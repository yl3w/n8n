#!/usr/bin/env bash
# Restrict inbound traffic to Docker-published ports to Cloudflare IPs on 80/443.
#
# Docker's DNAT rules route published-port traffic through FORWARD, not INPUT,
# so ufw never sees it. DOCKER-USER is evaluated before Docker's own rules; we
# jump from it into a chain we rebuild atomically from the cached Cloudflare
# lists written by cloudflare-ufw-update.sh.
#
# Run by cloudflare-docker-firewall.service (at boot, before docker.service)
# and by cloudflare-ufw-update.sh after each refresh.
# With no cached list it fails closed: only established traffic is allowed in.

set -euo pipefail

CACHE_DIR="/var/lib/cloudflare-ips"
CHAIN="CLOUDFLARE-DOCKER"
LOG_TAG="cloudflare-docker-firewall"

apply() {
    local family=$1 ipt=$2 list=$3
    local ext_if
    ext_if=$(ip "-$family" -o route show default | awk '{print $5; exit}')
    if [[ -z "$ext_if" ]]; then
        logger -t "$LOG_TAG" "no IPv$family default route — skipping $ipt"
        return 0
    fi

    local rules count=0
    rules="*filter
:$CHAIN - [0:0]
-A $CHAIN -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
-A $CHAIN ! -i $ext_if -j RETURN
"
    if [[ -s "$list" ]]; then
        while IFS= read -r cidr || [[ -n "$cidr" ]]; do
            [[ -z "$cidr" ]] && continue
            rules+="-A $CHAIN -s $cidr -p tcp -m conntrack --ctorigdstport 80 -j RETURN
-A $CHAIN -s $cidr -p tcp -m conntrack --ctorigdstport 443 -j RETURN
"
            count=$((count + 1))
        done < "$list"
    else
        logger -t "$LOG_TAG" "WARNING: $list missing — failing closed for $ipt"
    fi
    rules+="-A $CHAIN -j DROP
COMMIT
"

    # Docker creates DOCKER-USER too; creating it first lets us run before Docker.
    "$ipt" -N DOCKER-USER 2>/dev/null || true
    # --noflush keeps other chains; declaring $CHAIN flushes and refills it atomically.
    printf '%s' "$rules" | "${ipt}-restore" --noflush
    "$ipt" -C DOCKER-USER -j "$CHAIN" 2>/dev/null || "$ipt" -I DOCKER-USER 1 -j "$CHAIN"

    logger -t "$LOG_TAG" "$ipt: $count Cloudflare ranges allowed to containers on 80/443 via $ext_if"
}

apply 4 iptables "$CACHE_DIR/ips-v4"
apply 6 ip6tables "$CACHE_DIR/ips-v6"
