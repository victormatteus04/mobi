#!/usr/bin/env bash
set -e

# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source /opt/ouster_ws/install/setup.bash
# shellcheck disable=SC1091
source /ros2_ws/install/setup.bash

# Em outro computador da rede (ex.: notebook rodando o RViz): conecta direto
# ao roteador Zenoh do robo em modo cliente, sem roteador local.
# Ex.: MOBI_ZENOH_CONNECT=tcp/192.168.7.2:7447
if [[ -n "${MOBI_ZENOH_CONNECT:-}" ]]; then
  export ZENOH_CONFIG_OVERRIDE="mode=\"client\";connect/endpoints=[\"${MOBI_ZENOH_CONNECT}\"]"
fi

exec "$@"
