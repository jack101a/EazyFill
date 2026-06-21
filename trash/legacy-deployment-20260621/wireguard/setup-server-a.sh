#!/usr/bin/env bash
set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_ADDRESS="${WG_ADDRESS:-10.99.0.1/24}"
WG_PORT="${WG_PORT:-51820}"
NODE_B_PUBLIC_KEY="${NODE_B_PUBLIC_KEY:-}"
NODE_B_ALLOWED_IP="${NODE_B_ALLOWED_IP:-10.99.0.2/32}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root."
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
ListenPort = ${WG_PORT}
PrivateKey = ${PRIVATE_KEY}
SaveConfig = false

EOF

if [ -n "${NODE_B_PUBLIC_KEY}" ]; then
  cat >> "/etc/wireguard/${WG_INTERFACE}.conf" <<EOF
[Peer]
PublicKey = ${NODE_B_PUBLIC_KEY}
AllowedIPs = ${NODE_B_ALLOWED_IP}

EOF
fi

systemctl enable "wg-quick@${WG_INTERFACE}"
systemctl restart "wg-quick@${WG_INTERFACE}"

echo "Node A public key:"
cat "/etc/wireguard/${WG_INTERFACE}.pub"
echo "Open UDP ${WG_PORT} on the Oracle firewall/security list."
