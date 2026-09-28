"""Steady-state inventory — connect as the admin user via SSH key, escalate via sudo.

Hostname, address and admin user come from .env.vars (template: .env.vars.example).
To add another VPS, append to the hosts list with its own hostname and IP.
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
        "ssh_user": env("ADMIN_USER"),
        "ssh_key": "~/.ssh/id_ed25519_vps",
        "_sudo": True,
        "_use_sudo_password": True,
        "hostname": env("VPS_HOSTNAME"),
        "admin_user": env("ADMIN_USER"),
    }),
]
