# VPS Hardening + n8n on Coolify Cloud — Design

**Date:** 2026-04-15
**Status:** Approved (pending user final review of this document)
**Owner:** Bhaskar Maddala
**Repo:** `~/workspace/vpsconfig`

## Goal

Take a fresh Ubuntu 24.04 LTS VPS — currently exposed to the public internet with root SSH password authentication — and turn it into a hardened host running n8n managed by Coolify Cloud, with all configuration captured as code so the entire setup is reproducible.

## Non-goals

- High availability / multi-VPS redundancy
- Compliance with formal frameworks (SOC2, HIPAA, PCI)
- Self-hosting Coolify (using their cloud control plane instead)
- Running services beyond n8n at this stage (the design accommodates adding more later)
- Production-grade observability (no Prometheus/Grafana/Loki at this scale)

## Inputs (current state)

| | |
|---|---|
| **VPS provider** | CheapWindowsVPS (Virtualizor panel, Chicago `chi5` node) |
| **OS** | Ubuntu 24.04 LTS (kernel 6.8) |
| **Specs** | 3 GB RAM, 1 vCPU, 30 GB disk, no swap |
| **Network** | Dual-stack: IPv4 `198.144.178.149`, IPv6 `2606:c680:2000:2e::beeb:154d` |
| **Provider firewall** | Available via Virtualizor "Firewall" tab (manual config, no API) |
| **Current SSH** | `root` with password authentication |
| **Domain** | `satmur.com` (registered via Cloudflare Registrar) |
| **DNS strategy** | Cloudflare proxied (orange cloud) |
| **Hardening tier** | A — sensible baseline |

## Tooling decisions

| Layer | Tool | Why |
|---|---|---|
| OS configuration | **Pyinfra** | Python-based, agentless (SSH only), idempotent, faster than Ansible |
| Cloudflare resources | **Pulumi** (Python SDK) with **Pulumi Cloud free tier** for state | Declarative, version controlled, encrypted secrets via Pulumi-managed KMS, no state file in repo |
| Python project management | **uv** | Project-local `.venv/`, lockfile-driven, no system Python dependency |
| App orchestration | **Coolify Cloud** (managed control plane) | User-managed VPS, vendor-managed UI/orchestration |

**Local laptop prerequisites:** `brew install uv pulumi`. Nothing else (uv installs its own Python).

## Architecture

```
                                  ┌──────────────────────────────────┐
                                  │   YOU (laptop)                   │
                                  │   - SSH key: id_ed25519_vps      │
                                  │   - Browser: n8n.satmur.com      │
                                  └────────────┬─────────────────────┘
                                               │ HTTPS
                                               ▼
                              ┌────────────────────────────────────┐
                              │   CLOUDFLARE                       │
                              │   - DNS (proxied: orange cloud)    │
                              │   - WAF, DDoS, TLS termination     │
                              │   - Hides VPS IP from internet     │
                              └─────┬──────────────────────────┬───┘
                  HTTPS to origin   │                          │ Cloudflare API
                  (Full strict)     │                          │ (DNS-01 cert renewal)
                                    ▼                          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       VPS  satmur  (198.144.178.149)                   │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Provider firewall (Virtualizor — manual)                       │    │
│  │   allow: 22 (SSH) from anywhere                                │    │
│  │   allow: 80, 443 from Cloudflare IPv4+IPv6 ranges only         │    │
│  │   deny:  everything else                                       │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ ufw (host firewall — same rules, defense in depth)             │    │
│  │   Cloudflare IP ranges refreshed weekly via systemd timer      │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ SSH (sshd, port 22) + fail2ban                                 │    │
│  │   - root login: disabled                                       │    │
│  │   - password auth: disabled                                    │    │
│  │   - keys only, AllowUsers maddalab coolify                     │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Docker daemon (log rotation + weekly prune)                    │    │
│  │   ┌────────────┐  ┌────────────┐  ┌──────────────────┐         │    │
│  │   │  Traefik   │  │  Sentinel  │  │  n8n 2.x         │         │    │
│  │   │  (Coolify) │  │  (Coolify) │  │  SQLite (volume) │         │    │
│  │   └─────┬──────┘  └────────────┘  └─────────┬────────┘         │    │
│  │         └── proxies → coolify-network ──────┘                  │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  Users: root (locked from SSH), maddalab (admin), coolify (CC agent)   │
│  Swap: 2GB swapfile                                                    │
└────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ SSH (port 22), user: coolify
                                    │ key: Coolify Cloud's keypair
                                    │
                       ┌───────────────────────────┐
                       │   COOLIFY CLOUD           │
                       │   (control plane only —   │
                       │    UI, orchestration)     │
                       └───────────────────────────┘
```

