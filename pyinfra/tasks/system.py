"""System-level config: hostname, timezone, locale, swap file."""

from pyinfra.operations import apt, files, server

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

# --- Locale ---
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
