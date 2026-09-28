"""Cloudflare DNS and zone settings for satmur.com."""

import os
from pathlib import Path

import pulumi
import pulumi_cloudflare as cloudflare
from dotenv import load_dotenv

# VPS addresses come from .env.vars (template: .env.vars.example), not stack config
load_dotenv(Path(__file__).resolve().parent.parent / ".env.vars")


def env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"{key} is not set — copy .env.vars.example to .env.vars and fill it in")
    return value


# --- Config ---
config = pulumi.Config("satmur")
domain = config.require("domain")
vps_ipv4 = env("VPS_IPV4")
vps_ipv6 = env("VPS_IPV6")
n8n_subdomain = config.require("n8nSubdomain")

# --- Look up the existing zone (registered via Cloudflare Registrar) ---
zone = cloudflare.get_zone(filter=cloudflare.GetZoneFilterArgs(name=domain, match="all"))

# --- DNS records for n8n.<domain>, both A and AAAA, both proxied ---
n8n_a = cloudflare.DnsRecord(
    "n8n_a",
    zone_id=zone.zone_id,
    name=n8n_subdomain,
    type="A",
    content=vps_ipv4,
    proxied=True,
    ttl=1,  # 1 = Cloudflare auto when proxied
    comment="n8n service — managed by Pulumi (vpsconfig repo)",
)

n8n_aaaa = cloudflare.DnsRecord(
    "n8n_aaaa",
    zone_id=zone.zone_id,
    name=n8n_subdomain,
    type="AAAA",
    content=vps_ipv6,
    proxied=True,
    ttl=1,
    comment="n8n service — managed by Pulumi (vpsconfig repo)",
)

# --- Zone-level SSL/TLS settings (v6: one ZoneSetting per setting) ---
# Full Strict requires a real cert on origin. Coolify/Traefik will provision
# Let's Encrypt via DNS-01 challenge using a separate Cloudflare API token.
settings = {
    "ssl": "strict",
    "min_tls_version": "1.2",
    "always_use_https": "on",
    "automatic_https_rewrites": "on",
    "opportunistic_encryption": "on",
    "tls_1_3": "on",
}

for setting_id, value in settings.items():
    cloudflare.ZoneSetting(
        f"zone_setting_{setting_id}",
        zone_id=zone.zone_id,
        setting_id=setting_id,
        value=value,
    )

# --- Outputs for downstream tools / humans ---
pulumi.export("zone_id", zone.zone_id)
pulumi.export("n8n_fqdn", f"{n8n_subdomain}.{domain}")
