#!/usr/bin/env bash
set -e

# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source /opt/ouster_ws/install/setup.bash
# shellcheck disable=SC1091
source /ros2_ws/install/setup.bash

exec "$@"