## Component Specifications

### 1. Hostname, timezone, locale

- **Hostname:** `satmur` (from current `vps149257-lr5`)
- **Timezone:** `UTC`
- **Locale:** `en_US.UTF-8`

### 2. Swap file

- **Size:** 2 GB at `/swapfile`, mode `0600`
- **Persistence:** `/etc/fstab` entry
- **Tuning:**
  - `vm.swappiness=10`
  - `vm.vfs_cache_pressure=50`
- **Purpose:** safety net for Docker pull/build memory spikes; not for sustained workload

### 3. Users

| User | Auth | Sudo | SSH allowed | Purpose |
|---|---|---|---|---|
| `root` | n/a | self | no | OS owner, unreachable via SSH |
| `maddalab` | SSH key (your laptop's `id_ed25519_vps`) | password-required | yes | Daily admin login |
| `coolify` | SSH key (Coolify Cloud's pubkey) | NOPASSWD ALL | yes | Coolify Cloud agent connection |

**Bootstrap order** (must be followed exactly to avoid lockout):
1. Connect as `root` (current state)
2. Create `maddalab` user with sudo + add laptop's public key
3. **Manual sanity check** in second terminal: SSH as `maddalab`, run `sudo -i`. If broken, fix from root before continuing.
4. Create `coolify` user + add Coolify Cloud's public key + NOPASSWD sudoers entry
5. Apply SSH hardening config (Section 4) and restart sshd
6. **Manual sanity check** in third terminal: SSH as `maddalab` still works.
7. Only then exit the original root session.

### 4. SSH hardening

Configuration file: `/etc/ssh/sshd_config.d/99-hardening.conf`

```
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

Port stays at 22. Custom ports add log-noise reduction but no real security.

### 5. fail2ban

- Single jail: `sshd`
- Backend: `systemd` (reads journald)
- Trigger: 5 failed auths within 10 minutes
- Action: 1 hour ban
- Whitelist: `127.0.0.1/8 ::1` only (no pre-trusted IPs)

### 6. Network firewalls — two layers

**Provider firewall (Virtualizor — manual):**

| Direction | Port | Protocol | Source | Action |
|---|---|---|---|---|
| In | 22 | TCP | Anywhere | Allow |
| In | 80 | TCP | Cloudflare IPv4+IPv6 ranges | Allow |
| In | 443 | TCP | Cloudflare IPv4+IPv6 ranges | Allow |
| In | (all other) | * | * | Deny |
| Out | * | * | * | Allow |

Configured manually in CheapWindowsVPS panel. Maintenance: re-check Cloudflare IP list every ~6 months (Cloudflare changes the published ranges rarely).

**Host firewall (ufw — automated):**

- Same allow rules as provider firewall
- `default deny incoming`, `default allow outgoing`, `default deny routed`
- `IPV6=yes`
- Cloudflare IP ranges fetched from `https://www.cloudflare.com/ips-v4` and `https://www.cloudflare.com/ips-v6`
- **Refresh mechanism:** `cloudflare-ufw-update.timer` (systemd) runs weekly. On fetch failure, logs error and **leaves existing rules in place** — never opens up access on failure.

### 7. Unattended-upgrades

- Apply security updates only, automatically
- Auto-reboot at **04:00 UTC** only when a kernel update demands it
- No email — log to syslog/journald

### 8. Docker daemon configuration

`/etc/docker/daemon.json`:

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

`live-restore` keeps containers running across daemon restarts.

### 9. Disk hygiene

Weekly `docker-prune.timer` (systemd) runs:

```
docker system prune -af --filter "until=168h"
docker volume prune -f
```

(Removes stopped containers, unused images, and build cache older than 7 days, plus unused anonymous volumes. Docker rejects `until` combined with `--volumes`, hence two commands. Named volumes such as `n8n-data` are never pruned.)

### 10. AppArmor

Verify enabled, in `enforce` mode (Ubuntu 24.04 default). No custom profiles at tier A.

### 11. Coolify Cloud server registration

Manual one-time steps (no automation):

1. In Coolify Cloud → **Servers** → **New Server**
2. Name: `satmur`, Host: `198.144.178.149`, Port: `22`, User: `coolify`
3. Coolify shows a public SSH key — paste it into `coolify` user's `~/.ssh/authorized_keys` (Pyinfra task accepts this key as input)
4. Coolify validates connection, runs install script (detects existing Docker, skips install)
5. Pulls Sentinel container (metrics) and Traefik (reverse proxy) onto VPS

### 12. Coolify project structure

```
Coolify Cloud
└── Project: "automation"
    └── Environment: "production"
        └── Service: n8n            (n8nio/n8n:<pinned 2.x tag>, SQLite)
```

### 13. Database: SQLite

- n8n's built-in default — no separate database service, password, or RAM budget
- File: `database.sqlite` inside n8n's volume (`/home/node/.n8n`), WAL mode via `DB_SQLITE_POOL_SIZE`
- Fits a single-user, single-instance deployment; rules out n8n queue mode / horizontal scaling
- Backups take an online `sqlite3 .backup` snapshot rather than copying the live file (see Backups)

### 14. n8n service

- Image: `n8nio/n8n:<2.x tag>` (pinned; **verify latest stable at implementation time**; upgrade procedure documented in `RUNBOOK.md` and the Updates section below)
- Volume: Coolify-managed Docker volume at `/home/node/.n8n`
- Routing: Traefik label `n8n.satmur.com` → port 5678
- RAM ceiling: ~768 MB

**Environment variables:**

| Variable | Value |
|---|---|
| `DB_TYPE` | `sqlite` |
| `DB_SQLITE_POOL_SIZE` | `2` (enables WAL) |
| `N8N_HOST` | `n8n.satmur.com` |
| `N8N_PROTOCOL` | `https` |
| `N8N_PORT` | `5678` |
| `WEBHOOK_URL` | `https://n8n.satmur.com/` |
| `N8N_PROXY_HOPS` | `1` (behind Traefik) |
| `N8N_ENCRYPTION_KEY` | (Coolify secret, also backed up in password manager) |
| `GENERIC_TIMEZONE` | `UTC` |
| `TZ` | `UTC` |
| `N8N_LOG_LEVEL` | `info` |
| `N8N_DIAGNOSTICS_ENABLED` | `false` |
| `N8N_VERSION_NOTIFICATIONS_ENABLED` | `false` |
| `N8N_HIRING_BANNER_ENABLED` | `false` |
| `EXECUTIONS_DATA_PRUNE` | `true` |
| `EXECUTIONS_DATA_MAX_AGE` | `168` (hours = 7 days) |

### 15. TLS certificate flow

**DNS-01 challenge via Cloudflare API** (not HTTP-01).

1. Coolify's Traefik configured with Cloudflare DNS provider plugin + Cloudflare API token
2. Traefik creates `_acme-challenge.n8n.satmur.com` TXT record via API
3. Let's Encrypt verifies, issues cert
4. Traefik installs cert, removes TXT record
5. Auto-renews 30 days before expiry

### 16. Cloudflare API tokens

**Two separate tokens** (least privilege, independent revocation):

| Token | Scope | Stored in |
|---|---|---|
| `pulumi-satmur` | `Zone.Zone:Read`, `Zone.DNS:Edit`, `Zone.Zone Settings:Edit` on zone `satmur.com` | `pulumi config set --secret cloudflare:apiToken` |
| `coolify-cert-renewal` | `Zone.Zone:Read`, `Zone.DNS:Edit` on zone `satmur.com` | Coolify secret manager (consumed by Traefik) |

Both created manually in Cloudflare dashboard before first deploy. Calendar reminder set for annual rotation.

### 17. Cloudflare zone resources (Pulumi-managed)

```
cloudflare.Record                 "n8n_a"      A    n8n.satmur.com → 198.144.178.149              proxied=true
cloudflare.Record                 "n8n_aaaa"   AAAA n8n.satmur.com → 2606:c680:2000:2e::beeb:154d  proxied=true
cloudflare.ZoneSettingsOverride   "satmur"
    ssl                       = "strict"
    min_tls_version          = "1.2"
    always_use_https         = "on"
    automatic_https_rewrites = "on"
    opportunistic_encryption = "on"
    tls_1_3                  = "on"
```

`ssl="strict"` requires a real Let's Encrypt cert on origin (covered in Section 15). "Flexible" mode would be insecure.

### 18. First-deploy sequence

1. Manually create both Cloudflare API tokens (Section 16)
2. `uv run pulumi up` — creates DNS records + zone settings
3. Verify DNS: `dig n8n.satmur.com` returns Cloudflare anycast IPs
4. `uv run pyinfra inventory.py deploy.py` — full VPS hardening + Docker + coolify user
5. In Coolify Cloud UI: register server (Section 11), create project
6. Create n8n service with its `/home/node/.n8n` volume, paste env vars (Section 14), deploy
7. Traefik obtains cert via DNS-01 (~30 sec)
8. Open `https://n8n.satmur.com` → n8n setup wizard → create owner account
9. **Immediately copy `N8N_ENCRYPTION_KEY` from Coolify secret manager to your password manager** ("n8n satmur.com" entry)
10. Test webhook end-to-end with a trivial workflow

## Operations

### Backups

| What | How | Where | Frequency | Retention |
|---|---|---|---|---|
| `N8N_ENCRYPTION_KEY` | Manual copy at first deploy | Password manager (1Password / Bitwarden) | Once | Forever |
| n8n volume (`/home/node/.n8n`) incl. SQLite database | `restic` via systemd timer; the DB is captured as a consistent `sqlite3 .backup` snapshot (integrity-checked), the live DB files are excluded | Cloudflare R2 bucket `satmur-backups`, prefix `n8n-volume/` | Daily 03:00 UTC | 14 daily + 4 weekly + 6 monthly |

**Cloudflare R2 setup:**
- 1 bucket: `satmur-backups`
- 1 R2 access token, scoped read+write to that bucket only
- Token in `/etc/restic/r2-credentials` mode 0600 (root only)

**Quarterly restore drill:** restore latest restic snapshot to /tmp → `PRAGMA integrity_check` on the SQLite snapshot → verify workflow/credential counts match prod. Untested backups are not backups.

### Updates

| Component | Strategy |
|---|---|
| Ubuntu security patches | Auto via `unattended-upgrades` |
| Ubuntu major (24.04 → 26.04) | Manual every ~2 years; snapshot before. LTS support to 2029. |
| Docker engine | Auto via `unattended-upgrades` |
| Coolify control plane | Vendor-managed |
| Coolify-managed Sentinel/Traefik on VPS | Vendor-pushed via control plane |
| n8n | Manual, monthly review (procedure in `RUNBOOK.md`) |

### Monitoring

| Layer | Tool | Cost |
|---|---|---|
| External uptime | BetterStack free tier (10 monitors, 3-min interval, multi-region) → email + optional Discord webhook | Free |
| Resource metrics | Coolify Cloud dashboard (Sentinel agent) | Included |
| Cloudflare analytics | Cloudflare dashboard | Free |

Tier A explicitly excludes: Prometheus/Grafana/Loki, self-hosted log aggregation, APM/tracing.

### Recovery scenarios

| Scenario | Procedure | Time |
|---|---|---|
| Lost SSH key on laptop | Use Virtualizor VNC console → `sudo -i` from `maddalab` (whose password you have) → add new key | 10 min |
| Locked out by fail2ban | Wait 1 hour, or VNC console → `fail2ban-client unban <ip>` | 1–10 min |
| n8n database corrupted / bad migration | Stop n8n → restore SQLite snapshot from restic into the volume → start n8n | 30 min |
| Encryption key lost AND VPS lost | Workflows recoverable from the restic SQLite snapshot; stored credentials NOT recoverable, must re-enter all API keys/OAuth | hours |
| VPS dies entirely | Provision new VPS → `git clone vpsconfig` → `uv run pyinfra inventory.py deploy.py` → register in Coolify → deploy n8n → restore n8n volume + SQLite snapshot from restic → update Pulumi inventory IP → `pulumi up` | 1–2 hours |
| Suspected compromise | Reprovision new VPS, do NOT migrate old data without inspection. Rotate every secret. | 1 day |

### Day-to-day commands (`RUNBOOK.md`)

```bash
# SSH in
ssh maddalab@198.144.178.149

# View n8n logs
docker logs -f --tail 100 n8n

# Apply infra changes
cd ~/workspace/vpsconfig
uv run pyinfra inventory.py deploy.py    # VPS config
uv run pulumi up                          # Cloudflare resources

# Disk usage check
ssh maddalab@198.144.178.149 "df -h && docker system df"

# Force Cloudflare IP refresh
ssh maddalab@198.144.178.149 "sudo systemctl start cloudflare-ufw-update.service"

# n8n upgrade procedure (see RUNBOOK.md for full steps)
```

## Repository layout

```
vpsconfig/
├── pyproject.toml             # uv-managed Python project
├── uv.lock
├── .python-version
├── .gitignore                 # .venv/, __pycache__/, secrets
├── README.md
├── RUNBOOK.md                 # day-to-day operational commands
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-15-vps-hardening-coolify-design.md   (this file)
├── pyinfra/
│   ├── inventory.py           # VPS connection details
│   ├── deploy.py              # main deploy entrypoint
│   ├── tasks/
│   │   ├── system.py          # hostname, timezone, swap
│   │   ├── users.py           # maddalab, coolify users
│   │   ├── ssh.py             # sshd hardening
│   │   ├── firewall.py        # ufw + Cloudflare IP refresh
│   │   ├── fail2ban.py
│   │   ├── docker.py          # daemon config, log rotation, prune timer
│   │   └── unattended_upgrades.py
│   └── files/                 # templates, configs
└── pulumi/
    ├── Pulumi.yaml
    ├── Pulumi.prod.yaml       # stack config (encrypted secrets)
    ├── __main__.py            # Cloudflare resource definitions
    └── requirements.txt
```

## Known limitations / risks (honest catalog)

1. **Single VPS = single point of failure.** No HA. ~2-hour recovery to a new VPS via runbook.
2. **1 vCPU is the real constraint.** A single CPU-heavy workflow can starve everything else, including Traefik.
3. **30 GB disk fills.** Mitigations: 7-day n8n execution retention, weekly Docker prune, alert on disk usage.
4. **Coolify Cloud is a vendor dependency.** If they go down, VPS keeps running but management plane is gone. Migration to self-hosted Coolify is straightforward (same containers, run control plane yourself).
5. **Cloudflare proxy is a vendor dependency.** If Cloudflare has an outage, n8n is unreachable (firewall blocks non-CF traffic). Manual 5-minute fallback: switch DNS to "DNS only" in CF dashboard.
6. **Backup restore is untested until you test it.** Quarterly drill is mandatory.

## Out of scope (explicit deferrals)

These are real concerns we've consciously chosen not to address at tier A. Each has a clear upgrade path.

- **Custom SSH port** — no real security gain
- **Kernel sysctl hardening beyond Ubuntu defaults** — Ubuntu 24.04 ships sane defaults
- **`auditd`, AIDE, CrowdSec/Wazuh** — operational tax exceeds value at this scale
- **Log shipping to external destination** — single-VPS, journald local is fine
- **MFA on SSH (TOTP)** — SSH key + ufw + fail2ban + Cloudflare IP scoping is sufficient at tier A
- **Email/SMTP for system notifications** — using monitoring tool's notification channels instead
- **Multi-environment (staging/prod)** — single environment for now; Pulumi stacks make adding `staging` straightforward later
