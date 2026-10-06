cmake_minimum_required(VERSION 3.8)
project(mobi_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config rviz
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS scripts/obstacle_cloud.py scripts/check_lidar_yaw.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
