#!/usr/bin/env python3
"""Nuvem de obstaculos para o Nav2 a partir da nuvem crua do Ouster.

Remove o proprio robo (coluna da caixa + mastro em base_link), o chao e o que
estiver acima da altura util, e reduz por voxel. Diferente do scan filtrado do
ICP, nao tem alcance minimo: obstaculos colados no robo continuam visiveis.

A saida fica no frame do sensor (os_lidar), para o costmap fazer o raytracing
de limpeza a partir da posicao real do LiDAR.
"""

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from tf2_ros import Buffer, TransformListener


def quat_to_matrix(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


class ObstacleCloud(Node):
    def __init__(self):
        super().__init__('obstacle_cloud')
        p = self.declare_parameter
        self.base_frame = p('base_frame', 'base_link').value
        self.min_z = p('min_z', 0.10).value          # abaixo disso e chao
        self.max_z = p('max_z', 1.20).value          # acima disso nao bate no robo
        self.max_range = p('max_range', 8.0).value
        self.voxel = p('voxel_size', 0.05).value
        # Coluna do robo em base_link (caixa 0.70 x 0.50 + mastro), com folga.
        self.body_x = (p('body_min_x', -0.40).value, p('body_max_x', 0.40).value)
        self.body_y = (p('body_min_y', -0.30).value, p('body_max_y', 0.30).value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.sensor_to_base = None  # (R, t), transformacao estatica

        self.pub = self.create_publisher(
            PointCloud2, p('output_topic', '/mobi/obstacles').value, qos_profile_sensor_data)
        self.create_subscription(
            PointCloud2, p('input_topic', '/ouster/points').value,
            self.on_cloud, qos_profile_sensor_data)

    def lookup_sensor_to_base(self, sensor_frame):
        try:
            tf = self.tf_buffer.lookup_transform(
                self.base_frame, sensor_frame, Time(), timeout=Duration(seconds=0.0))
        except Exception as exc:  # TF estatico ainda nao chegou
            self.get_logger().warn(f'Sem TF {self.base_frame} <- {sensor_frame}: {exc}',
                                   throttle_duration_sec=5.0)
            return None
        q, t = tf.transform.rotation, tf.transform.translation
        rot = quat_to_matrix(q.x, q.y, q.z, q.w)
        self.get_logger().info(f'TF {self.base_frame} <- {sensor_frame} obtido.')
        return rot, np.array([t.x, t.y, t.z])

    def on_cloud(self, msg):
        if self.sensor_to_base is None:
            self.sensor_to_base = self.lookup_sensor_to_base(msg.header.frame_id)
            if self.sensor_to_base is None:
                return
        rot, trans = self.sensor_to_base

        pts = point_cloud2.read_points_numpy(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        rng2 = np.einsum('ij,ij->i', pts, pts)
        pts = pts[(rng2 > 1e-4) & (rng2 < self.max_range ** 2)]   # (0,0,0) = sem retorno

        base = pts @ rot.T + trans
        x, y, z = base[:, 0], base[:, 1], base[:, 2]
        in_body = ((x > self.body_x[0]) & (x < self.body_x[1])
                   & (y > self.body_y[0]) & (y < self.body_y[1]))
        keep = (z > self.min_z) & (z < self.max_z) & ~in_body
        pts, base = pts[keep], base[keep]

        if len(pts):
            cells = np.floor(base / self.voxel).astype(np.int64)
            keys = (cells[:, 0] * 73856093) ^ (cells[:, 1] * 19349663) ^ (cells[:, 2] * 83492791)
            _, first = np.unique(keys, return_index=True)
            pts = pts[first]

        self.pub.publish(point_cloud2.create_cloud_xyz32(msg.header, pts.astype(np.float32)))


def main():
    rclpy.init()
    node = ObstacleCloud()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
