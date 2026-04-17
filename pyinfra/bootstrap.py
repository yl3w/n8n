"""One-time bootstrap: create maddalab and coolify users.

Run: uv run pyinfra pyinfra/inventory_bootstrap.py pyinfra/bootstrap.py
"""

from pathlib import Path
from pyinfra.operations import files, server

LAPTOP_PUBKEY_PATH = Path.home() / ".ssh" / "id_ed25519_vps.pub"
laptop_pubkey = LAPTOP_PUBKEY_PATH.read_text().strip()

# --- maddalab user: human admin, sudo with password ---
server.user(
    name="Create maddalab admin user",
    user="maddalab",
    groups=["sudo"],
    shell="/bin/bash",
    create_home=True,
    ensure_home=True,
)

files.directory(
    name="Ensure maddalab .ssh directory",
    path="/home/maddalab/.ssh",
    user="maddalab",
    group="maddalab",
    mode="700",
)

files.file(
    name="Ensure maddalab authorized_keys exists",
    path="/home/maddalab/.ssh/authorized_keys",
    user="maddalab",
    group="maddalab",
    mode="600",
    touch=True,
)

files.line(
    name="Add laptop public key to maddalab authorized_keys",
    path="/home/maddalab/.ssh/authorized_keys",
    line=laptop_pubkey,
)

# --- coolify user: Coolify Cloud SSH agent, NOPASSWD sudo ---
server.user(
    name="Create coolify system user",
    user="coolify",
    groups=[],
    shell="/bin/bash",
    create_home=True,
    ensure_home=True,
)

files.directory(
    name="Ensure coolify .ssh directory",
    path="/home/coolify/.ssh",
    user="coolify",
    group="coolify",
    mode="700",
)

files.file(
    name="Ensure coolify authorized_keys exists",
    path="/home/coolify/.ssh/authorized_keys",
    user="coolify",
    group="coolify",
    mode="600",
    touch=True,
)

# Coolify Cloud's public key is added later in Phase 7.

files.put(
    name="Install coolify NOPASSWD sudoers entry",
    src="pyinfra/files/sudoers-coolify",
    dest="/etc/sudoers.d/coolify",
    user="root",
    group="root",
    mode="440",
)
