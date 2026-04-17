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
        "  -o /etc/apt/keyrings/docker.asc && "
        " chmod a+r /etc/apt/keyrings/docker.asc)",
    ],
)

# --- Docker apt repo ---
server.shell(
    name="Add Docker apt repo",
    commands=[
        'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] '
        'https://download.docker.com/linux/ubuntu noble stable" '
        '> /etc/apt/sources.list.d/docker.list',
    ],
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
    restarted=True,
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
