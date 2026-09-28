# VPS Hardening + n8n on Coolify Cloud — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the fresh Ubuntu 24.04 VPS (root password SSH, no firewall) and turn it into a hardened host running n8n via Coolify Cloud, with all configuration in code (Pyinfra + Pulumi).

**Architecture:** Two automation tools split by layer — Pyinfra for VPS-side OS configuration over SSH, Pulumi for Cloudflare DNS/zone settings. Coolify Cloud manages n8n (SQLite on a persistent volume) on the hardened VPS via SSH as a dedicated `coolify` user. All long-lived secrets in password manager / Coolify secrets / Pulumi-encrypted config — never in git.

**Tech Stack:** Python (uv-managed), Pyinfra 3.x, Pulumi (Python SDK + Cloud free tier), Cloudflare R2 (backups), restic, n8n 2.x (pin exact tag at deploy time), SQLite, Docker, ufw, fail2ban, BetterStack (uptime monitoring).

**Source of truth for every decision:** `docs/superpowers/specs/2026-04-15-vps-hardening-coolify-design.md`.

---

## How to use this plan

- Each **Phase** is a checkpoint. Stop after a phase, verify, then proceed.
- **Manual** steps are clearly labelled — they involve a UI, a password manager, or a sanity check.
- **Automated** steps run `uv run pyinfra ...` or `uv run pulumi ...` — wait for the command to succeed before continuing.
- **Verification** steps tell you what to look for. If the verification fails, stop and diagnose before continuing.
- **All commands are run from `~/workspace/vpsconfig` unless stated otherwise.**
- **Commit after every task** — frequent small commits are recoverable; one big commit is not.

---

## Phase 0 — Local laptop bootstrap

**Goal:** Workstation has all tools, repo has Python project skeleton.

### Task 0.1: Install local tools

- [ ] **Step 1: Verify Homebrew is installed**

```bash
brew --version
```

Expected: a version number. If "command not found", install from https://brew.sh first.

- [ ] **Step 2: Install uv, pulumi, restic** (restic only used for restore drills locally)

```bash
brew install uv pulumi restic
```

- [ ] **Step 3: Verify versions**

```bash
uv --version
pulumi version
restic version
```

Expected: each prints a version (uv >=0.4, pulumi >=3.140, restic >=0.17). No errors.

### Task 0.2: Generate dedicated SSH keypair for the VPS

- [ ] **Step 1: Check for existing key**

```bash
ls -la ~/.ssh/id_ed25519_vps* 2>/dev/null || echo "no key yet"
```

If the key exists, **skip to Task 0.3**.

- [ ] **Step 2: Generate the key** (no passphrase prompt loop — set one in your password manager and paste)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vps -C "vps-satmur-$(date +%Y%m%d)"
```

When prompted for passphrase, **use a passphrase from your password manager** (don't leave empty — laptop theft = VPS access).

- [ ] **Step 3: Add to ssh-agent so we don't re-prompt repeatedly**

```bash
ssh-add ~/.ssh/id_ed25519_vps
```

Expected: "Identity added: …".

- [ ] **Step 4: Verify the public key**

```bash
cat ~/.ssh/id_ed25519_vps.pub
```

Expected: a single line starting `ssh-ed25519 AAAA…`. Copy this to clipboard for the next task.

### Task 0.3: Copy SSH key to VPS root (one-time password use)

- [ ] **Step 1: Use ssh-copy-id with the dedicated key**

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_vps.pub root@198.144.178.149
```

You'll be prompted for the root password (one last time). Enter it.
Expected: "Number of key(s) added: 1".

- [ ] **Step 2: Verify key-based login works (no password)**

```bash
ssh -i ~/.ssh/id_ed25519_vps root@198.144.178.149 "whoami && hostname"
```

Expected output:
```
root
vps149257-lr5
```

If it prompts for password, the key wasn't added — re-run Step 1.

### Task 0.4: Initialize uv project

- [ ] **Step 1: Initialize uv project in the existing repo**

```bash
cd ~/workspace/vpsconfig
uv init --python 3.12 --no-readme --no-pin-python --vcs none
```

Note: `--no-pin-python` because we'll create a `.python-version` ourselves; `--vcs none` because git is already initialized.

- [ ] **Step 2: Pin Python version explicitly**

```bash
echo "3.12" > .python-version
```

