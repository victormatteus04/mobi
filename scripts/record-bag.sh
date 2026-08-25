#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash

# O daemon do ros2cli (usado para resolver o tipo de um topico quando nao
# informado) e compartilhado entre containers via network/ipc host e pode
# ficar num estado invalido apos varios containers subirem/cairem. Como
# passamos o tipo explicito para os topicos conhecidos (config/topics.yaml),
# so o "daemon stop" aqui protege o caso de BAG_TOPICS manuais/desconhecidos.
ros2 daemon stop >/dev/null 2>&1 || true

BAG_NAME="${1:?Uso: record-bag.sh NOME [base,ouster,d435i,t265,d455]}"
SENSOR_SET_CSV="${2:-${BAG_SENSOR_SET:-base,ouster,d435i,t265}}"
SENSOR_SET_CSV="${SENSOR_SET_CSV// /,}"
SENSOR_SET="${SENSOR_SET_CSV//,/ }"
OUTPUT_PATH="/bags/${BAG_NAME}"
TOPICS_CONFIG="${MOBI_TOPICS_CONFIG_SCRIPT:-/mobi/topics_config.py}"
TOPICS_CONFIG_YAML="${MOBI_TOPICS_CONFIG:-/etc/mobi/topics.yaml}"
WAIT_TIMEOUT="${SENSOR_WAIT_TIMEOUT:-60}"
MAX_CACHE_SIZE="${BAG_MAX_CACHE_SIZE:-1073741824}"
MAX_BAG_SIZE="${BAG_MAX_SIZE:-8589934592}"
STORAGE_CONFIG_FILE="${BAG_STORAGE_CONFIG:-/etc/mobi/mcap-compression.yaml}"
GENERATE_METADATA="${MOBI_GENERATE_METADATA_SCRIPT:-/mobi/generate_metadata.py}"
EXTRA_TOPICS="${BAG_TOPICS:-}"
EXTRA_TOPICS="${EXTRA_TOPICS//,/ }"
ONLY_EXTRA_TOPICS="${BAG_TOPICS_ONLY:-false}"

