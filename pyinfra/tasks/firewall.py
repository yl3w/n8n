"""ufw firewall + Cloudflare IP refresh timer."""

from pyinfra.operations import apt, files, server, systemd

apt.packages(
    name="Install ufw + curl",
    packages=["ufw", "curl"],
    update=True,
    cache_time=3600,
)

# --- Bootstrap rules ---
server.shell(
    name="Allow SSH (22/tcp) from anywhere",
    commands=["ufw allow 22/tcp comment 'ssh'"],
)

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

# Enable ufw (--force avoids interactive prompt)
server.shell(
    name="Enable ufw",
    commands=["ufw --force enable"],
)
