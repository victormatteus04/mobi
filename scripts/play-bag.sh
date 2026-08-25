#!/usr/bin/env bash
set -eo pipefail

BAG_NAME="${1:?Uso: play-bag.sh NOME [args extras do ros2 bag play]}"
shift || true
BAG_PATH="/bags/${BAG_NAME}"

source /opt/ros/humble/setup.bash

if [[ ! -e "${BAG_PATH}" ]]; then
  echo "Bag nao encontrada: ${BAG_PATH}" >&2
  exit 2
fi

RATE="${BAG_PLAY_RATE:-1.0}"
loop_args=()
[[ "${BAG_PLAY_LOOP:-false}" == "true" ]] && loop_args+=(--loop)

echo "[PLAY] ${BAG_PATH} (rate=${RATE})"
ros2 bag play "${BAG_PATH}" --clock --rate "${RATE}" "${loop_args[@]}" "$@" &
play_pid=$!
trap 'kill -INT "${play_pid}" 2>/dev/null' INT TERM
wait "${play_pid}"
