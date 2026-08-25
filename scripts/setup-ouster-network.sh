#!/usr/bin/env bash
set -euo pipefail

INTERFACE="${OUSTER_INTERFACE:-enp2s0}"
PROFILE="${OUSTER_NETWORK_PROFILE:-Mobi-Lidar}"

if nmcli -t -f NAME connection show | grep -Fxq "${PROFILE}"; then
  nmcli connection modify "${PROFILE}" connection.interface-name "${INTERFACE}"
else
  nmcli connection add type ethernet ifname "${INTERFACE}" con-name "${PROFILE}"
fi

nmcli connection modify "${PROFILE}" \
  connection.autoconnect yes \
  ipv4.method manual \
  ipv4.addresses "10.5.5.1/24,169.254.1.1/16" \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv4.ignore-auto-dns yes \
  ipv6.method disabled
nmcli connection up "${PROFILE}"

echo "[OK] ${INTERFACE}:"
ip -br addr show dev "${INTERFACE}"
echo
echo "Ouster encontrados:"
timeout 8 avahi-browse -art 2>/dev/null | grep -i -A4 -B1 'Ouster Sensor' || true
