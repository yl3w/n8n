"""SSH daemon hardening.

Manages /etc/ssh/sshd_config as a single source of truth.
No drop-in configs — the entire sshd config is explicit in one file.
ALWAYS verify non-root admin user works BEFORE running this.
"""

from pyinfra.operations import files, server, systemd

# Deploy the full managed sshd_config
files.put(
    name="Install managed sshd_config",
    src="pyinfra/files/sshd_config",
    dest="/etc/ssh/sshd_config",
    user="root",
    group="root",
    mode="644",
)

# Remove any drop-in configs that could conflict
files.file(
    name="Remove cloud-init sshd config if present",
    path="/etc/ssh/sshd_config.d/50-cloud-init.conf",
    present=False,
)

files.file(
    name="Remove old hardening drop-in if present",
    path="/etc/ssh/sshd_config.d/99-hardening.conf",
    present=False,
)

server.shell(
    name="Validate sshd config syntax",
    commands=["sshd -t"],
)

systemd.service(
    name="Restart sshd",
    service="ssh",
    restarted=True,
)
