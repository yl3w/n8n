"""SSH daemon hardening.

Disables root login, password auth, restricts to maddalab + coolify.
ALWAYS verify non-root admin user works BEFORE running this.
"""

from pyinfra.operations import files, server, systemd

# Remove cloud-init SSH config that may override our hardening
files.file(
    name="Remove cloud-init sshd config if present",
    path="/etc/ssh/sshd_config.d/50-cloud-init.conf",
    present=False,
)

# Comment out PermitRootLogin in main sshd_config (first-match-wins safety)
server.shell(
    name="Disable PermitRootLogin in main sshd_config",
    commands=[
        "sed -i 's/^PermitRootLogin yes/#PermitRootLogin yes  # disabled by pyinfra hardening/' /etc/ssh/sshd_config || true",
    ],
)

files.put(
    name="Install sshd hardening drop-in config",
    src="pyinfra/files/sshd-hardening.conf",
    dest="/etc/ssh/sshd_config.d/99-hardening.conf",
    user="root",
    group="root",
    mode="644",
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
