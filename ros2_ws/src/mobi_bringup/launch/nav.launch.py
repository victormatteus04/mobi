"""Navegacao autonoma do Mobi (Nav2) sobre o mapa do RTAB-Map.

Pre-requisitos no ar: ouster, description, slam em modo localizacao
(SLAM_LOCALIZATION=true) e base-bridge/rosbridge/mux para chegar na base.

Cadeia de velocidade (mesmos remapeamentos do nav2_bringup/navigation_launch):
  controller/behavior -> cmd_vel_nav -> velocity_smoother -> cmd_vel_smoothed
  -> collision_monitor -> /cmd_vel -> mobi_base_bridge -> ROS 1 -> mobi_cmd_mux

So os nos necessarios para a BT padrao (sem docking/route/waypoints): menos
pontos de falha na ativacao do lifecycle.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

LIFECYCLE_NODES = [
    'controller_server',
    'planner_server',
    'behavior_server',
    'velocity_smoother',
    'collision_monitor',
    'bt_navigator',
]


def generate_launch_description():
    params_file = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')
    params = [params_file, {'use_sim_time': use_sim_time}]
    tf_remaps = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
    to_smoother = tf_remaps + [('cmd_vel', 'cmd_vel_nav')]

    def nav2_node(package, executable, remappings=tf_remaps):
        return Node(package=package, executable=executable, name=executable,
                    output='screen', parameters=params, remappings=remappings)

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                get_package_share_directory('mobi_bringup'), 'config', 'nav2_params.yaml')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),

        Node(package='mobi_bringup', executable='obstacle_cloud.py', name='obstacle_cloud',
             output='screen', parameters=[{'use_sim_time': use_sim_time}]),

        nav2_node('nav2_controller', 'controller_server', to_smoother),
        nav2_node('nav2_planner', 'planner_server'),
        nav2_node('nav2_behaviors', 'behavior_server', to_smoother),
        nav2_node('nav2_bt_navigator', 'bt_navigator'),
        nav2_node('nav2_velocity_smoother', 'velocity_smoother', to_smoother),
        nav2_node('nav2_collision_monitor', 'collision_monitor'),

        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_navigation', output='screen',
             parameters=[{'use_sim_time': use_sim_time, 'autostart': True,
                          'node_names': LIFECYCLE_NODES}]),
    ])
