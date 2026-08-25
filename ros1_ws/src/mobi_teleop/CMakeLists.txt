cmake_minimum_required(VERSION 3.0.2)
project(mobi_teleop)

find_package(catkin REQUIRED COMPONENTS
  geometry_msgs
  rospy
  sensor_msgs
)

catkin_package()

catkin_install_python(PROGRAMS
  scripts/mobi_joy_teleop.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
