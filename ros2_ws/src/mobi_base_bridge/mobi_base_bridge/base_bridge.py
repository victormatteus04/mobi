"""Ponte minima ROS 2 (Jazzy) <-> base ROS 1 (Noetic) do Mobi via rosbridge.

ROS 2 -> ROS 1:  /cmd_vel (saida do Nav2)  -> /cmd_vel_nav (entra no mobi_cmd_mux,
                 que so repassa a base com o homem-morto segurado)
ROS 1 -> ROS 2:  /odom            -> /base/odom   (frame renomeado para wheel_odom:
                                                   "odom" e da odometria ICP)
                 /battery_voltage -> /base/battery_voltage
                 /cmd_vel_source  -> /base/cmd_vel_source (joy | nav | idle)

Se o websocket cair por mais de `reconnect_timeout` s, o processo sai com erro e
o container reinicia (restart: unless-stopped) - mais previsivel do que tentar
reassinar topicos numa conexao reaberta.
"""

import sys
import time

import rclpy
import roslibpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rosidl_runtime_py import message_to_ordereddict, set_message_fields
from std_msgs.msg import Float32, String

# (topico ROS 1, tipo ROS 1, topico ROS 2, tipo ROS 2)
ROS1_TO_ROS2 = [
    ('/odom', 'nav_msgs/Odometry', '/base/odom', Odometry),
    ('/battery_voltage', 'std_msgs/Float32', '/base/battery_voltage', Float32),
    ('/cmd_vel_source', 'std_msgs/String', '/base/cmd_vel_source', String),
]
ROS2_TO_ROS1 = [
    ('/cmd_vel', Twist, '/cmd_vel_nav', 'geometry_msgs/Twist'),
]


def ros1_dict_to_ros2(value):
    """Ajusta um dict de mensagem ROS 1 (rosbridge) para os campos ROS 2."""
    if isinstance(value, list):
        return [ros1_dict_to_ros2(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'secs', 'nsecs'}:
        return {'sec': value['secs'], 'nanosec': value['nsecs']}
    return {k: ros1_dict_to_ros2(v) for k, v in value.items() if k != 'seq'}


class BaseBridge(Node):
    def __init__(self):
        super().__init__('base_bridge')
        host = self.declare_parameter('rosbridge_host', '127.0.0.1').value
        port = self.declare_parameter('rosbridge_port', 9090).value
        self.wheel_odom_frame = self.declare_parameter('wheel_odom_frame', 'wheel_odom').value
        self.reconnect_timeout = self.declare_parameter('reconnect_timeout', 5.0).value

        self.ros1 = roslibpy.Ros(host=host, port=port)
        self.get_logger().info(f'Conectando ao rosbridge ws://{host}:{port} ...')
        self.ros1.run(timeout=10)  # levanta excecao se nao conectar
        self.get_logger().info('Conectado ao rosbridge.')
        self.disconnected_since = None

        for ros1_name, ros1_type, ros2_name, ros2_type in ROS1_TO_ROS2:
            self.bridge_up(ros1_name, ros1_type, ros2_name, ros2_type)
        self.down_topics = []
        for ros2_name, ros2_type, ros1_name, ros1_type in ROS2_TO_ROS1:
            self.down_topics.append(self.bridge_down(ros2_name, ros2_type, ros1_name, ros1_type))

        self.create_timer(1.0, self.check_connection)

    def bridge_up(self, ros1_name, ros1_type, ros2_name, ros2_type):
        publisher = self.create_publisher(ros2_type, ros2_name, 10)

        def on_ros1_message(message):
            msg = ros2_type()
            set_message_fields(msg, ros1_dict_to_ros2(message))
            if ros2_type is Odometry:
                msg.header.frame_id = self.wheel_odom_frame
            publisher.publish(msg)

        topic = roslibpy.Topic(self.ros1, ros1_name, ros1_type, queue_length=1)
        topic.subscribe(on_ros1_message)
        self.get_logger().info(f'ROS 1 {ros1_name} -> ROS 2 {ros2_name}')

    def bridge_down(self, ros2_name, ros2_type, ros1_name, ros1_type):
        topic = roslibpy.Topic(self.ros1, ros1_name, ros1_type, queue_length=1)
        topic.advertise()

        def on_ros2_message(msg):
            if self.ros1.is_connected:
                topic.publish(roslibpy.Message(dict(message_to_ordereddict(msg))))

        self.create_subscription(ros2_type, ros2_name, on_ros2_message, 10)
        self.get_logger().info(f'ROS 2 {ros2_name} -> ROS 1 {ros1_name}')
        return topic

    def check_connection(self):
        if self.ros1.is_connected:
            self.disconnected_since = None
            return
        now = time.monotonic()
        if self.disconnected_since is None:
            self.disconnected_since = now
            self.get_logger().warn('rosbridge desconectado.')
        elif now - self.disconnected_since > self.reconnect_timeout:
            self.get_logger().error('rosbridge fora do ar; saindo para o container reiniciar.')
            raise SystemExit(1)

    def stop(self):
        for topic in self.down_topics:
            if self.ros1.is_connected:
                topic.publish(roslibpy.Message(dict(message_to_ordereddict(Twist()))))
        self.ros1.terminate()


def main():
    rclpy.init()
    node = None
    exit_code = 0
    try:
        node = BaseBridge()
        rclpy.spin(node)
    except SystemExit as exc:
        exit_code = exc.code or 0
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # falha ao conectar no rosbridge, etc.
        print(f'[base_bridge] erro: {exc}', file=sys.stderr)
        exit_code = 1
    finally:
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
