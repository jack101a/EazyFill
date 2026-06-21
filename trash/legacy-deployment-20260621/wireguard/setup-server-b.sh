#!/usr/bin/env bash
set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_ADDRESS="${WG_ADDRESS:-10.99.0.2/24}"
WG_PORT="${WG_PORT:-51820}"
SERVER_A_PUBLIC_ENDPOINT="${SERVER_A_PUBLIC_ENDPOINT:-}"
SERVER_A_PUBLIC_KEY="${SERVER_A_PUBLIC_KEY:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root."
  exit 1
fi

if [ -z "${SERVER_A_PUBLIC_ENDPOINT}" ] || [ -z "${SERVER_A_PUBLIC_KEY}" ]; then
  echo "Set SERVER_A_PUBLIC_ENDPOINT and SERVER_A_PUBLIC_KEY."
  exit 1
fi

if ! command -v wg >/dev/null 2>&1; then
  apt-get update
  apt-get install -y wireguard
fi

install -d -m 700 /etc/wireguard
if [ ! -f "/etc/wireguard/${WG_INTERFACE}.key" ]; then
  wg genkey | tee "/etc/wireguard/${WG_INTERFACE}.key" | wg pubkey > "/etc/wireguard/${WG_INTERFACE}.pub"
  chmod 600 "/etc/wireguard/${WG_INTERFACE}.key"
fi

PRIVATE_KEY="$(cat "/etc/wireguard/${WG_INTERFACE}.key")"

cat > "/etc/wireguard/${WG_INTERFACE}.conf" <<EOF
[Interface]
Address = ${WG_ADDRESS}
PrivateKey = ${PRIVATE_KEY}
SaveConfig = false

[Peer]
PublicKey = ${SERVER_A_PUBLIC_KEY}
Endpoint = ${SERVER_A_PUBLIC_ENDPOINT}:${WG_PORT}
AllowedIPs = 10.99.0.0/24
PersistentKeepalive = 25
EOF

systemctl enable "wg-quick@${WG_INTERFACE}"
systemctl restart "wg-quick@${WG_INTERFACE}"

echo "Node B public key:"
cat "/etc/wireguard/${WG_INTERFACE}.pub"
