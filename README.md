# vpsconfig

Infrastructure-as-code for **n8n at https://n8n.satmur.com**: one hardened Ubuntu 24.04 VPS dedicated to n8n,
managed by Coolify Cloud, behind Cloudflare.

| Layer | Tool | Where |
|---|---|---|
| VPS OS config (users, SSH, firewall, Docker, …) | [pyinfra](https://pyinfra.com) over SSH | `pyinfra/` |
| Cloudflare DNS + zone TLS settings | [Pulumi](https://pulumi.com) (Python) | `pulumi/` — project `vpsconfig-cf` |
| Coolify server, Traefik proxy, n8n service | Pulumi + [Coolify provider](https://github.com/coolify-terraform/terraform-provider-coolify) | `pulumi-coolify/` — project `vpsconfig-coolify` |

Design rationale lives in `docs/superpowers/specs/`; the step-by-step build log (phases 0–12) is
`docs/superpowers/plans/`. This README is the operator's guide.

## How it fits together

```
 Browser / webhook callers
          │ HTTPS
          ▼
 Cloudflare (proxied DNS, SSL "Full (strict)")        ◄── pulumi/
          │ only Cloudflare IPs may reach 80/443
          ▼
 n8n VPS                                              ◄── pyinfra/
   ufw + CLOUDFLARE-DOCKER iptables chain, fail2ban, unattended-upgrades
   Docker
     ├── coolify-proxy (Traefik v3, Let's Encrypt via Cloudflare DNS-01)
     └── n8n service: n8n 2.41.3 + task runners, SQLite in volume n8n-data
          ▲
          │ SSH as user `coolify`
 Coolify Cloud (control plane, app.coolify.io)        ◄── pulumi-coolify/
```

Key facts:

- **The n8n host:** this VPS runs n8n and nothing else. It's reached as `n8n` via the SSH alias in
  [Local setup](#local-setup). Its hostname (`n8n`) and IPv4/IPv6 addresses come from your local `.env.vars`.
- **Users:** one human admin account (SSH key + sudo **password**; the owner gives you its name,
  written `<admin-user>` below; set as `ADMIN_USER` in `.env.vars`) and `coolify` (Coolify Cloud agent, passwordless sudo). Root login and
  password SSH are disabled; `AllowUsers` in `pyinfra/files/sshd_config.j2` admits only these two.
- **Web traffic** is accepted only from Cloudflare. Docker-published ports bypass ufw, so the same
  allowlist is also enforced in the `DOCKER-USER` → `CLOUDFLARE-DOCKER` chain. Both are refreshed weekly
  from Cloudflare's published ranges.
- **n8n data** (workflows, credentials, SQLite DB, encryption-key `config`) lives in the Docker volume
  `*n8n-data*`. **There are no backups yet** — see [Status and known gaps](#status-and-known-gaps).

## Repository layout

```
  .env.vars.example       template for .env.vars (gitignored): hostname, IPs, admin user
pyinfra/
  inventory.py            steady-state inventory (admin user + sudo)
  inventory_bootstrap.py  one-time: root, before users exist
  bootstrap.py            one-time: create the admin + coolify users
  tasks/                  one file per concern (see "Running pyinfra tasks")
  files/                  everything the tasks install (configs, scripts, units)
pulumi/                   Cloudflare stack (DNS A/AAAA for n8n, zone SSL settings)
pulumi-coolify/
  __main__.py             Coolify resources (imported from the hand-built setup)
  n8n-compose.yaml        the n8n service's docker-compose, as deployed
  traefik-proxy.yaml      Traefik config; __CF_DNS_API_TOKEN__ is filled from a Pulumi secret
  sdks/                   generated Python SDK for the provider — gitignored, see setup
docs/superpowers/         design spec + implementation plan
```

## Access you need

Ask the owner for each of these; nothing here works without them.

| What | Why |
|---|---|
| **`.env.vars` values** | The VPS hostname, IPv4/IPv6 and admin user name — deliberately not in git. |
| **SSH access to the n8n host** | Only keys in the admin account's `authorized_keys` can log in. Send the owner your **public** key to add. Today there is a single admin account — see gaps. |
| Admin account **name and sudo password** | pyinfra and most server commands prompt for it. |
| **Pulumi Cloud** org membership (the owner's org) | Stack state, and decryption of the secrets in `Pulumi.prod.yaml`. |
| **Coolify Cloud** team membership | UI access to the server and n8n service. |
| **Cloudflare** account (zone `satmur.com`) | DNS, API tokens, R2. |
| **Password-manager** entries | n8n owner login, `N8N_ENCRYPTION_KEY`, Cloudflare tokens, admin sudo password. |

## Local setup

1. **Tools** (macOS): `brew install uv pulumi`. Python 3.12 is pinned in `.python-version`; uv installs it.
2. **Clone and install** — order matters: the Coolify SDK must be generated before `uv sync`, because
   the root `pyproject.toml` references it as a workspace member.
   ```sh
   git clone git@github.com:yl3w/n8n.git vpsconfig && cd vpsconfig
   (cd pulumi-coolify && pulumi install)   # ends with a harmless "linking package ... no pyproject.toml" error
   uv sync
   ```
3. **Local values:** create `.env.vars` from the template and fill in the values the owner gave you.
   pyinfra and both Pulumi projects read it; a missing value stops them with a clear error.
   ```sh
   cp .env.vars.example .env.vars && chmod 600 .env.vars
   ```
4. **Pulumi login:** `pulumi login` (Pulumi Cloud), then check both stacks resolve:
   ```sh
   (cd pulumi && pulumi stack select prod && pulumi preview)
   (cd pulumi-coolify && pulumi stack select prod && pulumi preview)
   ```
   Both should report only `unchanged` resources. Anything else means someone changed things outside code — stop and investigate.
5. **SSH key + alias.** The inventory expects the key at `~/.ssh/id_ed25519_vps`. Add to `~/.ssh/config`:
   ```
   Host n8n
       HostName <vps-ipv4>
       User <admin-user>
       IdentityFile ~/.ssh/id_ed25519_vps
       IdentitiesOnly yes
   ```
   Then `ssh n8n` should give you a shell on the n8n host.

## Day-to-day operations

### Connecting

```sh
ssh n8n                          # shell as the admin user
ssh -t n8n 'sudo docker ps'      # one-off sudo command (-t so sudo can prompt)
```

The admin user is not in the `docker` group, so Docker commands need `sudo`.

### Running pyinfra tasks

Tasks are idempotent; run the one you changed. Preview first with `--dry`:

```sh
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/firewall.py --dry
uv run pyinfra pyinfra/inventory.py pyinfra/tasks/firewall.py
```

You will be prompted for the admin user's sudo password. There is no "run everything" entry point yet;
for a full pass run them in this order:

| Task | What it manages | Side effects |
|---|---|---|
| `system.py` | hostname, `/etc/hosts`, UTC, locale, 2 GB swap | — |
| `firewall.py` | ufw rules, Cloudflare allowlist for ufw **and** Docker, weekly refresh timer, boot-time Docker rules | enables ufw |
| `fail2ban.py` | SSH jail: 5 failures in 10 min → 1 h ban | restarts fail2ban |
| `unattended_upgrades.py` | automatic security updates | — |
| `docker.py` | Docker CE, `daemon.json` (log rotation, live-restore), weekly prune timer | **restarts Docker** (containers survive via live-restore; expect a blip) |
| `ssh.py` | full `sshd_config` | **restarts sshd** — keep an existing session open |
| `coolify_authorize.py` | adds Coolify Cloud's public key for `coolify` | needs `pyinfra/files/coolify-cloud.pub` (gitignored; copy it from Coolify → Keys & Tokens) |

`bootstrap.py` (with `inventory_bootstrap.py`, as root) is only for a brand-new VPS — see the plan, Phase 3.

### Changing Cloudflare DNS or zone settings

Edit `pulumi/__main__.py`, then `cd pulumi && pulumi preview && pulumi up`.

### Changing Coolify / n8n configuration

Coolify is managed from `pulumi-coolify/`. **Make changes in code, not in the Coolify UI** — UI edits
drift from the code, and the next `pulumi up` will overwrite them.

```sh
cd pulumi-coolify
# edit n8n-compose.yaml, traefik-proxy.yaml or __main__.py
pulumi preview --diff
pulumi up
```

Pulumi saves configuration in Coolify but does **not restart containers**. After an update, Coolify
shows "Changes pending": restart the n8n service (**Actions → Restart**) or the proxy
(**Servers → n8n → Proxy → Restart Proxy**). Then confirm `pulumi preview` shows no changes.

**Upgrading n8n:** read the [release notes](https://docs.n8n.io/release-notes/), then change *both* image
tags in `n8n-compose.yaml` (`n8nio/n8n:X` and `n8nio/runners:X` — they must match), `pulumi up`, restart
the service, and run a workflow to smoke-test.

### Health checks

```sh
curl -s https://n8n.satmur.com/healthz                    # {"status":"ok"}
ssh n8n 'echo | openssl s_client -connect 127.0.0.1:443 -servername n8n.satmur.com 2>/dev/null \
  | openssl x509 -noout -issuer -enddate'                 # Let's Encrypt, not "TRAEFIK DEFAULT CERT"
source .env.vars && curl -s -m 5 "http://$VPS_IPV4/" || echo "blocked"   # direct origin access must time out
```

Common Cloudflare errors: **521** nothing listening on the VPS (proxy down); **526** origin certificate
invalid (Traefik has no Let's Encrypt cert for the host — check the proxy logs); **502/503** Traefik is up
but can't reach n8n.

## Secrets

Never commit secrets. They live in:

| Secret | Stored in |
|---|---|
| Cloudflare token for Pulumi DNS (`cloudflare:apiToken`) | `pulumi/Pulumi.prod.yaml` (Pulumi-encrypted) |
| Coolify API token (`coolify:token`) | `pulumi-coolify/Pulumi.prod.yaml` (encrypted) |
| Cloudflare DNS-01 token for Traefik (`cfDnsToken`, expires 2027-10-01) | `pulumi-coolify/Pulumi.prod.yaml` (encrypted) → injected into the proxy config |
| `N8N_ENCRYPTION_KEY` (`n8nEncryptionKey`) | `pulumi-coolify/Pulumi.prod.yaml` (encrypted) **and** the password manager |
| VPS hostname, IPs, admin user name (not secret, but kept out of this public repo) | `.env.vars` (gitignored) |
| Coolify's SSH key (`n8n-vps`) | Coolify only; public half in `pyinfra/files/coolify-cloud.pub` (gitignored) |

Set or rotate one with `pulumi config set --secret <name>` (it prompts; the value stays out of shell
history), then `pulumi up` and restart what uses it.

**`N8N_ENCRYPTION_KEY` is irreplaceable**: n8n encrypts every stored credential with it. Never
regenerate it; losing it means re-entering every credential even with a full data backup.

## Rules that keep production safe

- **Don't recreate the n8n service.** A new service gets a new, empty `n8n-data` volume. All Coolify
  resources are `protect`ed in Pulumi; if a preview ever shows `replace` or `delete` for the service,
  stop.
- **SSH changes:** keep a working session open while running `ssh.py`, and test a *new* login before
  closing it. The VNC console in the VPS provider's panel is the fallback.
- **Keep Cloudflare proxied.** Switching `n8n.satmur.com` to "DNS only" exposes the origin IP — and
  the firewall only admits Cloudflare, so the site would go down anyway.
- **This repo is public.** Only commit placeholders and Pulumi ciphertext; server IPs and the admin user
  name belong in `.env.vars`. Check for secrets before
  pushing (`git diff --cached`).
- **Scripts that need sudo need a terminal.** Commands run by non-interactive tools can't answer the
  sudo prompt; run those in your own terminal.

## Status and known gaps

Done (plan phases 0–4, 6–8): hardened host, Docker, Coolify, n8n live with valid TLS, webhooks tested,
Coolify managed by Pulumi.

Open:

1. **No backups (Phase 9).** Losing the VPS or its disk loses all workflows and credentials. Planned:
   daily restic snapshots of `n8n-data` (with a consistent `sqlite3 .backup`) to Cloudflare R2.
2. **Single admin account.** Everyone with access shares one admin account. Per-person users would give
   individual audit trails and revocation.
3. **No uptime monitoring (Phase 10)** and no aggregate `deploy.py` (Phase 11).
4. **Provider-level firewall (Phase 5)** in the VPS panel: status unknown; SSH (22) is open to the
   internet, protected by key-only auth and fail2ban.
5. **Coolify provider is young** (`coolify-terraform/coolify` 0.1.x, community-maintained). It's pinned in
   `pulumi-coolify/Pulumi.yaml`; read its changelog before bumping.
