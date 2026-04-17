"""Inventory used ONLY for the initial bootstrap pass.

Connects as root using the SSH key deployed via ssh-copy-id.
After Phase 3 completes, switch to inventory.py (maddalab user).
"""

hosts = [
    ("198.144.178.149", {
        "ssh_user": "root",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "hostname": "satmur",
    }),
]
