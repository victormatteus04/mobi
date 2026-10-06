# Imagem ROS 2 Jazzy unica da stack de mapeamento/navegacao do Mobi.
#
# Quase tudo vem do apt com binarios amd64 e arm64, entao o mesmo Dockerfile
# serve para o notebook e para a Jetson Thor. Excecao: o driver do Ouster (ver
# abaixo). O workspace do proprio robo (ros2_ws) e compilado por ultimo.
FROM ros:jazzy-ros-base-noble

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y --no-install-recommends \
      git \
      ros-jazzy-rmw-zenoh-cpp \
      ros-jazzy-rtabmap-ros \
      ros-jazzy-robot-state-publisher \
      ros-jazzy-xacro \
      ros-jazzy-rosbag2-storage-mcap \
      ros-jazzy-rviz2 \
      ros-jazzy-navigation2 \
      python3-pip \
      python3-autobahn \
      python3-twisted \
      python3-openssl \
      python3-service-identity \
    && rm -rf /var/lib/apt/lists/*

# roslibpy (cliente rosbridge do mobi_base_bridge) nao tem pacote apt. Suas
# dependencias vem do apt acima; --no-deps evita o pip trocar libs do sistema.
RUN pip3 install --no-cache-dir --break-system-packages --no-deps roslibpy==2.1.0

# ouster-ros do fonte em tag fixa: o binario ros-jazzy-ouster-ros 0.15.1 aborta
# com "Field 'WINDOW' not found in LidarScan" no nosso OS-0-128 (fw 2.5.3,
# perfil RNG19_RFL8_SIG16_NIR16) - https://github.com/ouster-lidar/ouster-ros/issues/577
# A 0.14.2 foi confirmada na issue com o mesmo sensor/firmware. Voltar ao apt
# quando a issue for resolvida.
ARG OUSTER_ROS_REF=jazzy-0.14.2
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    git clone --depth 1 --branch "${OUSTER_ROS_REF}" \
      https://github.com/ouster-lidar/ouster-ros.git /opt/ouster_ws/src/ouster-ros \
    && apt-get update \
    && rosdep update --rosdistro jazzy \
    && rosdep install --from-paths /opt/ouster_ws/src --ignore-src -r -y --rosdistro jazzy \
    && rm -rf /var/lib/apt/lists/* \
    && cd /opt/ouster_ws \
    && source /opt/ros/jazzy/setup.bash \
    && colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && rm -rf build log

COPY ros2_ws/src /ros2_ws/src
WORKDIR /ros2_ws
RUN source /opt/ouster_ws/install/setup.bash \
    && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release

COPY docker/jazzy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
