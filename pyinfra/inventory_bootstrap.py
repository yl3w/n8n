"""Inventory used ONLY for the initial bootstrap pass.

Connects as root using the SSH key deployed via ssh-copy-id.
After Phase 3 completes, switch to inventory.py (admin user).
Hostname, address and admin user come from .env.vars (template: .env.vars.example).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.vars")


def env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"{key} is not set — copy .env.vars.example to .env.vars and fill it in")
    return value


hosts = [
    (env("VPS_IPV4"), {
        "ssh_user": "root",
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "hostname": env("VPS_HOSTNAME"),
        "admin_user": env("ADMIN_USER"),
    }),
]
