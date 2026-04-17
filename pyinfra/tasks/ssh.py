"""SSH daemon hardening.

Disables root login, password auth, restricts to maddalab + coolify.
ALWAYS verify non-root admin user works BEFORE running this.
"""

from pyinfra.operations import files, server, systemd

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
    name="Reload sshd",
    service="ssh",
    reloaded=True,
)
