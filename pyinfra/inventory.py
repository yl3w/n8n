"""Steady-state inventory — connect as maddalab via SSH key, escalate via sudo."""

hosts = [
    ("198.144.178.149", {
        "ssh_user": "maddalab",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "_sudo": True,
        "_use_sudo_password": True,
    }),
]
