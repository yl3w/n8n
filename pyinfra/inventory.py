"""Steady-state inventory — connect as maddalab via SSH key, escalate via sudo.

To add another VPS, append to the hosts list with its own hostname and IP.
"""

hosts = [
    ("198.144.178.149", {
        "ssh_user": "maddalab",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "_sudo": True,
        "_use_sudo_password": True,
        "hostname": "satmur",
    }),
]
