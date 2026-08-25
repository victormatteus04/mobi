#!/usr/bin/env bash
set -e

# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
# Use local_setup: o underlay ROS 2 ja foi carregado acima.
# shellcheck disable=SC1091
source /ros-humble-ros1-bridge/install/local_setup.bash

echo "[mobi-bridge] ROS_MASTER_URI=${ROS_MASTER_URI}"
echo "[mobi-bridge] ROS_IP=${ROS_IP}"
echo "[mobi-bridge] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"

exec "$@"

