#!/usr/bin/env bash
# Refresh ufw rules to allow only Cloudflare IPs on 80/443.
# Run by cloudflare-ufw-update.service (triggered weekly).
# On fetch failure, leaves existing rules in place.

set -euo pipefail

CF_V4_URL="https://www.cloudflare.com/ips-v4"
CF_V6_URL="https://www.cloudflare.com/ips-v6"
LOG_TAG="cloudflare-ufw-update"

logger -t "$LOG_TAG" "starting refresh"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if ! curl -fsSL --max-time 30 "$CF_V4_URL" -o "$TMPDIR/v4.txt"; then
    logger -t "$LOG_TAG" "ERROR: failed to fetch $CF_V4_URL — leaving existing rules"
    exit 1
fi
if ! curl -fsSL --max-time 30 "$CF_V6_URL" -o "$TMPDIR/v6.txt"; then
    logger -t "$LOG_TAG" "ERROR: failed to fetch $CF_V6_URL — leaving existing rules"
    exit 1
fi

if [[ ! -s "$TMPDIR/v4.txt" ]] || [[ ! -s "$TMPDIR/v6.txt" ]]; then
    logger -t "$LOG_TAG" "ERROR: fetched IP list was empty — leaving existing rules"
    exit 1
fi
grep -qE '^[0-9.]+/[0-9]+$' "$TMPDIR/v4.txt" || { logger -t "$LOG_TAG" "ERROR: v4 list malformed"; exit 1; }
grep -qE '^[0-9a-f:]+/[0-9]+$' "$TMPDIR/v6.txt" || { logger -t "$LOG_TAG" "ERROR: v6 list malformed"; exit 1; }

# Delete all existing cloudflare-managed rules by comment tag
ufw status numbered | grep 'cloudflare-managed' | awk -F'[][]' '{print $2}' | sort -rn | while read -r idx; do
    yes | ufw delete "$idx" >/dev/null 2>&1 || true
done

# Add fresh rules
while IFS= read -r cidr; do
    [[ -z "$cidr" ]] && continue
    ufw allow proto tcp from "$cidr" to any port 80 comment 'cloudflare-managed' >/dev/null
    ufw allow proto tcp from "$cidr" to any port 443 comment 'cloudflare-managed' >/dev/null
done < "$TMPDIR/v4.txt"

while IFS= read -r cidr; do
    [[ -z "$cidr" ]] && continue
    ufw allow proto tcp from "$cidr" to any port 80 comment 'cloudflare-managed' >/dev/null
    ufw allow proto tcp from "$cidr" to any port 443 comment 'cloudflare-managed' >/dev/null
done < "$TMPDIR/v6.txt"

ufw reload >/dev/null
V4_COUNT=$(wc -l < "$TMPDIR/v4.txt")
V6_COUNT=$(wc -l < "$TMPDIR/v6.txt")
logger -t "$LOG_TAG" "refresh complete — $V4_COUNT v4 + $V6_COUNT v6 ranges allowed on 80/443"
