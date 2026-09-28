"""Add Coolify Cloud's public key to coolify user's authorized_keys.

This file relies on pyinfra/files/coolify-cloud.pub which is .gitignored.
Paste the key shown in Coolify Cloud (Servers → Add) into that file first.
"""

from pathlib import Path
from pyinfra.operations import files

key_path = Path(__file__).parent.parent / "files" / "coolify-cloud.pub"
if not key_path.exists():
    raise SystemExit(f"Missing {key_path} — paste Coolify Cloud's public key there first")
coolify_pubkey = key_path.read_text().strip()

files.line(
    name="Authorize Coolify Cloud key for coolify user",
    path="/home/coolify/.ssh/authorized_keys",
    line=coolify_pubkey,
)
