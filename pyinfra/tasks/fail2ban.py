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
