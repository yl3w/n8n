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
