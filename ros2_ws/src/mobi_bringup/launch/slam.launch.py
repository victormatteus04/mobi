"""SLAM 3D so com o Ouster: icp_odometry (odom -> base_link) + rtabmap (map -> odom).

Adaptado de rtabmap_examples/launch/lidar3d.launch.py (introlab/rtabmap_ros).
Os parametros ajustaveis ficam em config/slam_icp.yaml; aqui so entra o que
muda por execucao (tempo simulado, modo localizacao, banco de dados).

Uso:
  ros2 launch mobi_bringup slam.launch.py                          # mapeamento ao vivo
  ros2 launch mobi_bringup slam.launch.py use_sim_time:=true       # com ros2 bag play --clock
  ros2 launch mobi_bringup slam.launch.py localization:=true       # reusa o mapa salvo
  ros2 launch mobi_bringup slam.launch.py delete_db:=true          # comeca um mapa do zero
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def is_true(context, name):
    return LaunchConfiguration(name).perform(context).lower() == 'true'


def launch_setup(context):
    params_file = LaunchConfiguration('params_file')
    use_sim_time = {'use_sim_time': is_true(context, 'use_sim_time')}
    localization = is_true(context, 'localization')

    rtabmap_overrides = {'database_path': LaunchConfiguration('database_path')}
    if localization:
        rtabmap_overrides['Mem/IncrementalMemory'] = 'false'
        rtabmap_overrides['Mem/InitWMWithAllNodes'] = 'true'

    # Sem "-d" o rtabmap continua o banco existente (mapeamento multi-sessao).
    rtabmap_arguments = ['-d'] if is_true(context, 'delete_db') and not localization else []

    remappings = [
        ('scan_cloud', LaunchConfiguration('lidar_topic')),
        ('odom', 'icp_odom'),
        ('imu', 'imu_not_used'),
    ]

    return [
        Node(
            package='rtabmap_odom', executable='icp_odometry', name='icp_odometry',
            namespace='rtabmap', output='screen',
            parameters=[params_file, use_sim_time,
                        {'deskewing': is_true(context, 'deskewing')}],
            remappings=remappings,
        ),
        Node(
            package='rtabmap_slam', executable='rtabmap', name='rtabmap',
            namespace='rtabmap', output='screen',
            parameters=[params_file, use_sim_time, rtabmap_overrides],
            remappings=remappings,
            arguments=rtabmap_arguments,
        ),
    ]


def generate_launch_description():
    default_params = os.path.join(
        get_package_share_directory('mobi_bringup'), 'config', 'slam_icp.yaml')

    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_params,
                              description='YAML com os parametros do icp_odometry e do rtabmap.'),
        DeclareLaunchArgument('use_sim_time', default_value='false',
                              description='true ao reproduzir bag com --clock.'),
        DeclareLaunchArgument('lidar_topic', default_value='/ouster/points'),
        DeclareLaunchArgument('localization', default_value='false',
                              description='true: nao altera o mapa, so se localiza nele.'),
        DeclareLaunchArgument('database_path', default_value='/maps/rtabmap.db'),
        DeclareLaunchArgument('delete_db', default_value='false',
                              description='true: apaga o banco ao iniciar (mapa novo).'),
        DeclareLaunchArgument('deskewing', default_value='false',
                              description='Exige nuvem com tempo por ponto (Ouster point_type '
                                          'original/native); xyzir nao tem.'),
        OpaqueFunction(function=launch_setup),
    ])