- [ ] **Step 3: Install Python 3.12 via uv** (so we don't depend on system Python)

```bash
uv python install 3.12
```

Expected: "Installed Python 3.12.x" (or "already installed").

- [ ] **Step 4: Add Pyinfra and Pulumi dependencies**

```bash
uv add 'pyinfra>=3.0' 'pulumi>=3.140' 'pulumi-cloudflare>=5.40'
```

Expected: dependencies resolve, `pyproject.toml` and `uv.lock` updated, `.venv/` created.

- [ ] **Step 5: Verify `uv run` works**

```bash
uv run python -c "import pyinfra; import pulumi; import pulumi_cloudflare; print('ok')"
```

Expected: `ok`.

### Task 0.5: Create .gitignore

- [ ] **Step 1: Create `.gitignore`**

Write file `.gitignore` with this exact content:

```
# Python / uv
.venv/
__pycache__/
*.pyc
*.pyo
.python-version-local
.pytest_cache/

# Pulumi
.pulumi/

# Local environment
.env
.env.local
*.local

# OS
.DS_Store
Thumbs.db

# Editor
.vscode/
.idea/
*.swp
*.swo
*~

# Secrets — explicitly excluded even though our flow shouldn't put them here
*.pem
*.key
secrets/
```

- [ ] **Step 2: Verify the venv isn't tracked**

```bash
git status --short
```

Expected: `.venv/` does NOT appear. If it does, your `.gitignore` isn't right.

### Task 0.6: Create directory skeleton

- [ ] **Step 1: Create directories**

```bash
mkdir -p pyinfra/tasks pyinfra/files pulumi
touch pyinfra/__init__.py pyinfra/tasks/__init__.py
```

- [ ] **Step 2: Verify**

```bash
find pyinfra pulumi -type d
```

Expected:
```
pyinfra
pyinfra/tasks
pyinfra/files
pulumi
```

### Task 0.7: Commit Phase 0

- [ ] **Step 1: Stage and commit**

```bash
git add .gitignore .python-version pyproject.toml uv.lock pyinfra pulumi
git commit -m "chore: initialize uv project, pyinfra and pulumi skeletons"
```

- [ ] **Step 2: Verify**

```bash
git log --oneline
```

Expected: 2 commits (the spec from earlier + this one).

---

## Phase 1 — Cloudflare manual prep

**Goal:** All Cloudflare-side resources and tokens that Pulumi cannot bootstrap (chicken-and-egg) exist before we run anything.

### Task 1.1: Sign in to Pulumi Cloud and authenticate CLI

- [ ] **Step 1 (manual):** Confirm your Pulumi Cloud account (created earlier). Note the organization name (likely your username).

- [ ] **Step 2: Authenticate the CLI**

```bash
pulumi login
```

This opens a browser. Approve the device login. Return to terminal.
Expected: "Logged in to pulumi.com as <your-username>".

### Task 1.2: Create Cloudflare API token for Pulumi

- [ ] **Step 1 (manual):** Sign in to https://dash.cloudflare.com → click your profile (top-right) → **My Profile** → **API Tokens** → **Create Token**.

- [ ] **Step 2 (manual):** Click **Create Custom Token**. Configure exactly:

| Field | Value |
|---|---|
| Token name | `pulumi-satmur` |
| Permissions | Add three rows: |
| | `Zone` → `Zone` → `Read` |
| | `Zone` → `DNS` → `Edit` |
| | `Zone` → `Zone Settings` → `Edit` |
| Zone Resources | `Include` → `Specific zone` → `satmur.com` |
| Client IP Address Filtering | (leave empty) |
| TTL | Optional. Recommend setting expiry 1 year out, calendar reminder to rotate. |

Click **Continue to summary** → **Create Token**.

- [ ] **Step 3 (manual):** Cloudflare shows the token **once**. Copy it now.

- [ ] **Step 4 (manual):** Paste it into your password manager under entry `Cloudflare API token — pulumi-satmur` for safekeeping. (Pulumi will store its own encrypted copy in the next phase.)

- [ ] **Step 5 (manual):** Test the token before leaving the page — Cloudflare provides a curl command. Run it.

Expected: JSON response with `"status": "active"`. If 401, the token is bad — regenerate.

### Task 1.3: Create Cloudflare API token for Coolify cert renewal

- [ ] **Step 1 (manual):** Repeat the dashboard flow from Task 1.2, but configure:

| Field | Value |
|---|---|
| Token name | `coolify-cert-renewal` |
| Permissions | `Zone` → `Zone` → `Read` |
| | `Zone` → `DNS` → `Edit` |
| Zone Resources | `Include` → `Specific zone` → `satmur.com` |
| TTL | 1 year, calendar reminder. |

- [ ] **Step 2 (manual):** Save the token in your password manager under `Cloudflare API token — coolify-cert-renewal`. We'll paste it into Coolify in Phase 7.

### Task 1.4: Create Cloudflare R2 bucket and access token

- [ ] **Step 1 (manual):** In Cloudflare dashboard, sidebar → **R2** → **Create bucket**.
  - Name: `satmur-backups`
  - Location: Automatic (or your nearest region)
  - Click **Create bucket**.

- [ ] **Step 2 (manual):** In the R2 sidebar, **Manage R2 API Tokens** → **Create API token**.
  - Token name: `satmur-backups-rw`
  - Permissions: **Object Read & Write**
  - Specify bucket: `satmur-backups` only
  - TTL: 1 year (calendar reminder).
  - Click **Create API Token**.

- [ ] **Step 3 (manual):** Cloudflare shows three values **once**:
  - **Access Key ID**
  - **Secret Access Key**
  - **Endpoint URL** (looks like `https://<account-id>.r2.cloudflarestorage.com`)

  Copy all three to your password manager under entry `R2 — satmur-backups`.

- [ ] **Step 4 (manual):** Verify access from your laptop using `rclone` (optional but recommended). Skip if you don't already have rclone configured — we'll use the credentials from the VPS later.

---

## Phase 2 — Pulumi: Cloudflare DNS and zone settings

**Goal:** DNS A/AAAA records for `n8n.satmur.com` exist (proxied), zone TLS settings configured. Verifiable with `dig`.

### Task 2.1: Initialize Pulumi project

- [ ] **Step 1: Initialize the Pulumi project (uses Pulumi Cloud KMS for secrets, the default)**

```bash
cd ~/workspace/vpsconfig/pulumi
uv run pulumi new python --name vpsconfig-cf --description "Cloudflare DNS for satmur" --stack prod
```

When prompted:
- Project name: accept `vpsconfig-cf`
- Project description: accept
- Stack name: `prod`
- Toolchain: `pip` (we'll discard the auto-created venv next; we use uv at the repo root)

Pulumi creates: `Pulumi.yaml`, `Pulumi.prod.yaml`, `requirements.txt`, `__main__.py`, `venv/`.

- [ ] **Step 2: Discard Pulumi's auto-created venv (we manage Python deps via uv at the repo root)**

```bash
cd ~/workspace/vpsconfig/pulumi
rm -rf venv requirements.txt
```

- [ ] **Step 3: Tell Pulumi to use the repo-root uv-managed Python instead of `pulumi/venv`**

Edit `pulumi/Pulumi.yaml` and replace the `runtime:` block with:

```yaml
runtime:
  name: python
  options:
    virtualenv: ../.venv
    toolchain: pip
```

(`../.venv` points back to the uv-managed venv at the repo root.)

- [ ] **Step 4: Verify uv-managed deps cover Pulumi**

```bash
cd ~/workspace/vpsconfig
uv run python -c "import pulumi_cloudflare; print(pulumi_cloudflare.__version__)"
```

Expected: a version number (>=5.40).

### Task 2.2: Configure Pulumi stack with Cloudflare token and account ID

- [ ] **Step 1: Find your Cloudflare account ID**

In Cloudflare dashboard → click `satmur.com` zone → right sidebar shows **Account ID**. Copy it.

- [ ] **Step 2: Set non-secret config**

```bash
cd ~/workspace/vpsconfig/pulumi
uv run pulumi config set cloudflare:accountId <your-account-id>
uv run pulumi config set satmur:domain satmur.com
uv run pulumi config set satmur:vpsIPv4 198.144.178.149
uv run pulumi config set satmur:vpsIPv6 2606:c680:2000:2e::beeb:154d
uv run pulumi config set satmur:n8nSubdomain n8n
```

- [ ] **Step 3: Set the Cloudflare API token as a secret**

```bash
uv run pulumi config set --secret cloudflare:apiToken <paste-pulumi-satmur-token>
```

- [ ] **Step 4: Verify config (secrets shown as `[secret]`)**

```bash
uv run pulumi config
```

Expected: shows `cloudflare:accountId`, `cloudflare:apiToken [secret]`, and the `satmur:*` keys.

### Task 2.3: Write Pulumi Cloudflare resources

- [ ] **Step 1:** Replace `pulumi/__main__.py` with this content:

```python
"""Cloudflare DNS and zone settings for satmur.com."""

import pulumi
import pulumi_cloudflare as cloudflare

# --- Config ---
config = pulumi.Config("satmur")
domain = config.require("domain")
vps_ipv4 = config.require("vpsIPv4")
vps_ipv6 = config.require("vpsIPv6")
n8n_subdomain = config.require("n8nSubdomain")

# --- Look up the existing zone (we registered it via Cloudflare Registrar) ---
zone = cloudflare.get_zone(name=domain)

# --- DNS records for n8n.<domain>, both A and AAAA, both proxied ---
n8n_a = cloudflare.Record(
    "n8n_a",
    zone_id=zone.id,
    name=n8n_subdomain,
    type="A",
    content=vps_ipv4,
    proxied=True,
    ttl=1,  # 1 = Cloudflare auto when proxied
    comment="n8n service — managed by Pulumi (vpsconfig repo)",
)

n8n_aaaa = cloudflare.Record(
    "n8n_aaaa",
    zone_id=zone.id,
    name=n8n_subdomain,
    type="AAAA",
    content=vps_ipv6,
    proxied=True,
    ttl=1,
    comment="n8n service — managed by Pulumi (vpsconfig repo)",
)

# --- Zone-level SSL/TLS settings ---
# Full Strict requires a real cert on origin. Coolify/Traefik will provision
# Let's Encrypt via DNS-01 challenge using a separate Cloudflare API token.
zone_settings = cloudflare.ZoneSettingsOverride(
    "satmur_zone_settings",
    zone_id=zone.id,
    settings=cloudflare.ZoneSettingsOverrideSettingsArgs(
        ssl="strict",
        min_tls_version="1.2",
        always_use_https="on",
        automatic_https_rewrites="on",
        opportunistic_encryption="on",
        tls_1_3="on",
    ),
)

# --- Outputs for downstream tools / humans ---
pulumi.export("zone_id", zone.id)
pulumi.export("n8n_fqdn", f"{n8n_subdomain}.{domain}")
```

- [ ] **Step 2: Lint-check by importing the module**

```bash
cd ~/workspace/vpsconfig/pulumi
uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('m', '__main__.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)"
```

Expected: errors out at the `pulumi.Config` call because there's no Pulumi context — that's fine, means the imports and syntax are OK. Any `SyntaxError` or `ImportError` is real.

### Task 2.4: Pulumi preview (dry-run, must succeed before `up`)

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig/pulumi
uv run pulumi preview
```

Expected:
- 3 resources to create: `n8n_a`, `n8n_aaaa`, `satmur_zone_settings`
- 0 to update, 0 to delete
- No error messages

If the preview fails:
- 401/403 → token wrong scope, recreate from Task 1.2
- "no zone matching" → zone name mismatch; check `pulumi config get satmur:domain`

### Task 2.5: Pulumi up (apply)

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig/pulumi
uv run pulumi up
```

Review the plan, type `yes` to confirm.
Expected: "Resources: 3 created" and outputs include `n8n_fqdn: n8n.satmur.com`.

### Task 2.6: Verify DNS

- [ ] **Step 1: Resolve via Cloudflare DNS (1.1.1.1 to bypass any local cache)**

```bash
dig +short @1.1.1.1 n8n.satmur.com
dig +short @1.1.1.1 AAAA n8n.satmur.com
```

Expected: each returns IPs in Cloudflare's range (104.x.x.x or 172.x.x.x for v4; 2606:4700::… for v6). **NOT** your VPS IP — that means the proxy is on (correct).

- [ ] **Step 2: Verify zone settings via API**

```bash
curl -s -H "Authorization: Bearer <your-pulumi-satmur-token>" \
  "https://api.cloudflare.com/client/v4/zones/$(uv run pulumi -C ~/workspace/vpsconfig/pulumi stack output zone_id)/settings/ssl" | jq '.result.value'
```

Expected: `"strict"`.

### Task 2.7: Commit Phase 2

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig
git add pulumi/
git commit -m "feat(pulumi): add Cloudflare DNS records and SSL settings for n8n.satmur.com"
```

`Pulumi.prod.yaml` is committed because the secret in it is **encrypted** by Pulumi Cloud KMS (safe to commit).

---

## Phase 3 — Pyinfra: SSH bootstrap (highest-risk phase)

**Goal:** `maddalab` and `coolify` users exist, SSH is hardened (no root, no password), you've verified you can still log in. Mistakes here lock you out.

> **Discipline reminder:** Keep the existing `root` SSH session open in Terminal Window A throughout this phase. Test every change in a NEW terminal window. Only close Window A after Phase 3 is fully verified.

### Task 3.1: Open insurance terminals

- [ ] **Step 1 (manual):** Open Terminal Window A. SSH into the VPS as root using the key we set up:

```bash
ssh -i ~/.ssh/id_ed25519_vps root@198.144.178.149
```

Leave this open for the entire phase. Don't close it.

- [ ] **Step 2 (manual):** Open Terminal Window B (separate). This is where you'll run pyinfra and tests. Confirm you're NOT logged into the VPS in this window.

### Task 3.2: Write pyinfra inventory for the bootstrap (root + key)

- [ ] **Step 1:** Create `pyinfra/inventory_bootstrap.py`:

```python
"""Inventory used ONLY for the initial bootstrap pass.

Connects as root using the SSH key we already deployed via ssh-copy-id.
After Phase 3 completes, this inventory is no longer used — switch to
inventory.py (which connects as maddalab).
"""

vps = (
    "198.144.178.149",
    {
        "ssh_user": "root",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "ssh_port": 22,
    },
)

hosts = [vps]
```

- [ ] **Step 2:** Create `pyinfra/inventory.py` (the steady-state inventory we'll use after Phase 3):

```python
"""Inventory for the hardened state — connect as maddalab via SSH key."""

vps = (
    "198.144.178.149",
    {
        "ssh_user": "maddalab",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "ssh_port": 22,
    },
)

hosts = [vps]
```

### Task 3.3: Read your SSH public key into the deploy

- [ ] **Step 1:** We need `maddalab` to receive your laptop's public key. The deploy will read it from the file at run time (not committed):

```bash
cat ~/.ssh/id_ed25519_vps.pub
```

Confirm output is your public key. (We'll reference this path in Python in the next task.)

### Task 3.4: Write the bootstrap deploy script

- [ ] **Step 1:** Create `pyinfra/bootstrap.py`:

```python
"""One-time bootstrap: create maddalab and coolify users.

Run from the project root:
    uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/bootstrap.py

After this succeeds AND you've verified the new users work, run Phase 3.7
(SSH hardening) using this same inventory, then switch to inventory.py.
"""

from pathlib import Path

from pyinfra import host
from pyinfra.operations import files, server

# --- Read your laptop's public key (path is local to your laptop) ---
LAPTOP_PUBKEY_PATH = Path.home() / ".ssh" / "id_ed25519_vps.pub"
laptop_pubkey = LAPTOP_PUBKEY_PATH.read_text().strip()

# --- maddalab user: human admin, sudo with password ---
server.user(
    name="Create maddalab admin user",
    user="maddalab",
    groups=["sudo"],
    shell="/bin/bash",
    create_home=True,
    ensure_home=True,
)

files.directory(
    name="Ensure maddalab .ssh directory",
    path="/home/maddalab/.ssh",
    user="maddalab",
    group="maddalab",
    mode="700",
)

files.file(
    name="Ensure maddalab authorized_keys exists",
    path="/home/maddalab/.ssh/authorized_keys",
    user="maddalab",
    group="maddalab",
    mode="600",
    touch=True,
)

files.line(
    name="Add laptop public key to maddalab authorized_keys",
    path="/home/maddalab/.ssh/authorized_keys",
    line=laptop_pubkey,
)

# --- maddalab needs a password set so sudo works ---
# We DO NOT bake the password into git. The deploy will prompt operator
# to set a password manually after this script. See Task 3.6.

# --- coolify user: Coolify Cloud SSH agent, NOPASSWD sudo ---
server.user(
    name="Create coolify system user",
    user="coolify",
    groups=[],
    shell="/bin/bash",
    create_home=True,
    ensure_home=True,
)

files.directory(
    name="Ensure coolify .ssh directory",
    path="/home/coolify/.ssh",
    user="coolify",
    group="coolify",
    mode="700",
)

files.file(
    name="Ensure coolify authorized_keys exists",
    path="/home/coolify/.ssh/authorized_keys",
    user="coolify",
    group="coolify",
    mode="600",
    touch=True,
)

# Coolify Cloud's public key is added in Phase 7 from their UI.
# We deliberately leave coolify's authorized_keys empty here.

files.put(
    name="Install coolify NOPASSWD sudoers entry",
    src="pyinfra/files/sudoers-coolify",
    dest="/etc/sudoers.d/coolify",
    user="root",
    group="root",
    mode="440",
)
```

- [ ] **Step 2:** Create `pyinfra/files/sudoers-coolify`:

```
# Coolify Cloud agent — needs unattended sudo to install/manage Docker.
# Keep this file mode 0440 owned by root.
coolify ALL=(ALL) NOPASSWD: ALL
```

### Task 3.5: Run the bootstrap deploy

- [ ] **Step 1: Dry-run first** (in Terminal Window B)

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/bootstrap.py --dry
```

Expected: lists each operation as "Pending" (would change state). No errors.

- [ ] **Step 2: Apply for real**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/bootstrap.py
```

Expected output includes `[198.144.178.149] Success` for each operation. Final summary should show all green.

If anything fails — **STOP**. Do not proceed. Diagnose using Terminal Window A (you're root, you can read logs and revert).

### Task 3.6: Set maddalab password (manual, on the VPS)

- [ ] **Step 1 (manual):** In Terminal Window A (still root on VPS):

```bash
passwd maddalab
```

Choose a strong password. Type it twice. **Save it in your password manager** under entry `VPS satmur — maddalab sudo password`.

- [ ] **Step 2 (manual):** Verify password set:

```bash
chage -l maddalab
```

Expected: `Last password change` shows today's date.

### Task 3.7: SANITY CHECK — verify maddalab login works

- [ ] **Step 1 (manual):** Open **Terminal Window C** (third terminal, separate from A and B).

- [ ] **Step 2 (manual):** SSH as maddalab:

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149
```

Expected: prompt becomes `maddalab@vps149257-lr5:~$`. **No password prompted.**

- [ ] **Step 3 (manual): Verify sudo works (with password)**

In Window C:

```bash
sudo whoami
```

Expected: prompts for password (the one you just set in Task 3.6), then prints `root`.

- [ ] **Step 4 (manual): If any of the above fails, do NOT proceed. Diagnose from Window A (still root).**

Common failures:
- "Permission denied (publickey)": the public key wasn't added to `/home/maddalab/.ssh/authorized_keys`. Check from Window A: `cat /home/maddalab/.ssh/authorized_keys`.
- "sudo: maddalab is not in the sudoers file": the user wasn't added to the sudo group. Fix from Window A: `usermod -aG sudo maddalab`.

### Task 3.8: Write SSH hardening task module

- [ ] **Step 1:** Create `pyinfra/files/sshd-hardening.conf`:

```
# Managed by pyinfra — see pyinfra/tasks/ssh.py
# This file lives in /etc/ssh/sshd_config.d/99-hardening.conf and overrides
# the defaults in /etc/ssh/sshd_config.

PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers maddalab coolify
Protocol 2
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
```

- [ ] **Step 2:** Create `pyinfra/tasks/ssh.py`:

```python
"""SSH daemon hardening.

Disables root login, password auth, etc. Restarts sshd at the end.
ALWAYS run AFTER you've verified the non-root admin user can log in
(see Phase 3.7 in the implementation plan).
"""

from pyinfra.operations import files, systemd

files.put(
    name="Install sshd hardening drop-in config",
    src="pyinfra/files/sshd-hardening.conf",
    dest="/etc/ssh/sshd_config.d/99-hardening.conf",
    user="root",
    group="root",
    mode="644",
)

# Validate config syntax before reloading. If sshd -t fails, sshd will not
# restart and we'll see the error in pyinfra output.
from pyinfra.operations import server  # noqa: E402

server.shell(
    name="Validate sshd config syntax",
    commands=["sshd -t"],
)

systemd.service(
    name="Reload sshd",
    service="ssh",
    reloaded=True,
)
```

### Task 3.9: Apply SSH hardening (still using bootstrap inventory = root)

- [ ] **Step 1: Dry-run**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/tasks/ssh.py --dry
```

Expected: 3 pending operations.

- [ ] **Step 2: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/tasks/ssh.py
```

Expected: success on all 3 operations.

### Task 3.10: SANITY CHECK — SSH still works for maddalab, root is rejected

> **CRITICAL:** Do these tests in Windows B and C. Keep Window A (the existing root session) open — if anything is wrong, you can fix from there.

- [ ] **Step 1 (manual): Verify maddalab can still log in (Window C)**

Open a fresh Window C session:

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "echo ok"
```

Expected: `ok`.

If this fails: **stop**. Use Window A (root) to fix `/etc/ssh/sshd_config.d/99-hardening.conf`. Most likely culprit: `AllowUsers` typo.

- [ ] **Step 2 (manual): Verify root SSH login is rejected (Window B)**

```bash
ssh -i ~/.ssh/id_ed25519_vps root@198.144.178.149 "echo unexpected_root_login"
```

Expected: `Permission denied (publickey)` or `Connection closed`.

If you see `unexpected_root_login`: hardening didn't apply. Check `/etc/ssh/sshd_config.d/` from Window A.

- [ ] **Step 3 (manual): Confirm only maddalab and coolify are in AllowUsers**

In Window C:

```bash
sudo cat /etc/ssh/sshd_config.d/99-hardening.conf
```

Verify the file matches what you wrote.

- [ ] **Step 4 (manual): Now safe to close Window A.** Close it.

### Task 3.11: Commit Phase 3

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig
git add pyinfra/
git commit -m "feat(pyinfra): bootstrap users (maddalab, coolify) and harden sshd"
```

---

## Phase 4 — Pyinfra: System hardening

**Goal:** Hostname/timezone/swap set, ufw + Cloudflare-IP allowlist active, fail2ban running, unattended-upgrades configured, AppArmor verified.

From here on, **all pyinfra commands use `inventory.py`** (which connects as `maddalab`). pyinfra will use sudo where needed.

### Task 4.1: Configure pyinfra to use sudo

- [ ] **Step 1:** Update `pyinfra/inventory.py` to enable sudo:

```python
"""Inventory for the hardened state — connect as maddalab via SSH key, escalate via sudo."""

vps = (
    "198.144.178.149",
    {
        "ssh_user": "maddalab",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "ssh_port": 22,
        "_sudo": True,
        "_use_sudo_password": True,
    },
)

hosts = [vps]
```

- [ ] **Step 2: Test sudo connectivity** (will prompt for sudo password)

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py exec -- whoami
```

When prompted, enter maddalab's sudo password. Expected output: `[198.144.178.149] >>> root`.

(If prompted multiple times, set `PYINFRA_SUDO_PASSWORD` env var or use `--sudo-password` flag.)

### Task 4.2: System config task (hostname, timezone, locale, swap)

- [ ] **Step 1:** Create `pyinfra/tasks/system.py`:

```python
"""System-level config: hostname, timezone, locale, swap file."""

from pyinfra.operations import files, server, apt

# --- Hostname ---
server.hostname(
    name="Set hostname to satmur",
    hostname="satmur",
)

# --- Timezone (UTC) ---
server.shell(
    name="Set timezone to UTC",
    commands=["timedatectl set-timezone UTC"],
)

# --- Locale: ensure en_US.UTF-8 generated and default ---
apt.packages(
    name="Ensure locales package present",
    packages=["locales"],
    update=False,
)

server.shell(
    name="Generate en_US.UTF-8 locale",
    commands=[
        "locale-gen en_US.UTF-8",
        "update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8",
    ],
)

# --- Swap file (2 GB at /swapfile) ---
# Idempotent: check before creating.
server.shell(
    name="Create 2GB swap file at /swapfile",
    commands=[
        "test -f /swapfile || (fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile)",
    ],
)

files.line(
    name="Persist swap in /etc/fstab",
    path="/etc/fstab",
    line="/swapfile none swap sw 0 0",
)

files.put(
    name="Apply swappiness/cache-pressure tuning",
    src="pyinfra/files/sysctl-swap.conf",
    dest="/etc/sysctl.d/60-swap.conf",
    user="root",
    group="root",
    mode="644",
)

server.shell(
    name="Reload sysctl",
    commands=["sysctl --system"],
)
```

- [ ] **Step 2:** Create `pyinfra/files/sysctl-swap.conf`:

```
# Swap and cache pressure tuning — see docs/superpowers/specs/2026-04-15-vps-hardening-coolify-design.md §3.1
vm.swappiness=10
vm.vfs_cache_pressure=50
```

- [ ] **Step 3: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/system.py
```

Expected: all operations succeed. The hostname change may show "Pending host: satmur" — normal.

- [ ] **Step 4: Verify**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "hostname && timedatectl | grep 'Time zone' && swapon --show && cat /proc/sys/vm/swappiness"
```

Expected:
```
satmur
                Time zone: UTC (UTC, +0000)
NAME      TYPE SIZE USED PRIO
/swapfile file   2G   0B   -2
10
```

### Task 4.3: Firewall (ufw + Cloudflare IP refresh)

- [ ] **Step 1:** Create `pyinfra/files/cloudflare-ufw-update.sh`:

```bash
#!/usr/bin/env bash
# Refresh ufw rules to allow only Cloudflare IPs on 80/443.
# Run by cloudflare-ufw-update.service (triggered weekly).
# On fetch failure, leaves existing rules in place. Never opens up access.

set -euo pipefail

CF_V4_URL="https://www.cloudflare.com/ips-v4"
CF_V6_URL="https://www.cloudflare.com/ips-v6"
LOG_TAG="cloudflare-ufw-update"

logger -t "$LOG_TAG" "starting refresh"

# Fetch into temp files first; only proceed if both succeed.
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if ! curl -fsSL --max-time 30 "$CF_V4_URL" -o "$TMPDIR/v4.txt"; then
    logger -t "$LOG_TAG" "ERROR: failed to fetch $CF_V4_URL — leaving existing rules in place"
    exit 1
fi
if ! curl -fsSL --max-time 30 "$CF_V6_URL" -o "$TMPDIR/v6.txt"; then
    logger -t "$LOG_TAG" "ERROR: failed to fetch $CF_V6_URL — leaving existing rules in place"
    exit 1
fi

# Sanity-check fetched data: must be at least 1 line each, must look like CIDRs.
if [[ ! -s "$TMPDIR/v4.txt" ]] || [[ ! -s "$TMPDIR/v6.txt" ]]; then
    logger -t "$LOG_TAG" "ERROR: fetched IP list was empty — leaving existing rules in place"
    exit 1
fi
grep -qE '^[0-9.]+/[0-9]+$' "$TMPDIR/v4.txt" || { logger -t "$LOG_TAG" "ERROR: v4 list malformed"; exit 1; }
grep -qE '^[0-9a-f:]+/[0-9]+$' "$TMPDIR/v6.txt" || { logger -t "$LOG_TAG" "ERROR: v6 list malformed"; exit 1; }

# Remove all existing ufw rules tagged "cloudflare" (we tag via comment).
# ufw --dry-run delete rules by index — too fragile. Use a marker approach:
# delete all 80/443 ALLOW rules, then re-add from scratch.
# Read current rules and delete the ones matching 80/tcp or 443/tcp.
ufw status numbered | grep -E 'ALLOW.*\b(80|443)/tcp\b' | awk -F'[][]' '{print $2}' | sort -rn | while read -r idx; do
    yes | ufw delete "$idx" >/dev/null 2>&1 || true
done

# Add fresh rules.
while read -r cidr; do
    [[ -z "$cidr" ]] && continue
    ufw allow proto tcp from "$cidr" to any port 80 comment 'cloudflare-managed' >/dev/null
    ufw allow proto tcp from "$cidr" to any port 443 comment 'cloudflare-managed' >/dev/null
done < "$TMPDIR/v4.txt"

while read -r cidr; do
    [[ -z "$cidr" ]] && continue
    ufw allow proto tcp from "$cidr" to any port 80 comment 'cloudflare-managed' >/dev/null
    ufw allow proto tcp from "$cidr" to any port 443 comment 'cloudflare-managed' >/dev/null
done < "$TMPDIR/v6.txt"

ufw reload >/dev/null
V4_COUNT=$(wc -l < "$TMPDIR/v4.txt")
V6_COUNT=$(wc -l < "$TMPDIR/v6.txt")
logger -t "$LOG_TAG" "refresh complete — $V4_COUNT v4 + $V6_COUNT v6 ranges allowed on 80/443"
```

- [ ] **Step 2:** Create `pyinfra/files/cloudflare-ufw-update.service`:

```
[Unit]
Description=Refresh ufw rules to allow only Cloudflare IPs on 80/443
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cloudflare-ufw-update.sh
```

- [ ] **Step 3:** Create `pyinfra/files/cloudflare-ufw-update.timer`:

```
[Unit]
Description=Weekly refresh of Cloudflare IP allowlist for ufw

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
```

- [ ] **Step 4:** Create `pyinfra/files/ufw-defaults`:

```
# Edit at your peril. /etc/default/ufw managed by pyinfra.
IPV6=yes
DEFAULT_INPUT_POLICY="DROP"
DEFAULT_OUTPUT_POLICY="ACCEPT"
DEFAULT_FORWARD_POLICY="DROP"
DEFAULT_APPLICATION_POLICY="SKIP"
MANAGE_BUILTINS=no
IPT_SYSCTL=/etc/ufw/sysctl.conf
IPT_MODULES=""
```

- [ ] **Step 5:** Create `pyinfra/tasks/firewall.py`:

```python
"""ufw firewall + Cloudflare IP refresh timer."""

from pyinfra.operations import apt, files, server, systemd

apt.packages(
    name="Install ufw + curl",
    packages=["ufw", "curl"],
    update=True,
    cache_time=3600,
)

# --- ufw defaults file (sets IPV6=yes etc.) ---
files.put(
    name="Install ufw defaults",
    src="pyinfra/files/ufw-defaults",
    dest="/etc/default/ufw",
    user="root",
    group="root",
    mode="644",
)

# --- Bootstrap rules: allow ssh; web ports added by the refresh script ---
server.shell(
    name="Allow SSH (22/tcp) from anywhere",
    commands=["ufw allow 22/tcp comment 'ssh'"],
)

# Set defaults explicitly via ufw cli (in addition to /etc/default/ufw)
server.shell(
    name="Set ufw default policies",
    commands=[
        "ufw --force default deny incoming",
        "ufw --force default allow outgoing",
        "ufw --force default deny routed",
    ],
)

# --- Cloudflare IP refresh script + timer ---
files.put(
    name="Install cloudflare-ufw-update.sh",
    src="pyinfra/files/cloudflare-ufw-update.sh",
    dest="/usr/local/sbin/cloudflare-ufw-update.sh",
    user="root",
    group="root",
    mode="755",
)

files.put(
    name="Install cloudflare-ufw-update.service",
    src="pyinfra/files/cloudflare-ufw-update.service",
    dest="/etc/systemd/system/cloudflare-ufw-update.service",
    user="root",
    group="root",
    mode="644",
)

files.put(
    name="Install cloudflare-ufw-update.timer",
    src="pyinfra/files/cloudflare-ufw-update.timer",
    dest="/etc/systemd/system/cloudflare-ufw-update.timer",
    user="root",
    group="root",
    mode="644",
)

systemd.daemon_reload(name="systemctl daemon-reload")

# Run the service NOW to populate Cloudflare rules before enabling ufw
server.shell(
    name="Run cloudflare-ufw-update once to populate rules",
    commands=["systemctl start cloudflare-ufw-update.service"],
)

systemd.service(
    name="Enable + start cloudflare-ufw-update.timer",
    service="cloudflare-ufw-update.timer",
    enabled=True,
    running=True,
)

# Finally, enable ufw. --force avoids interactive prompt.
server.shell(
    name="Enable ufw",
    commands=["ufw --force enable"],
)
```

- [ ] **Step 6: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/firewall.py
```

Expected: all green. The "Run cloudflare-ufw-update" step may take ~10s.

- [ ] **Step 7: Verify**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo ufw status verbose | head -20"
```

Expected: shows `Status: active`, `Default: deny (incoming), allow (outgoing), deny (routed)`, and many `ALLOW IN` rules tagged `cloudflare-managed` plus the SSH rule.

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo ufw status numbered | grep -c cloudflare"
```

Expected: a number > 30 (Cloudflare publishes ~15 v4 + ~7 v6 ranges, each times 2 ports = ~44 rules).

- [ ] **Step 8: Verify the timer**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "systemctl list-timers cloudflare-ufw-update.timer --no-pager"
```

Expected: shows next run time.

### Task 4.4: fail2ban

- [ ] **Step 1:** Create `pyinfra/files/jail-local.conf`:

```ini
# /etc/fail2ban/jail.local — managed by pyinfra
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
```

- [ ] **Step 2:** Create `pyinfra/tasks/fail2ban.py`:

```python
"""fail2ban — single SSH jail, journald backend."""

from pyinfra.operations import apt, files, systemd

apt.packages(
    name="Install fail2ban",
    packages=["fail2ban"],
    update=False,
)

files.put(
    name="Install jail.local",
    src="pyinfra/files/jail-local.conf",
    dest="/etc/fail2ban/jail.local",
    user="root",
    group="root",
    mode="644",
)

systemd.service(
    name="Enable + restart fail2ban",
    service="fail2ban",
    enabled=True,
    running=True,
    restarted=True,
)
```

- [ ] **Step 3: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/fail2ban.py
```

- [ ] **Step 4: Verify**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo fail2ban-client status sshd"
```

Expected output includes:
```
Status for the jail: sshd
|- Filter
|  ...
|- Actions
|  |- Currently banned: 0
   ...
```

### Task 4.5: Unattended-upgrades

- [ ] **Step 1:** Create `pyinfra/files/50unattended-upgrades`:

```
// Managed by pyinfra. /etc/apt/apt.conf.d/50unattended-upgrades

Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

Unattended-Upgrade::Package-Blacklist { };
Unattended-Upgrade::DevRelease "auto";

Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::InstallOnShutdown "false";

// Reboot only if a kernel update needs it, at 04:00 UTC.
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-WithUsers "false";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";

// Email reporting disabled — no MTA configured. Output goes to journald.
Unattended-Upgrade::Mail "";
Unattended-Upgrade::MailReport "on-change";

Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
```

- [ ] **Step 2:** Create `pyinfra/files/20auto-upgrades`:

```
// Managed by pyinfra. /etc/apt/apt.conf.d/20auto-upgrades

APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
```

- [ ] **Step 3:** Create `pyinfra/tasks/unattended_upgrades.py`:

```python
"""Automatic security patches via unattended-upgrades."""

from pyinfra.operations import apt, files, systemd

apt.packages(
    name="Install unattended-upgrades",
    packages=["unattended-upgrades", "apt-listchanges"],
    update=False,
)

files.put(
    name="Install 50unattended-upgrades",
    src="pyinfra/files/50unattended-upgrades",
    dest="/etc/apt/apt.conf.d/50unattended-upgrades",
    user="root",
    group="root",
    mode="644",
)

files.put(
    name="Install 20auto-upgrades",
    src="pyinfra/files/20auto-upgrades",
    dest="/etc/apt/apt.conf.d/20auto-upgrades",
    user="root",
    group="root",
    mode="644",
)

systemd.service(
    name="Enable + start unattended-upgrades",
    service="unattended-upgrades",
    enabled=True,
    running=True,
)
```

- [ ] **Step 4: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/unattended_upgrades.py
```

- [ ] **Step 5: Verify config valid**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo unattended-upgrade --dry-run -d 2>&1 | tail -20"
```

Expected: completes without "Error" or "Exception". Final lines describe what would be installed (likely "No packages found that can be upgraded").

### Task 4.6: AppArmor verification (no install — Ubuntu default)

- [ ] **Step 1:** Verify enforce mode

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo aa-status | head -3"
```

Expected output:
```
apparmor module is loaded.
N profiles are loaded.
N profiles are in enforce mode.
```

### Task 4.7: Commit Phase 4

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig
git add pyinfra/
git commit -m "feat(pyinfra): system hardening — swap, ufw + CF allowlist, fail2ban, unattended-upgrades"
```

---

## Phase 5 — Provider firewall (manual, Virtualizor)

**Goal:** Defense-in-depth — same firewall rules at the hypervisor level.

### Task 5.1: Configure Virtualizor firewall

- [ ] **Step 1 (manual):** Sign in to your CheapWindowsVPS panel. Open `vps149257-lr5` → click the **Firewall** tab.

- [ ] **Step 2 (manual):** Get current Cloudflare IP ranges (you'll paste them into the panel):

```bash
curl -s https://www.cloudflare.com/ips-v4
echo "---"
curl -s https://www.cloudflare.com/ips-v6
```

- [ ] **Step 3 (manual):** Configure rules in the Virtualizor panel. Order matters — rules are evaluated top-down, first match wins:

| # | Direction | Protocol | Port | Source | Action |
|---|---|---|---|---|---|
| 1 | In | TCP | 22 | Anywhere | Allow |
| 2..N | In | TCP | 80 | Each Cloudflare v4 CIDR | Allow |
| N+1..M | In | TCP | 80 | Each Cloudflare v6 CIDR | Allow |
| M+1..K | In | TCP | 443 | Each Cloudflare v4 CIDR | Allow |
| K+1..L | In | TCP | 443 | Each Cloudflare v6 CIDR | Allow |
| Last | In | * | * | Anywhere | Deny |

- [ ] **Step 4 (manual):** Apply / Save. Verify from your laptop:

```bash
# SSH still works (port 22 from anywhere allowed)
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "echo provider_firewall_ok"
```

Expected: `provider_firewall_ok`.

- [ ] **Step 5 (manual):** Note in your calendar: review provider firewall every 6 months for Cloudflare IP changes.

---

## Phase 6 — Pyinfra: Docker

**Goal:** Docker installed, daemon configured for log rotation + live-restore, weekly prune timer enabled.

### Task 6.1: Docker daemon config + prune timer files

- [ ] **Step 1:** Create `pyinfra/files/docker-daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "live-restore": true
}
```

- [ ] **Step 2:** Create `pyinfra/files/docker-prune.service`:

```
[Unit]
Description=Prune unused Docker resources older than 7 days
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker system prune -af --volumes --filter "until=168h"
```

- [ ] **Step 3:** Create `pyinfra/files/docker-prune.timer`:

```
[Unit]
Description=Weekly Docker prune

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
```

### Task 6.2: Docker install task

- [ ] **Step 1:** Create `pyinfra/tasks/docker.py`:

```python
"""Install Docker CE from Docker's official apt repo + configure daemon + weekly prune timer."""

from pyinfra.operations import apt, files, server, systemd

# --- Prereqs ---
apt.packages(
    name="Install Docker prereqs",
    packages=["ca-certificates", "curl", "gnupg"],
    update=True,
    cache_time=3600,
)

# --- Docker GPG key ---
server.shell(
    name="Install Docker GPG key",
    commands=[
        "install -m 0755 -d /etc/apt/keyrings",
        "test -f /etc/apt/keyrings/docker.asc || "
        "(curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
        "  | tee /etc/apt/keyrings/docker.asc > /dev/null && "
        " chmod a+r /etc/apt/keyrings/docker.asc)",
    ],
)

# --- Docker apt repo ---
files.line(
    name="Add Docker apt repo",
    path="/etc/apt/sources.list.d/docker.list",
    line=(
        "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] "
        "https://download.docker.com/linux/ubuntu noble stable"
    ),
)

# --- Docker engine + plugins ---
apt.packages(
    name="Install Docker CE",
    packages=[
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ],
    update=True,
    cache_time=600,
)

# --- daemon.json ---
files.directory(
    name="Ensure /etc/docker exists",
    path="/etc/docker",
    user="root",
    group="root",
    mode="755",
)

files.put(
    name="Install /etc/docker/daemon.json",
    src="pyinfra/files/docker-daemon.json",
    dest="/etc/docker/daemon.json",
    user="root",
    group="root",
    mode="644",
)

systemd.service(
    name="Enable + restart Docker daemon",
    service="docker",
    enabled=True,
    running=True,
    restarted=True,  # to pick up daemon.json
)

# --- Weekly prune timer ---
files.put(
    name="Install docker-prune.service",
    src="pyinfra/files/docker-prune.service",
    dest="/etc/systemd/system/docker-prune.service",
    user="root",
    group="root",
    mode="644",
)

files.put(
    name="Install docker-prune.timer",
    src="pyinfra/files/docker-prune.timer",
    dest="/etc/systemd/system/docker-prune.timer",
    user="root",
    group="root",
    mode="644",
)

systemd.daemon_reload(name="systemctl daemon-reload")

systemd.service(
    name="Enable + start docker-prune.timer",
    service="docker-prune.timer",
    enabled=True,
    running=True,
)
```

- [ ] **Step 2: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/docker.py
```

Expected: all green. Docker install pulls ~200MB of packages — give it a minute.

- [ ] **Step 3: Verify Docker**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo docker version && sudo docker info | grep -E '(Logging Driver|Live Restore|Cgroup)'"
```

Expected:
- `Server: Docker Engine - Community, Version: 27.x` (or newer)
- `Logging Driver: json-file`
- `Live Restore Enabled: true`

- [ ] **Step 4: Verify prune timer**

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "systemctl list-timers docker-prune.timer --no-pager"
```

Expected: shows next scheduled run.

### Task 6.3: Commit Phase 6

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig
git add pyinfra/
git commit -m "feat(pyinfra): install Docker CE with log rotation + weekly prune timer"
```

---

## Phase 7 — Coolify Cloud server registration (manual + small pyinfra)

**Goal:** Coolify Cloud has a working SSH connection to the VPS as user `coolify`. Sentinel + Traefik containers running on the VPS.

### Task 7.1: Sign up for Coolify Cloud (if not done)

- [ ] **Step 1 (manual):** Go to https://app.coolify.io and sign up. Confirm email.

- [ ] **Step 2 (manual):** Create a new **Team** if prompted (default is fine).

### Task 7.2: Add the VPS as a Server in Coolify Cloud

- [ ] **Step 1 (manual):** In Coolify Cloud → **Servers** → **+ Add**.

- [ ] **Step 2 (manual):** Configure:

| Field | Value |
|---|---|
| Server name | `n8n` |
| Description | `n8n production VPS` |
| IP Address | `198.144.178.149` |
| User | `coolify` |
| Port | `22` |

Click **Continue**.

- [ ] **Step 3 (manual):** Coolify shows you a public SSH key. **Copy it.**

### Task 7.3: Install Coolify's public key on VPS via pyinfra

We deliberately keep this in code (not curl-piped manually) so it's reproducible.

- [ ] **Step 1:** Save Coolify's public key locally — do NOT commit it. Create `pyinfra/files/coolify-cloud.pub` (this file path is in `.gitignore` because of the `*.pub` not being filtered — let's add an explicit ignore):

Add to `.gitignore`:
```
pyinfra/files/coolify-cloud.pub
```

```bash
cd ~/workspace/vpsconfig
echo "pyinfra/files/coolify-cloud.pub" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore Coolify Cloud public key file"
```

- [ ] **Step 2:** Save the key (Window B):

```bash
cat > pyinfra/files/coolify-cloud.pub <<'EOF'
<paste-the-coolify-cloud-public-key-from-step-7.2-step-3>
EOF
```

- [ ] **Step 3:** Create `pyinfra/tasks/coolify_authorize.py`:

```python
"""Add Coolify Cloud's public key to coolify user's authorized_keys.

This file relies on pyinfra/files/coolify-cloud.pub which is .gitignored.
"""

from pathlib import Path
from pyinfra.operations import files

key_path = Path(__file__).parent.parent / "files" / "coolify-cloud.pub"
coolify_pubkey = key_path.read_text().strip()

files.line(
    name="Authorize Coolify Cloud key for coolify user",
    path="/home/coolify/.ssh/authorized_keys",
    line=coolify_pubkey,
)
```

- [ ] **Step 4:** Apply

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/coolify_authorize.py
```

Expected: 1 operation, success.

- [ ] **Step 5:** Verify

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo cat /home/coolify/.ssh/authorized_keys"
```

Expected: shows the Coolify Cloud public key.

### Task 7.4: Validate connection in Coolify Cloud UI

- [ ] **Step 1 (manual):** Back in Coolify Cloud → **Servers → n8n** → click **Validate Server**.

Expected: green checkmarks for SSH connectivity, sudo, and Docker. (Coolify detects existing Docker and skips install.)

- [ ] **Step 2 (manual):** Coolify will install its **Sentinel** (metrics agent) and **Traefik** (proxy). Wait ~1 minute.

- [ ] **Step 3 (manual):** Verify on the VPS:

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

Expected: at least `coolify-sentinel` and `coolify-proxy` (Traefik) containers running.

### Task 7.5: Configure Coolify with Cloudflare API token (for cert renewal)

- [ ] **Step 1 (manual):** In Coolify Cloud → **Servers → n8n** → **Settings** (or **Proxy** tab — UI varies by version) → find the **Wildcard Domain** / **DNS-01 Challenge** section.

- [ ] **Step 2 (manual):** Configure DNS-01 with Cloudflare:
  - Provider: **Cloudflare**
  - Email: your Cloudflare account email
  - API Token: paste the `coolify-cert-renewal` token from Task 1.3 (saved in your password manager)

- [ ] **Step 3 (manual):** Save. Coolify will use this for Let's Encrypt cert renewals via DNS-01.

---

## Phase 8 — n8n deployment via Coolify UI (SQLite)

**Goal:** n8n reachable at `https://n8n.satmur.com` with valid TLS cert, storing its data in SQLite on a persistent volume.

**Why SQLite, not Postgres:** single-user, single-instance n8n. SQLite is n8n's default, needs no extra service, secrets, or memory, and lives in the same volume as the rest of n8n's state. Trade-offs accepted: no queue mode / horizontal scaling, and backups must snapshot the database file safely (Phase 9). Migrating to Postgres later means exporting and re-importing workflows and credentials.

### Task 8.1: Create Coolify project + environment

- [ ] **Step 1 (manual):** Coolify Cloud → **Projects → + Add Project**.
  - Name: `automation`
  - Description: `n8n + workflows`

- [ ] **Step 2 (manual):** Inside the project: Coolify auto-creates a `production` environment. Confirm it exists.

### Task 8.2: Deploy n8n service

- [ ] **Step 1 (manual):** Look up the latest stable n8n version: https://docs.n8n.io/release-notes/ (cross-check tags at https://hub.docker.com/r/n8nio/n8n/tags)

  Pin to that exact tag (e.g., `2.41.3`). Note the version in your password manager next to the `n8n satmur.com` entry.

- [ ] **Step 2: Generate the encryption key**

```bash
openssl rand -base64 32 | tr -d /=+ | cut -c1-32
```

Paste it into your password manager **now** under `n8n satmur.com — encryption key`. Once n8n encrypts credentials with this key, losing it = losing all credentials.

- [ ] **Step 3 (manual):** In project → `production` → **+ New Resource → Docker Image**.

- [ ] **Step 4 (manual):** Configure:
  - Server: `n8n`
  - Name: `n8n`
  - Image: `n8nio/n8n:<pinned-version>` (NOT `:latest`)
  - Ports Exposes: `5678`
  - Domains: `https://n8n.satmur.com`

- [ ] **Step 5 (manual):** **Storages** tab: add a persistent volume. **Load-bearing** — the SQLite database lives here; without it every redeploy wipes all workflows and credentials.
  - Name: `n8n-data`
  - Destination path: `/home/node/.n8n`
  - Host path: leave empty (Coolify-managed Docker volume)

- [ ] **Step 6 (manual):** **Environment Variables** tab (the "Developer view" accepts `KEY=value` lines):

| Variable | Value | Mark as Secret? |
|---|---|---|
| `DB_TYPE` | `sqlite` | no |
| `DB_SQLITE_POOL_SIZE` | `2` | no |
| `N8N_ENCRYPTION_KEY` | (key from Step 2) | yes |
| `N8N_HOST` | `n8n.satmur.com` | no |
| `N8N_PROTOCOL` | `https` | no |
| `N8N_PORT` | `5678` | no |
| `WEBHOOK_URL` | `https://n8n.satmur.com/` | no |
| `N8N_PROXY_HOPS` | `1` | no |
| `GENERIC_TIMEZONE` | `UTC` | no |
| `TZ` | `UTC` | no |
| `N8N_LOG_LEVEL` | `info` | no |
| `N8N_DIAGNOSTICS_ENABLED` | `false` | no |
| `N8N_VERSION_NOTIFICATIONS_ENABLED` | `false` | no |
| `N8N_HIRING_BANNER_ENABLED` | `false` | no |
| `EXECUTIONS_DATA_PRUNE` | `true` | no |
| `EXECUTIONS_DATA_MAX_AGE` | `168` | no |

Notes:
- `DB_SQLITE_POOL_SIZE` > 0 enables WAL mode (concurrent reads during writes).
- `N8N_PROXY_HOPS=1` tells n8n it sits behind Traefik; without it n8n logs `X-Forwarded-For` validation errors and rate limiting misbehaves.
- Execution pruning (7 days) keeps the SQLite file from growing unbounded.

- [ ] **Step 7 (manual):** **Resource Limits** tab: Memory limit `768m`.

- [ ] **Step 8 (manual):** Click **Deploy**. Watch the deploy log. First deploy includes:
  - Pull n8n image (~200MB)
  - n8n creates `/home/node/.n8n/database.sqlite` and runs migrations
  - Traefik requests the Let's Encrypt cert via DNS-01 in the background (~30s; possibly longer on first run)

Expected final log lines: `Editor is now accessible via: https://n8n.satmur.com/`.

If TLS cert fails (Cloudflare returns 526 for more than a few minutes):
- Check **Servers → n8n → Proxy → Logs** for `acme` / `cloudflare` errors
- Check the Traefik config has `CF_DNS_API_TOKEN` and the `dnschallenge` flags (Task 7.5)
- Check Cloudflare token has `Zone:DNS:Edit` scope
- Check `dig _acme-challenge.n8n.satmur.com TXT` from your laptop — Traefik briefly creates this TXT record during cert issuance

- [ ] **Step 9: Verify the database is on the volume**

```bash
ssh -t n8n 'sudo sh -c "ls -la /var/lib/docker/volumes/*n8n-data*/_data/"'
```

Expected: `database.sqlite` (plus `-wal` / `-shm` files while running) and `config`.

### Task 8.3: Initial n8n setup

- [ ] **Step 1 (manual):** Open https://n8n.satmur.com in your browser.

Expected: n8n owner setup wizard. Cert lock icon should be valid (no warning).

- [ ] **Step 2 (manual):** Create the owner account:
  - Email: your email
  - First/last name: your choice
  - Password: strong, save in password manager under `n8n satmur.com — owner login`
  - Click **Next**, **Skip survey**

- [ ] **Step 3 (manual):** Verify n8n is healthy by creating a trivial workflow:
  1. Click **+ New Workflow**
  2. Add a **Manual Trigger** node
  3. Add a **Set** node, set field `hello` to `world`
  4. Click **Execute Workflow** at the bottom
  5. Output should show `{ "hello": "world" }`

### Task 8.4: Backup the encryption key (CRITICAL)

- [ ] **Step 1 (manual):** Open Coolify → n8n service → **Environment Variables** → reveal `N8N_ENCRYPTION_KEY`.

- [ ] **Step 2 (manual):** Confirm it matches what's in your password manager from Task 8.2 Step 2. If not, update the password manager NOW.

- [ ] **Step 3 (manual):** Add a calendar reminder: **Test n8n encryption key restore — 30 days**. The drill: restore the SQLite database from restic, start a fresh n8n container with this key, verify a stored credential decrypts. (We'll do this for real in Phase 12.)

### Task 8.5: Webhook end-to-end test

- [ ] **Step 1 (manual):** In n8n: create a new workflow.

- [ ] **Step 2 (manual):** Add a **Webhook** trigger node:
  - HTTP Method: `POST`
  - Path: `test`
  - Click "Listen for test event" (or save and toggle Active)

- [ ] **Step 3 (manual):** Copy the **Production URL** from the node — it should be `https://n8n.satmur.com/webhook/test`.

- [ ] **Step 4 (manual):** From your laptop:

```bash
curl -X POST https://n8n.satmur.com/webhook/test -H "Content-Type: application/json" -d '{"ping":"pong"}'
```

Expected: HTTP 200, JSON response (n8n's default webhook output). The execution should appear in n8n's "Executions" tab with the payload.

If you get HTTP 521/522 errors: Cloudflare can't reach origin. Check `coolify-proxy` is running and the `CLOUDFLARE-DOCKER` chain allows current Cloudflare ranges.

If you get HTTP 526: Cloudflare (Full strict) rejects the origin cert. Check the Let's Encrypt cert was issued (proxy logs; may take a few minutes after first deploy).

---

## Phase 9 — Backups

**Goal:** n8n's volume — including a consistent snapshot of the SQLite database — backed up daily via restic to R2.

**Why a snapshot step:** copying `database.sqlite` while n8n writes to it can capture a torn, unrestorable file. The backup script first takes an online copy with `sqlite3 .backup` (safe while n8n is running), checks it with `PRAGMA integrity_check`, and backs up that copy instead of the live file.

### Task 9.1: restic for n8n volume → systemd timer

- [ ] **Step 1:** Create `pyinfra/files/restic-env`:

```
# Managed by pyinfra. /etc/restic/r2-credentials, mode 0600 root only.
# Used by /usr/local/sbin/restic-n8n-backup.sh

RESTIC_REPOSITORY=s3:https://<r2-account-id>.r2.cloudflarestorage.com/satmur-backups/n8n-volume
RESTIC_PASSWORD=<generated-32char-password>
AWS_ACCESS_KEY_ID=<r2-access-key-id>
AWS_SECRET_ACCESS_KEY=<r2-secret-access-key>
```

**Generate the restic repository password** (different from R2 keys; encrypts your backup contents):

```bash
openssl rand -base64 32 | tr -d /=+ | cut -c1-32
```

Save this in your password manager under `restic — n8n-volume backup encryption`. Then fill in the `restic-env` file with all four values. **This file is NOT committed** (`.gitignore` excludes `secrets/`, but let's add an explicit rule):

```bash
echo "pyinfra/files/restic-env" >> .gitignore
```

- [ ] **Step 2:** Create `pyinfra/files/restic-n8n-backup.sh`:

```bash
#!/usr/bin/env bash
# Back up n8n's persistent volume to R2 via restic.
# The live SQLite database is excluded; a consistent online copy made with
# sqlite3 .backup is backed up in its place.
# Run by restic-n8n-backup.service (daily timer).

set -euo pipefail

# Source and export credentials (RESTIC_REPOSITORY, RESTIC_PASSWORD, AWS_*)
set -a
# shellcheck source=/dev/null
source /etc/restic/r2-credentials
set +a

LOG_TAG="restic-n8n-backup"
STAGE_DIR="/var/backups/n8n"

fail() { logger -t "$LOG_TAG" "ERROR: $*"; exit 1; }

logger -t "$LOG_TAG" "starting backup"

# Coolify-managed volumes live under /var/lib/docker/volumes/<name>/_data;
# Coolify prefixes the name from Task 8.2 Step 5 with the resource UUID.
mapfile -t VOLS < <(docker volume ls --quiet --filter "name=n8n-data")
[[ ${#VOLS[@]} -eq 1 ]] || fail "expected 1 Docker volume matching 'n8n-data', found ${#VOLS[@]}"
MOUNT_PATH="/var/lib/docker/volumes/${VOLS[0]}/_data"
DB="$MOUNT_PATH/database.sqlite"
[[ -f "$DB" ]] || fail "$DB not found"

# Consistent online snapshot of the database (safe while n8n is writing).
install -d -m 700 "$STAGE_DIR"
rm -f "$STAGE_DIR/database.sqlite"
sqlite3 "$DB" ".backup '$STAGE_DIR/database.sqlite'"
CHECK=$(sqlite3 "$STAGE_DIR/database.sqlite" "PRAGMA integrity_check;")
[[ "$CHECK" == "ok" ]] || fail "integrity_check on snapshot failed: $CHECK"

# Initialize repo if not yet done (idempotent).
restic snapshots >/dev/null 2>&1 || restic init

# Back up the volume minus the live DB files, plus the snapshot.
restic backup "$MOUNT_PATH" "$STAGE_DIR/database.sqlite" \
    --exclude "$MOUNT_PATH/database.sqlite" \
    --exclude "$MOUNT_PATH/database.sqlite-wal" \
    --exclude "$MOUNT_PATH/database.sqlite-shm" \
    --tag "n8n-volume" --host satmur

# Apply retention: 14 daily, 4 weekly, 6 monthly.
restic forget --tag "n8n-volume" --keep-daily 14 --keep-weekly 4 --keep-monthly 6 --prune

logger -t "$LOG_TAG" "backup complete"
```

- [ ] **Step 3:** Create `pyinfra/files/restic-n8n-backup.service`:

```
[Unit]
Description=Daily restic backup of n8n volume (incl. SQLite snapshot) to R2
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/restic-n8n-backup.sh
```

- [ ] **Step 4:** Create `pyinfra/files/restic-n8n-backup.timer`:

```
[Unit]
Description=Daily restic backup of n8n volume

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
```

- [ ] **Step 5:** Create `pyinfra/tasks/backups.py`:

```python
"""restic + R2 daily backups of the n8n Docker volume (SQLite snapshot included)."""

from pyinfra.operations import apt, files, server, systemd

apt.packages(
    name="Install restic + sqlite3",
    packages=["restic", "sqlite3"],
    update=False,
)

files.directory(
    name="Ensure /etc/restic exists",
    path="/etc/restic",
    user="root",
    group="root",
    mode="700",
)

files.put(
    name="Install restic R2 credentials",
    src="pyinfra/files/restic-env",
    dest="/etc/restic/r2-credentials",
    user="root",
    group="root",
    mode="600",
)

files.put(
    name="Install restic-n8n-backup.sh",
    src="pyinfra/files/restic-n8n-backup.sh",
    dest="/usr/local/sbin/restic-n8n-backup.sh",
    user="root",
    group="root",
    mode="755",
)

files.put(
    name="Install restic-n8n-backup.service",
    src="pyinfra/files/restic-n8n-backup.service",
    dest="/etc/systemd/system/restic-n8n-backup.service",
    user="root",
    group="root",
    mode="644",
)

files.put(
    name="Install restic-n8n-backup.timer",
    src="pyinfra/files/restic-n8n-backup.timer",
    dest="/etc/systemd/system/restic-n8n-backup.timer",
    user="root",
    group="root",
    mode="644",
)

systemd.daemon_reload(name="systemctl daemon-reload")

systemd.service(
    name="Enable + start restic-n8n-backup.timer",
    service="restic-n8n-backup.timer",
    enabled=True,
    running=True,
)
```

- [ ] **Step 6: Apply**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/backups.py
```

- [ ] **Step 7: Trigger first backup manually to verify**

```bash
ssh -t n8n "sudo systemctl start restic-n8n-backup.service && sudo journalctl -t restic-n8n-backup -u restic-n8n-backup.service --no-pager -n 20"
```

Expected: log shows "starting backup", restic init/snapshot output, "backup complete". No `integrity_check` error.

- [ ] **Step 8: Verify in R2**

```bash
ssh -t n8n "sudo bash -c 'set -a && source /etc/restic/r2-credentials && set +a && restic snapshots && restic ls latest | grep database.sqlite'"
```

Expected: at least one snapshot, containing `/var/backups/n8n/database.sqlite` and **no** `/var/lib/docker/volumes/.../database.sqlite`.

### Task 9.2: Commit Phase 9

- [ ] **Step 1:**

```bash
cd ~/workspace/vpsconfig
git add pyinfra/ .gitignore
git commit -m "feat(backups): daily restic snapshots of n8n volume + SQLite DB to R2"
```

(The `restic-env` file is NOT staged — it's gitignored.)

---

## Phase 10 — Monitoring (BetterStack)

**Goal:** External uptime monitoring for `https://n8n.satmur.com`, with alerts to email.

### Task 10.1: BetterStack signup + monitor

- [ ] **Step 1 (manual):** Sign up at https://betterstack.com/uptime (free tier).

- [ ] **Step 2 (manual):** Create monitor:
  - **+ Create monitor**
  - URL: `https://n8n.satmur.com`
  - Check frequency: 3 minutes
  - Request type: **HEAD** (lighter than GET)
  - Expected status: 200, 401, 403, or 404 (n8n root may redirect)
  - Regions: All free regions
  - Notifications: your email
  - Optionally: add a Discord webhook

- [ ] **Step 3 (manual):** Trigger a test alert: pause Traefik temporarily, wait 6 minutes, expect email. Then resume.

```bash
# Pause
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo docker stop coolify-proxy"
# (wait for alert email, ~6 min)
# Resume
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo docker start coolify-proxy"
```

- [ ] **Step 4 (manual):** Confirm BetterStack reports "Recovered" within ~6 min.

---

## Phase 11 — Documentation

**Goal:** `README.md` and `RUNBOOK.md` exist so future-you can operate this without re-reading the spec.

### Task 11.1: README.md

- [ ] **Step 1:** Create `README.md`:

```markdown
# vpsconfig

Configuration as code for `satmur.com` — a single-VPS deployment of [n8n](https://n8n.io) managed via [Coolify Cloud](https://coolify.io), with hardening via [Pyinfra](https://pyinfra.com) and Cloudflare DNS via [Pulumi](https://pulumi.com).

## Architecture

See [docs/superpowers/specs/2026-04-15-vps-hardening-coolify-design.md](docs/superpowers/specs/2026-04-15-vps-hardening-coolify-design.md).

## Prerequisites

- macOS or Linux laptop
- `brew install uv pulumi restic`
- SSH key pair at `~/.ssh/id_ed25519_vps`
- Pulumi Cloud account (free tier)
- Cloudflare account with `satmur.com` zone
- Cloudflare R2 bucket `satmur-backups` + access token
- Coolify Cloud account

## Layout

- `pyinfra/` — VPS configuration (Pyinfra)
- `pulumi/` — Cloudflare DNS + zone settings (Pulumi)
- `docs/` — design and plan documents
- `RUNBOOK.md` — day-to-day operational commands

## Quick commands

```bash
# Set up local Python environment
uv sync

# Apply VPS config
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/<task>.py

# Apply all VPS tasks
uv run pyinfra pyinfra/inventory.py pyinfra/deploy.py

# Apply Cloudflare changes
cd pulumi && uv run pulumi up

# SSH to VPS
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149
```

## Setup from scratch

To rebuild this on a new VPS, follow [docs/superpowers/plans/2026-04-15-vps-hardening-coolify.md](docs/superpowers/plans/2026-04-15-vps-hardening-coolify.md) end-to-end.

## License

(Personal — no license intended.)
```

- [ ] **Step 2:** Commit

```bash
git add README.md
git commit -m "docs: add README"
```

### Task 11.2: RUNBOOK.md

- [ ] **Step 1:** Create `RUNBOOK.md`:

```markdown
# RUNBOOK — satmur (n8n on Coolify Cloud)

Day-to-day operational commands and recovery procedures.

## Connection details

- VPS IP: `198.144.178.149`
- SSH user: `maddalab` (key: `~/.ssh/id_ed25519_vps`)
- Service URL: https://n8n.satmur.com
- Coolify Cloud: https://app.coolify.io

## Common operations

### SSH in

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149
```

### View n8n logs

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo docker logs -f --tail 100 n8n"
```

(Container name may vary; use `sudo docker ps` to find it.)

### Apply infra changes

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/deploy.py    # all VPS tasks
uv run pulumi -C pulumi up                                # Cloudflare
```

### Disk usage

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "df -h && sudo docker system df"
```

### Force Cloudflare IP refresh

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo systemctl start cloudflare-ufw-update.service"
```

### Trigger restic backup manually

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo systemctl start restic-n8n-backup.service"
```

### List restic snapshots

```bash
ssh -i ~/.ssh/id_ed25519_vps maddalab@198.144.178.149 "sudo bash -c 'set -a && source /etc/restic/r2-credentials && set +a && restic snapshots'"
```

## n8n upgrade procedure

1. Read changelog: https://docs.n8n.io/release-notes/
2. Take a fresh backup: `ssh -t n8n "sudo systemctl start restic-n8n-backup.service"` and confirm "backup complete" in the journal.
3. In Coolify → n8n service → change Image tag (e.g., `1.79.0` → `1.84.0`) → **Redeploy**.
4. Watch deploy logs for migration errors.
5. Smoke test: log in, run a known-good workflow.
6. If broken: revert image tag → redeploy. If a schema migration ran, restore the SQLite database from the step 2 snapshot (see "n8n database corrupted").

## Recovery procedures

### Lost SSH key on laptop

1. Use Virtualizor VNC console (in CheapWindowsVPS panel).
2. Log in as `maddalab` with sudo password (from password manager).
3. `sudo nano /home/maddalab/.ssh/authorized_keys` — add new pubkey.
4. Test from laptop: `ssh -i ~/.ssh/<new-key> maddalab@198.144.178.149`.

### Locked out by fail2ban

- Wait 1 hour, OR
- Use VNC console: `sudo fail2ban-client unban <your-ip>`.

### n8n database corrupted (or bad migration)

1. Coolify → `n8n` → **Stop**.
2. Restore the SQLite snapshot to /tmp: `sudo bash -c 'set -a && source /etc/restic/r2-credentials && set +a && restic restore latest --target /tmp/n8n-restore --include /var/backups/n8n/database.sqlite'` (use a snapshot ID instead of `latest` to go further back).
3. Put it in place (the n8n container runs as uid 1000):
   ```bash
   VOL=$(sudo sh -c 'echo /var/lib/docker/volumes/*n8n-data*/_data')
   sudo cp /tmp/n8n-restore/var/backups/n8n/database.sqlite "$VOL/database.sqlite"
   sudo rm -f "$VOL/database.sqlite-wal" "$VOL/database.sqlite-shm"
   sudo chown 1000:1000 "$VOL/database.sqlite"
   sudo rm -rf /tmp/n8n-restore
   ```
4. Coolify → `n8n` → **Start**.
5. Verify n8n still loads workflows and a stored credential decrypts.

### VPS dies entirely

1. Provision new VPS (preferably Ubuntu 24.04).
2. `git clone <this repo>` on laptop.
3. `ssh-copy-id -i ~/.ssh/id_ed25519_vps.pub root@<new-ip>` (one-time).
4. Edit `pyinfra/inventory_bootstrap.py` and `pyinfra/inventory.py` to point at new IP.
5. Run Phases 3, 4, 5, 6 of the plan in order.
6. Update Pulumi VPS IPs: `cd pulumi && uv run pulumi config set satmur:vpsIPv4 <new-ip>`. `pulumi up`.
7. In Coolify: delete old server, register new server (same SSH user, paste pubkey via `pyinfra/tasks/coolify_authorize.py`).
8. Re-deploy n8n in Coolify (Phase 8 Task 8.2; encryption key from password manager), then **Stop** it.
9. Run Phase 9 (backups task) so restic + credentials are on the new host.
10. Restore the latest restic snapshot: copy the volume contents back into the new `*n8n-data*` volume, and put `/var/backups/n8n/database.sqlite` back as `database.sqlite` (see "n8n database corrupted" for the commands).
11. Start n8n. Smoke test webhook end-to-end.

### Suspected compromise

DO NOT migrate data from old VPS without inspection. Reprovision fresh, rotate every secret (n8n encryption key, restic repository password, all Cloudflare API tokens, R2 access token).

## Quarterly drills

- **Backup restore drill** (every 3 months): restore latest restic snapshot to /tmp on the VPS → `PRAGMA integrity_check` on the SQLite snapshot → verify workflow/credential counts match prod (Phase 12 Task 12.2).
- **Cloudflare IP review** (every 6 months): re-check provider firewall in Virtualizor against current `https://www.cloudflare.com/ips-v4` and `ips-v6`.
- **Token rotation** (annually, calendar reminders set): rotate both Cloudflare API tokens and R2 access token.
```

- [ ] **Step 2:** Commit

```bash
git add RUNBOOK.md
git commit -m "docs: add operational runbook"
```

### Task 11.3: Add an aggregate `deploy.py` for "all tasks" runs

- [ ] **Step 1:** Create `pyinfra/deploy.py`:

```python
"""Apply all post-bootstrap tasks in order. Run on every change.

Usage:
    uv run pyinfra pyinfra/inventory.py pyinfra/deploy.py
"""

# Import each task module — pyinfra picks up operations from imports.
from pyinfra.api import deploy

# Note: pyinfra collects operations by execution context, so we just
# `import` each tasks file. Each file uses operations at module top-level.

# Order matters: system before firewall (need swap before docker), etc.
import pyinfra.tasks.system  # noqa: F401
import pyinfra.tasks.firewall  # noqa: F401
import pyinfra.tasks.fail2ban  # noqa: F401
import pyinfra.tasks.unattended_upgrades  # noqa: F401
import pyinfra.tasks.docker  # noqa: F401
import pyinfra.tasks.backups  # noqa: F401
import pyinfra.tasks.coolify_authorize  # noqa: F401
import pyinfra.tasks.ssh  # noqa: F401  # ssh hardening — keeps auth config in sync
```

> **Note:** Pyinfra's mechanism for splitting operations across files is via the `local.include()` helper, not Python imports. Verify by running `uv run pyinfra pyinfra/inventory.py pyinfra/deploy.py --dry`. If operations don't appear, switch to `local.include` style. Pyinfra docs: https://docs.pyinfra.com/en/3.x/api/operations.html

If imports don't work, replace with this content using `local.include`:

```python
"""Apply all post-bootstrap tasks in order."""

from pyinfra import local

local.include("pyinfra/tasks/system.py")
local.include("pyinfra/tasks/firewall.py")
local.include("pyinfra/tasks/fail2ban.py")
local.include("pyinfra/tasks/unattended_upgrades.py")
local.include("pyinfra/tasks/docker.py")
local.include("pyinfra/tasks/coolify_authorize.py")
local.include("pyinfra/tasks/backups.py")
local.include("pyinfra/tasks/ssh.py")
```

- [ ] **Step 2: Verify aggregate deploy is a no-op (everything already applied)**

```bash
cd ~/workspace/vpsconfig
uv run pyinfra pyinfra/inventory.py pyinfra/deploy.py --dry
```

Expected: many operations listed, nearly all "No change" / unchanged. If anything shows pending, run without `--dry` to apply.

- [ ] **Step 3: Commit**

```bash
git add pyinfra/deploy.py
git commit -m "feat(pyinfra): aggregate deploy.py to apply all tasks idempotently"
```

---

## Phase 12 — Verification & restore drill

**Goal:** Prove the system is production-ready by exercising the recovery scenarios.

### Task 12.1: End-to-end smoke test

- [ ] **Step 1: Send a webhook payload, check execution**

```bash
curl -X POST https://n8n.satmur.com/webhook/test -H "Content-Type: application/json" -d '{"smoke":"test","time":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}'
```

In n8n UI → Executions, see a new entry with the payload.

### Task 12.2: Backup restore drill (n8n volume + SQLite via restic)

- [ ] **Step 1: On VPS, list snapshots**

```bash
ssh -t n8n "sudo bash -c 'set -a && source /etc/restic/r2-credentials && set +a && restic snapshots'"
```

- [ ] **Step 2: Restore latest snapshot to /tmp on the VPS (won't touch live data)**

```bash
ssh -t n8n "sudo bash -c 'set -a && source /etc/restic/r2-credentials && set +a && restic restore latest --target /tmp/n8n-restore-test'"
```

- [ ] **Step 3: Verify files and database integrity**

```bash
ssh -t n8n 'sudo sh -c "ls -la /tmp/n8n-restore-test/var/lib/docker/volumes/*/_data/ && sqlite3 /tmp/n8n-restore-test/var/backups/n8n/database.sqlite \"PRAGMA integrity_check;\""'
```

Expected: contents of `/home/node/.n8n/` (config, custom nodes if any — but no live `database.sqlite`), and `ok` from the integrity check.

- [ ] **Step 4: Compare row counts with production**

```bash
Q="SELECT count(*) FROM workflow_entity; SELECT count(*) FROM credentials_entity;"
ssh -t n8n "sudo sqlite3 /tmp/n8n-restore-test/var/backups/n8n/database.sqlite '$Q'; echo ---; sudo sh -c \"sqlite3 -readonly /var/lib/docker/volumes/*n8n-data*/_data/database.sqlite '$Q'\""
```

Expected: two numbers (workflows, credentials) above `---` matching the two below (or differ only by changes made since the snapshot).

- [ ] **Step 5: Cleanup**

```bash
ssh -t n8n "sudo rm -rf /tmp/n8n-restore-test"
```

- [ ] **Step 6: Add calendar reminder: "Quarterly restore drill — next: <date+90>"**

### Task 12.3: Final checklist

- [ ] All sections of the spec have a corresponding implementation
- [ ] All Cloudflare resources show in `pulumi stack`
- [ ] `ufw status` shows Cloudflare-IP-scoped rules + SSH
- [ ] Provider firewall configured in Virtualizor
- [ ] `fail2ban-client status sshd` shows enabled
- [ ] `systemctl list-timers` shows: `cloudflare-ufw-update.timer`, `docker-prune.timer`, `restic-n8n-backup.timer`, `apt-daily.timer`, `apt-daily-upgrade.timer`
- [ ] n8n reachable at `https://n8n.satmur.com` with valid TLS
- [ ] Webhook test returns 200
- [ ] restic snapshot (incl. `/var/backups/n8n/database.sqlite`) exists in R2
- [ ] BetterStack monitor green
- [ ] Encryption key in password manager
- [ ] Sudo password for `maddalab` in password manager
- [ ] All Cloudflare/R2 API tokens in password manager
- [ ] All commits pushed to remote (if you've added one)

### Task 12.4: Final commit + tag

- [ ] **Step 1: Tag the release**

```bash
cd ~/workspace/vpsconfig
git tag -a v1.0.0 -m "Initial production deployment of n8n on satmur.com"
```

(Push to remote if you have one set up: `git push --tags`.)

---

## Self-review notes (writer's checklist after writing)

- [x] Each spec section maps to a phase/task
- [x] All file paths are absolute or repo-relative
- [x] Bootstrap order discipline preserved (Phase 3 has insurance terminals + sanity checks)
- [x] No `TBD` / `TODO` / `implement later` placeholders in execution steps
- [x] Manual steps are explicitly marked
- [x] Verification commands appear after every change
- [x] Recovery procedures documented in RUNBOOK.md
- [x] Secrets never committed (gitignore + Pulumi Cloud KMS + password manager)
- [x] Idempotent re-runs of pyinfra are explicitly verified (Task 11.3)

## Caveats and known fragilities

- **Pyinfra `local.include` vs imports**: Task 11.3 hedges between two patterns. Verify with `--dry` and pick the one that works in your pyinfra version.
- **Cloudflare IP refresh script** assumes `ufw status numbered` parses cleanly. If Cloudflare adds a CIDR with weird formatting, the regex may miss it. Worst case: stale ranges. Best case: weekly refresh catches it.
- **Coolify Cloud UI fields can drift between versions.** If Task 8.2 fields don't match, find the equivalent — env vars and the persistent volume are the load-bearing parts.
- **Pulumi Cloudflare provider 5.x → 6.x** may rename arguments. If you upgrade, run `pulumi preview` carefully.
- **n8n version pinning**: `1.74.1` in the spec is a placeholder — Task 8.2 Step 1 instructs you to look up the latest stable at deploy time.
