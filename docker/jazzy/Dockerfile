# Imagem ROS 2 Jazzy unica da stack de mapeamento/navegacao do Mobi.
#
# Todos os pacotes vem do apt com binarios amd64 e arm64, entao o mesmo
# Dockerfile serve para o notebook e para a Jetson Thor sem compilar driver
# nenhum. So o workspace do proprio robo (ros2_ws) e compilado aqui.
FROM ros:jazzy-ros-base-noble

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-zenoh-cpp \
      ros-jazzy-ouster-ros \
      ros-jazzy-rtabmap-ros \
      ros-jazzy-robot-state-publisher \
      ros-jazzy-xacro \
      ros-jazzy-rosbag2-storage-mcap \
    && rm -rf /var/lib/apt/lists/*

COPY ros2_ws/src /ros2_ws/src
WORKDIR /ros2_ws
RUN source /opt/ros/jazzy/setup.bash \
    && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release

COPY docker/jazzy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
