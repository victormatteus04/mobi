#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
ros2 daemon stop >/dev/null 2>&1 || true

SENSOR_SET_CSV="${1:-${MOBI_SENSOR_SET:-ouster,d435i,t265}}"
SENSOR_SET_CSV="${SENSOR_SET_CSV// /,}"
WAIT_TIMEOUT="${SENSOR_WAIT_TIMEOUT:-60}"
TOPICS_CONFIG="${MOBI_TOPICS_CONFIG_SCRIPT:-/mobi/topics_config.py}"
TOPICS_CONFIG_YAML="${MOBI_TOPICS_CONFIG:-/etc/mobi/topics.yaml}"

wait_for_message() {
  local topic=$1
  local label=$2
  local type=$3
  local deadline=$((SECONDS + WAIT_TIMEOUT))

  while ((SECONDS < deadline)); do
    if timeout 4 ros2 topic echo --once --no-daemon --qos-reliability best_effort \
      "${topic}" ${type:+"${type}"} >/dev/null 2>&1; then
      printf '[OK] %-14s %s\n' "${label}" "${topic}"
      return 0
    fi
  done
  printf '[ERRO] %-12s sem dados em %s\n' "${label}" "${topic}" >&2
  return 1
}

required_output="$(python3 "${TOPICS_CONFIG}" --config "${TOPICS_CONFIG_YAML}" \
  required "${SENSOR_SET_CSV}")" || exit 2

status=0
while IFS=$'\t' read -r topic label type; do
  [[ -z "${topic}" ]] && continue
  wait_for_message "${topic}" "${label}" "${type}" || status=1
done <<< "${required_output}"

exit "${status}"
