#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"

load_env() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
}
load_env

normalize_sensors() {
  local value="${1:-${MOBI_SENSOR_SET:-ouster,d435i,t265}}"
  value="${value//,/ }"
  echo "${value}"
}

validate_sensors() {
  local sensor
  for sensor in $1; do
    case "${sensor}" in
      base|ouster|d435i|t265|d455) ;;
      *) echo "Sensor desconhecido: ${sensor}" >&2; exit 2 ;;
    esac
  done
}

discover_ouster() {
  local discovered=""
  if command -v avahi-browse >/dev/null 2>&1; then
    discovered="$(timeout 6 avahi-browse -rtp _roger._tcp 2>/dev/null \
      | awk -F';' '$1 == "=" && $8 ~ /^[0-9]+\./ {print $8; exit}')"
  fi
  if [[ -n "${discovered}" ]]; then
    export OUSTER_HOSTNAME="${discovered}"
    echo "[Ouster] Detectado em ${OUSTER_HOSTNAME}"
  else
    export OUSTER_HOSTNAME="${OUSTER_HOSTNAME:-169.254.216.20}"
    echo "[Ouster] Usando ${OUSTER_HOSTNAME}"
  fi
}

needs_realsense() {
  [[ " $1 " == *" d435i "* || " $1 " == *" t265 "* || " $1 " == *" d455 "* ]]
}

sensor_services() {
  local sensor
  for sensor in $1; do
    [[ "${sensor}" == base ]] || printf '%s\n' "${sensor}"
  done
}

git_commit() {
  git -C "${PROJECT_DIR}" rev-parse HEAD 2>/dev/null || echo ""
}

git_dirty() {
  if ! git -C "${PROJECT_DIR}" rev-parse --git-dir >/dev/null 2>&1; then
    echo ""
    return
  fi
  if git -C "${PROJECT_DIR}" diff --quiet -- . ':!bags' ':!.env' 2>/dev/null \
      && git -C "${PROJECT_DIR}" diff --cached --quiet -- . ':!bags' ':!.env' 2>/dev/null; then
    echo "false"
  else
    echo "true"
  fi
}

