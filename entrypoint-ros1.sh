#!/usr/bin/env bash
set -e

# shellcheck disable=SC1091
source "/opt/ros/${ROS_DISTRO}/setup.bash"

if [[ -f /opt/mobi_ws/devel/setup.bash ]]; then
  # shellcheck disable=SC1091
  source /opt/mobi_ws/devel/setup.bash
fi

exec "$@"
