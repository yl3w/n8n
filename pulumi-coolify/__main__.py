"""Coolify Cloud resources for satmur: server, Traefik proxy, and the n8n service.

Everything here was created by hand in Coolify first (plan Phases 7-8) and then
adopted with `import_`. Resources are `protect`ed: deleting or replacing the
n8n service would orphan its n8n-data volume (workflows, credentials, SQLite DB).

Setup on a fresh clone (sdks/ is generated, not committed):
    cd pulumi-coolify && pulumi install   # ends with a harmless "linking package" error;
    uv sync                               # the root pyproject.toml links sdks/coolify
"""

import os
from pathlib import Path

import pulumi
import pulumi_coolify as coolify
from dotenv import load_dotenv

HERE = Path(__file__).parent
# VPS address comes from .env.vars (template: .env.vars.example)
load_dotenv(HERE.resolve().parent / ".env.vars")


def env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"{key} is not set — copy .env.vars.example to .env.vars and fill it in")
    return value

config = pulumi.Config()
cf_dns_token = config.require_secret("cfDnsToken")
n8n_encryption_key = config.require_secret("n8nEncryptionKey")

# Existing Coolify IDs, used to adopt resources on first `pulumi up`. After a
# successful import these can stay: `import_` is a no-op once the resource is in state.
SERVER_UUID = "sifz3twahnhdmrwyi3qoos9o"
PRIVATE_KEY_UUID = "ypih15axijd76oncxhao4uqw"  # "n8n-vps"; the key itself stays unmanaged
PROJECT_UUID = "tckhx2vdjuz08uiehdcat4ts"
SERVICE_UUID = "ibgqn5lsms5rszavro5pt7jw"
ENCRYPTION_KEY_ENV_UUID = "pqzi8fbldnan8sdfnz9chzpa"


def adopt(import_id: str) -> pulumi.ResourceOptions:
    return pulumi.ResourceOptions(import_=import_id, protect=True)


# --- Server (registered in Phase 7; SSH as `coolify`) ---
server = coolify.Server(
    "n8n-server",
    name="n8n",
    description="n8n vps config",
    ip=env("VPS_IPV4"),
    user="coolify",
    port=22,
    private_key_uuid=PRIVATE_KEY_UUID,
    opts=adopt(SERVER_UUID),
)

# --- Traefik proxy: Cloudflare DNS-01 for Let's Encrypt (Task 7.5) ---
# traefik-proxy.yaml holds the config with a placeholder; the token comes from
# Pulumi secret config so it never lands in git. Coolify stores it without a
# trailing newline.
proxy_template = (HERE / "traefik-proxy.yaml").read_text().rstrip("\n")
proxy = coolify.ServerProxy(
    "n8n-proxy",
    server_uuid=SERVER_UUID,
    proxy_type="traefik",
    redirect_enabled=True,
    configuration=pulumi.Output.secret(
        cf_dns_token.apply(lambda t: proxy_template.replace("__CF_DNS_API_TOKEN__", t))
    ),
    opts=adopt(SERVER_UUID),
)

# --- Project + environment ---
project = coolify.Project(
    "automation",
    name="automation",
    description="n8n + workflows",
    opts=adopt(PROJECT_UUID),
)

environment = coolify.Environment(
    "production",
    name="production",
    project_uuid=PROJECT_UUID,
    opts=adopt(f"{PROJECT_UUID}:production"),
)

# --- n8n service (SQLite; external task runners) ---
service = coolify.Service(
    "n8n",
    name="n8n",
    project_uuid=PROJECT_UUID,
    server_uuid=SERVER_UUID,
    environment_name="production",
    docker_compose_raw=(HERE / "n8n-compose.yaml").read_text(),
    urls=[coolify.ServiceUrlArgs(name="n8n", url="https://n8n.satmur.com")],
    connect_to_docker_network=False,
    is_container_label_escape_enabled=True,
    opts=adopt(f"{PROJECT_UUID}:{SERVER_UUID}:production:{SERVICE_UUID}"),
)

# Only the encryption key is managed here; the compose file's other variables
# use their ${VAR:-default}s and Coolify generates SERVICE_* values itself.
encryption_key = coolify.EnvironmentVariable(
    "n8n-encryption-key",
    service_uuid=SERVICE_UUID,
    key="N8N_ENCRYPTION_KEY",
    comment="Generated useing openssl",
    value=n8n_encryption_key,
    is_literal=False,
    is_multiline=False,
    is_preview=False,
    opts=adopt(f"service:{SERVICE_UUID}:{ENCRYPTION_KEY_ENV_UUID}"),
)

pulumi.export("server_uuid", server.uuid)
pulumi.export("service_uuid", service.uuid)
pulumi.export("service_status", service.status)