# Fallback para quando /mobi nao for um repo git (nao deveria acontecer, mas
# generate_metadata.py sempre recebe algo identificando a config usada).
config_fingerprint() {
  local files=(
    docker-compose.yml .env
    config/topics.yaml config/fastdds-udp-only.xml config/mcap-compression.yaml
    ros2_ws/src/mobi_description/urdf/mobi.urdf.xacro
  )
  files+=(scripts/*.sh Dockerfile.*)
  cat "${files[@]}" 2>/dev/null | sha256sum | cut -d' ' -f1
}

ensure_realsense_base() {
  if ! docker image inspect realsense-d455-t265-a2m12-ros2:latest >/dev/null 2>&1; then
    cat >&2 <<'EOF'
Imagem base das RealSense ausente.
Construa a implementacao de referencia primeiro:
  docker build -t realsense-d455-t265-a2m12-ros2 ../Creation_data
EOF
    exit 3
  fi
}

ensure_realsense_image() {
  ensure_realsense_base
  if ! docker image inspect mobi/ros2-realsense:humble >/dev/null 2>&1; then
    echo "[BUILD] Criando camada Mobi sobre a imagem RealSense local..."
    DOCKER_BUILDKIT=0 docker build \
      --network host \
      -f Dockerfile.realsense \
      -t mobi/ros2-realsense:humble \
      .
  fi
}

command_name="${1:-help}"
shift || true

case "${command_name}" in
  network)
    exec ./scripts/setup-ouster-network.sh
    ;;
  build)
    ensure_realsense_image
    docker compose build ros-master ros1-bridge ouster description
    ;;
  up)
    sensors="$(normalize_sensors "${1:-}")"
    validate_sensors "${sensors}"
    if needs_realsense "${sensors}"; then ensure_realsense_image; fi
    docker compose up -d zenoh-router ros-master rosserial joystick rosbridge \
      base-bridge description
    if [[ " ${sensors} " == *" ouster "* ]]; then
      discover_ouster
    fi
    mapfile -t services < <(sensor_services "${sensors}")
    if ((${#services[@]})); then
      docker compose up -d "${services[@]}"
    fi
    docker compose ps
    ;;
  stop)
    sensors="$(normalize_sensors "${1:-}")"
    validate_sensors "${sensors}"
    mapfile -t services < <(sensor_services "${sensors}")
    if ((${#services[@]})); then
      docker compose stop "${services[@]}"
    fi
    ;;
  check)
    sensors="$(normalize_sensors "${1:-}")"
    validate_sensors "${sensors}"
    ensure_realsense_image
    docker compose run --rm --no-deps \
      -e "SENSOR_WAIT_TIMEOUT=${SENSOR_WAIT_TIMEOUT:-60}" \
      bag-recorder /mobi/check-sensors.sh "${sensors}"
    ;;
  devices)
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder /mobi/run-realsense.sh devices
    echo
    discover_ouster
    curl -fsS --max-time 5 \
      "http://${OUSTER_HOSTNAME}/api/v1/sensor/metadata/sensor_info" || true
    echo
    ;;
  bag)
    name="${1:-sessao_$(date +%Y%m%d_%H%M%S)}"
    sensors="$(normalize_sensors "${2:-base,${MOBI_SENSOR_SET:-ouster,d435i,t265}}")"
    validate_sensors "${sensors}"
    ensure_realsense_image
    mkdir -p bags
    docker compose run --rm --no-deps \
      -e "BAG_SENSOR_SET=${sensors}" \
      -e "BAG_TOPICS=${BAG_TOPICS:-}" \
      -e "BAG_TOPICS_ONLY=${BAG_TOPICS_ONLY:-false}" \
      -e "BAG_DURATION_SEC=${BAG_DURATION_SEC:-}" \
      -e "BAG_STORAGE_CONFIG=${BAG_STORAGE_CONFIG-/etc/mobi/mcap-compression.yaml}" \
      -e "MOBI_OPERATOR=${MOBI_OPERATOR:-}" \
      -e "MOBI_LOCATION=${MOBI_LOCATION:-}" \
      -e "MOBI_CONDITIONS=${MOBI_CONDITIONS:-}" \
      -e "MOBI_NOTES=${MOBI_NOTES:-}" \
      -e "MOBI_GIT_COMMIT=$(git_commit)" \
      -e "MOBI_GIT_DIRTY=$(git_dirty)" \
      -e "MOBI_CONFIG_FINGERPRINT=$(config_fingerprint)" \
      -e "HOST_UID=$(id -u)" \
      -e "HOST_GID=$(id -g)" \
      bag-recorder /mobi/record-bag.sh "${name}" "${sensors}"
    ;;
  bag-info)
    name="${1:?Uso: ./mobi.sh bag-info NOME}"
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder \
      ros2 bag info "/bags/${name}"
    ;;
  extract)
    name="${1:?Uso: ./mobi.sh extract NOME [--images-format png|jpg] [--topics t1,t2]}"
    shift || true
    ensure_realsense_image
    docker compose run --rm --no-deps \
      -e "HOST_UID=$(id -u)" -e "HOST_GID=$(id -g)" \
      bag-recorder bash -c "
        python3 /mobi/extract_bag.py --bag-path /bags/${name} \"\$@\" && \
        chown -R $(id -u):$(id -g) /bags/${name}/extracted
      " -- "$@"
    ;;
  validate)
    name="${1:?Uso: ./mobi.sh validate NOME}"
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder bash -c "
      python3 /mobi/validate_bag.py --bag-path /bags/${name} && \
      chown $(id -u):$(id -g) /bags/${name}/validation_report.json
    "
    ;;
  preview)
    name="${1:?Uso: ./mobi.sh preview NOME}"
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder bash -c "
      python3 /mobi/preview_bag.py --bag-path /bags/${name} && \
      chown -R $(id -u):$(id -g) /bags/${name}/preview
    "
    ;;
  catalog)
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder bash -c "
      python3 /mobi/build_catalog.py --bags-dir /bags && \
      chown $(id -u):$(id -g) /bags/index.html /bags/catalog.json
    "
    ;;
  process)
    name="${1:?Uso: ./mobi.sh process NOME}"
    echo "=== [1/4] extract ${name} ==="
    "${BASH_SOURCE[0]}" extract "${name}"
    echo "=== [2/4] validate ${name} ==="
    "${BASH_SOURCE[0]}" validate "${name}"
    echo "=== [3/4] preview ${name} ==="
    "${BASH_SOURCE[0]}" preview "${name}"
    echo "=== [4/4] catalog ==="
    "${BASH_SOURCE[0]}" catalog
    echo "=== process ${name}: concluido ==="
    ;;
  play)
    name="${1:?Uso: ./mobi.sh play NOME}"
    shift || true
    ensure_realsense_image
    docker compose run --rm --no-deps bag-recorder /mobi/play-bag.sh "${name}" "$@"
    ;;
  map)
    # Mapa novo: SLAM em modo mapeamento gravando em maps/NOME.db.
    name="${1:?Uso: ./mobi.sh map NOME}"
    if [[ -e "maps/${name}.db" ]]; then
      echo "maps/${name}.db ja existe. Use outro nome (ou apague o arquivo)." >&2
      exit 2
    fi
    mkdir -p maps
    docker compose stop nav slam 2>/dev/null || true
    SLAM_MAP_NAME="${name}" SLAM_DELETE_DB=true SLAM_LOCALIZATION=false \
      SLAM_DESKEWING="${SLAM_DESKEWING:-true}" \
      docker compose up -d --force-recreate zenoh-router description slam
    echo "Mapeando em maps/${name}.db. Para salvar: ./mobi.sh slam-stop"
    ;;
  localize)
    # Localizacao num mapa salvo (nao altera o mapa). Pre-requisito do Nav2.
    name="${1:?Uso: ./mobi.sh localize NOME}"
    if [[ ! -e "maps/${name}.db" ]]; then
      echo "maps/${name}.db nao existe. Mapas disponiveis:" >&2
      ls maps/*.db 2>/dev/null >&2 || true
      exit 2
    fi
    docker compose stop slam 2>/dev/null || true
    SLAM_MAP_NAME="${name}" SLAM_DELETE_DB=false SLAM_LOCALIZATION=true \
      SLAM_DESKEWING="${SLAM_DESKEWING:-true}" \
      docker compose up -d --force-recreate zenoh-router description slam
    echo "Localizando em maps/${name}.db. Depois: ./mobi.sh nav"
    ;;
  nav)
    docker compose up -d --force-recreate nav
    echo "Nav2 no ar. Destino: '2D Goal Pose' no RViz. O robo so anda com L1 SEGURADO."
    ;;
  check-yaw)
    # Precisa de: up (base-bridge) + ouster + slam/localize rodando.
    docker compose exec slam /entrypoint.sh \
      ros2 run mobi_bringup check_lidar_yaw.py
    ;;
  slam-stop)
    # Parar o slam grava o banco do mapa.
    docker compose stop nav slam
    ls -la maps/
    ;;
  slam)
    # Ao vivo: precisa do Ouster no ar (./mobi.sh up ouster).
    docker compose up -d zenoh-router description slam
    docker compose logs -f slam
    ;;
  slam-bag)
    # Offline: roda o SLAM sobre o Ouster gravado numa bag, em tempo simulado.
    # O mapa vai para maps/NOME.db (recriado a cada execucao).
    name="${1:?Uso: ./mobi.sh slam-bag NOME [args extras do ros2 bag play]}"
    shift || true
    mkdir -p maps
    SLAM_USE_SIM_TIME=true SLAM_DELETE_DB=true SLAM_MAP_NAME="${name}" \
      docker compose up -d --force-recreate zenoh-router description slam player
    docker compose exec player /entrypoint.sh ros2 bag play "/bags/${name}" --clock 100 \
      --topics /ouster/points /ouster/imu /tf_static "$@"
    echo "Bag concluida. Mapa em maps/${name}.db (pare com: docker compose stop slam)"
    ;;
  status)
    docker compose ps -a
    ;;
  logs)
    docker compose logs -f --tail=100 "$@"
    ;;
  viz)
    docker compose build gui
    docker compose up -d gui
    docker compose logs -f gui
    ;;
  dashboard)
    ensure_realsense_image
    DOCKER_BUILDKIT=0 docker build --network host \
      -f Dockerfile.dashboard -t mobi/ros2-dashboard:humble .
    MOBI_GIT_COMMIT="$(git_commit)" MOBI_GIT_DIRTY="$(git_dirty)" \
      MOBI_CONFIG_FINGERPRINT="$(config_fingerprint)" docker compose up -d dashboard
    echo "Painel em http://localhost:${DASHBOARD_PORT:-8080}"
    ;;
  rqt)
    docker compose build gui
    docker compose run --rm --no-deps gui ros2 run rqt_image_view rqt_image_view
    ;;
  down)
    COMPOSE_PROFILES="ouster,t265,d435i,d455,tools,gui,dashboard,slam,nav,legacy-humble" docker compose down
    ;;
  help|*)
    cat <<'EOF'
Uso:
  ./mobi.sh network
  ./mobi.sh build
  ./mobi.sh up [ouster,d435i,t265,d455]
  ./mobi.sh stop [ouster,d435i,t265,d455]
  ./mobi.sh check [base,ouster,d435i,t265,d455]
  ./mobi.sh devices
  ./mobi.sh bag [NOME] [base,ouster,d435i,t265,d455]
  ./mobi.sh bag-info NOME
  ./mobi.sh extract NOME [--images-format png|jpg] [--topics /t1,/t2]
  ./mobi.sh validate NOME
  ./mobi.sh preview NOME
  ./mobi.sh catalog
  ./mobi.sh process NOME    # extract + validate + preview + catalog, em sequencia
  ./mobi.sh play NOME [args extras do ros2 bag play]

Selecao manual de topicos na gravacao (alem ou no lugar dos grupos acima):
  BAG_TOPICS="/topico1,/topico2" ./mobi.sh bag NOME [grupos]
  BAG_TOPICS="/topico1,/topico2" BAG_TOPICS_ONLY=true ./mobi.sh bag NOME

Duracao fixa (encerra sozinha, sem precisar de Ctrl+C):
  BAG_DURATION_SEC=10 ./mobi.sh bag NOME [grupos]

Metadados da sessao (viram metadata.json + README.md dentro da bag):
  MOBI_OPERATOR="fulano" MOBI_LOCATION="predio X" MOBI_CONDITIONS="indoor" \
    MOBI_NOTES="teste de corredor" ./mobi.sh bag NOME [grupos]
  ./mobi.sh status
  ./mobi.sh logs [SERVICOS...]
  ./mobi.sh map NOME         # mapa novo -> maps/NOME.db (nao sobrescreve)
  ./mobi.sh localize NOME    # localizacao num mapa salvo (pre-requisito do nav)
  ./mobi.sh nav              # Nav2 (robo so anda com L1/LB segurado)
  ./mobi.sh slam-stop        # para nav + slam (grava o mapa)
  ./mobi.sh check-yaw        # confere a montagem do Ouster (dirija reto p/ frente)
  ./mobi.sh slam             # SLAM ao vivo com as variaveis SLAM_* do ambiente
  ./mobi.sh slam-bag NOME    # SLAM offline sobre o Ouster de uma bag -> maps/NOME.db
  ./mobi.sh viz              # RViz2 em container (TF, RobotModel, PointCloud2, imagens, pose)
  ./mobi.sh rqt              # rqt_image_view avulso, em container
  ./mobi.sh dashboard        # painel web: estado dos sensores + gravar bag sem terminal
  ./mobi.sh down
EOF
    ;;
esac