if [[ "${BAG_NAME}" == */* || "${BAG_NAME}" == "." || "${BAG_NAME}" == ".." ]]; then
  echo "Use apenas um nome de sessao, sem caminho." >&2
  exit 2
fi
if [[ -e "${OUTPUT_PATH}" ]]; then
  echo "A sessao ja existe: ${OUTPUT_PATH}" >&2
  exit 2
fi

declare -a candidates=()
declare -a required=()
declare -A required_type=()

if [[ "${ONLY_EXTRA_TOPICS}" != "true" ]]; then
  topics_output="$(python3 "${TOPICS_CONFIG}" --config "${TOPICS_CONFIG_YAML}" \
    topics "${SENSOR_SET_CSV},tf")" || exit 2
  while IFS= read -r topic; do
    [[ -n "${topic}" ]] && candidates+=("${topic}")
  done <<< "${topics_output}"

  required_output="$(python3 "${TOPICS_CONFIG}" --config "${TOPICS_CONFIG_YAML}" \
    required "${SENSOR_SET_CSV}")" || exit 2
  while IFS=$'\t' read -r topic _label type; do
    if [[ -n "${topic}" ]]; then
      required+=("${topic}")
      required_type["${topic}"]="${type}"
    fi
  done <<< "${required_output}"
fi

if [[ -n "${EXTRA_TOPICS}" ]]; then
  required+=(${EXTRA_TOPICS})
  candidates+=(${EXTRA_TOPICS})
fi

if ((${#required[@]} == 0)); then
  echo "Nenhum topico selecionado. Informe SENSOR_SET ou BAG_TOPICS." >&2
  exit 2
fi

wait_for_message() {
  local topic=$1
  local type=$2
  local deadline=$((SECONDS + WAIT_TIMEOUT))
  echo "[CHECK] ${topic}"
  while ((SECONDS < deadline)); do
    if timeout 4 ros2 topic echo --once --no-daemon --qos-reliability best_effort \
      "${topic}" ${type:+"${type}"} >/dev/null 2>&1; then
      return 0
    fi
  done
  echo "[ERRO] Nenhum dado real recebido em ${topic}." >&2
  return 1
}

for topic in "${required[@]}"; do
  wait_for_message "${topic}" "${required_type[${topic}]:-}"
done

mapfile -t advertised < <(ros2 topic list --no-daemon)
declare -A available=()
for topic in "${advertised[@]}"; do
  available["${topic}"]=1
done

declare -A selected=()
declare -a topics=()
for topic in "${candidates[@]}"; do
  if [[ -n "${available[${topic}]:-}" && -z "${selected[${topic}]:-}" ]]; then
    selected["${topic}"]=1
    topics+=("${topic}")
  fi
done

if ((${#topics[@]} == 0)); then
  echo "Nenhum topico disponivel para gravacao." >&2
  exit 3
fi

if [[ "${ONLY_EXTRA_TOPICS}" == "true" ]]; then
  echo "[REC] Topicos manuais (BAG_TOPICS_ONLY=true)"
else
  echo "[REC] Sensores: ${SENSOR_SET}"
  [[ -n "${EXTRA_TOPICS}" ]] && echo "[REC] Topicos extra: ${EXTRA_TOPICS}"
fi
echo "[REC] Saida: ${OUTPUT_PATH}"
printf '[REC] Topico: %s\n' "${topics[@]}"
echo "[REC] Ctrl+C encerra e finaliza o MCAP."

START_TIME_UTC="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"

set +e
ros2 bag record \
  --storage mcap \
  --output "${OUTPUT_PATH}" \
  --max-cache-size "${MAX_CACHE_SIZE}" \
  --max-bag-size "${MAX_BAG_SIZE}" \
  ${STORAGE_CONFIG_FILE:+--storage-config-file "${STORAGE_CONFIG_FILE}"} \
  "${topics[@]}" &
record_pid=$!
trap 'kill -INT "${record_pid}" 2>/dev/null' INT TERM

timer_pid=""
if [[ -n "${BAG_DURATION_SEC:-}" ]]; then
  ( sleep "${BAG_DURATION_SEC}"; kill -INT "${record_pid}" 2>/dev/null ) &
  timer_pid=$!
fi

wait "${record_pid}"
status=$?
[[ -n "${timer_pid}" ]] && kill "${timer_pid}" 2>/dev/null
trap - INT TERM
set -e

END_TIME_UTC="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"

if [[ -e "${OUTPUT_PATH}" ]]; then
  python3 "${GENERATE_METADATA}" \
    --output-path "${OUTPUT_PATH}" \
    --session-name "${BAG_NAME}" \
    --sensor-groups "$([[ "${ONLY_EXTRA_TOPICS}" == "true" ]] && echo "" || echo "${SENSOR_SET_CSV}")" \
    --extra-topics "${EXTRA_TOPICS// /,}" \
    --topics-only "${ONLY_EXTRA_TOPICS}" \
    --start-time "${START_TIME_UTC}" \
    --end-time "${END_TIME_UTC}" \
    --operator "${MOBI_OPERATOR:-}" \
    --location "${MOBI_LOCATION:-}" \
    --conditions "${MOBI_CONDITIONS:-}" \
    --notes "${MOBI_NOTES:-}" \
    --git-commit "${MOBI_GIT_COMMIT:-}" \
    --git-dirty "${MOBI_GIT_DIRTY:-}" \
    --config-fingerprint "${MOBI_CONFIG_FINGERPRINT:-}" \
    || echo "[AVISO] metadata.json/README.md nao gerados (bag continua valida)" >&2
fi

if [[ -n "${HOST_UID:-}" && -n "${HOST_GID:-}" && -e "${OUTPUT_PATH}" ]]; then
  chown -R "${HOST_UID}:${HOST_GID}" "${OUTPUT_PATH}" 2>/dev/null || true
fi
exit "${status}"
