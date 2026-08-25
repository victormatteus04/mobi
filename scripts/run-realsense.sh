#!/usr/bin/env bash
set -eo pipefail

MODEL="${1:?Uso: run-realsense.sh t265|d435i|d455|devices}"

source /opt/ros/humble/setup.bash

if [[ "${MODEL}" == "devices" ]]; then
  echo "[SDK legado: T265]"
  source /ros2_ws/install/setup.bash
  rs-enumerate-devices -s
  echo
  echo "[SDK moderno: D4xx]"
  export LD_LIBRARY_PATH="/opt/librealsense-d455/lib:${LD_LIBRARY_PATH:-}"
  /opt/librealsense-d455/bin/rs-enumerate-devices -s
  exit 0
fi

sleep "${CAMERA_START_DELAY:-0}"

serial_arguments() {
  local serial="${1:-}"
  if [[ -n "${serial}" ]]; then
    serial="${serial#_}"
    printf '%s\n' -p "serial_no:=_${serial}"
  fi
}

if [[ "${MODEL}" == "t265" ]]; then
  source /ros2_ws/install/setup.bash
  mapfile -t serial_args < <(serial_arguments "${T265_SERIAL:-}")
  exec /ros2_ws/install/lib/realsense2_camera/realsense2_camera_node \
    --ros-args \
    -r __ns:=/t265 \
    -r __node:=camera \
    -p camera_name:=t265 \
    -p device_type:=t265 \
    "${serial_args[@]}" \
    -p enable_pose:=true \
    -p pose_fps:=200 \
    -p enable_accel:=true \
    -p enable_gyro:=true \
    -p enable_fisheye1:=true \
    -p enable_fisheye2:=true \
    -p unite_imu_method:=2 \
    -p publish_odom_tf:=true \
    -p initial_reset:=false
fi

case "${MODEL}" in
  d435i)
    camera_name=d435i
    serial="${D435I_SERIAL:-}"
    device_type="${D435I_DEVICE_TYPE:-d435i}"
    profile="${D435I_PROFILE:-640x480x30}"
    enable_imu="${D435I_ENABLE_IMU:-true}"
    enable_infra="${D435I_ENABLE_INFRA:-false}"
    enable_emitter="${D435I_ENABLE_EMITTER:-false}"
    ;;
  d455)
    camera_name=d455
    serial="${D455_SERIAL:-}"
    device_type=d455
    profile="${D455_PROFILE:-640x480x30}"
    enable_imu="${D455_ENABLE_IMU:-true}"
    enable_infra="${D455_ENABLE_INFRA:-false}"
    enable_emitter="${D455_ENABLE_EMITTER:-false}"
    ;;
  *)
    echo "Modelo RealSense desconhecido: ${MODEL}" >&2
    exit 2
    ;;
esac

export AMENT_PREFIX_PATH="/d455_ws/install:/opt/ros/humble"
export CMAKE_PREFIX_PATH="/d455_ws/install:/opt/librealsense-d455:/opt/ros/humble"
export COLCON_PREFIX_PATH="/d455_ws/install"
export LD_LIBRARY_PATH="/d455_ws/install/lib:/opt/librealsense-d455/lib:/opt/ros/humble/lib:${LD_LIBRARY_PATH:-}"
export PATH="/d455_ws/install/bin:/opt/librealsense-d455/bin:/opt/ros/humble/bin:${PATH}"

mapfile -t serial_args < <(serial_arguments "${serial}")
device_args=()
if [[ -z "${serial}" ]]; then
  device_args=(-p "device_type:=${device_type}")
fi

emitter_value=0
[[ "${enable_emitter}" == "true" ]] && emitter_value=1

exec /d455_ws/install/lib/realsense2_camera/realsense2_camera_node \
  --ros-args \
  -r __ns:=/ \
  -r "__node:=${camera_name}" \
  -p "camera_name:=${camera_name}" \
  "${serial_args[@]}" \
  "${device_args[@]}" \
  -p "depth_module.depth_profile:=${profile}" \
  -p "depth_module.infra_profile:=${profile}" \
  -p "rgb_camera.color_profile:=${profile}" \
  -p enable_depth:=true \
  -p enable_color:=true \
  -p "enable_infra1:=${enable_infra}" \
  -p "enable_infra2:=${enable_infra}" \
  -p "enable_accel:=${enable_imu}" \
  -p "enable_gyro:=${enable_imu}" \
  -p unite_imu_method:=2 \
  -p align_depth.enable:=true \
  -p enable_sync:=true \
  -p "depth_module.emitter_enabled:=${emitter_value}" \
  -p initial_reset:=false
