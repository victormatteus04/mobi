#!/usr/bin/env python3
"""Confere o yaw de montagem do Ouster (ouster_yaw no URDF) dirigindo para frente.

Compara a odometria das rodas (/base/odom, vinda da base ROS 1) com a do ICP
(/rtabmap/icp_odom). Andando reto para frente, a velocidade do ICP expressa em
base_link deveria apontar para +x. O angulo medido e o erro do yaw no URDF:
    ouster_yaw_correto = ouster_yaw_atual - erro

Uso: ./mobi.sh check-yaw   (dirija RETO PARA FRENTE ~1-2 m durante a coleta)
"""

import math
import sys
import time

import rclpy
from nav_msgs.msg import Odometry

DURATION_S = 20.0
MIN_WHEEL_VX = 0.05
MIN_SAMPLES = 15


def main():
    rclpy.init()
    node = rclpy.create_node('check_lidar_yaw')
    state = {'wheel_vx': 0.0, 'wheel_stamp': 0.0, 'sum_x': 0.0, 'sum_y': 0.0, 'n': 0}

    def on_wheel(msg):
        state['wheel_vx'] = msg.twist.twist.linear.x
        state['wheel_stamp'] = time.monotonic()

    def on_icp(msg):
        fresh = time.monotonic() - state['wheel_stamp'] < 0.2
        if fresh and state['wheel_vx'] > MIN_WHEEL_VX:
            state['sum_x'] += msg.twist.twist.linear.x
            state['sum_y'] += msg.twist.twist.linear.y
            state['n'] += 1

    node.create_subscription(Odometry, '/base/odom', on_wheel, 50)
    node.create_subscription(Odometry, '/rtabmap/icp_odom', on_icp, 10)
    print(f'Coletando {DURATION_S:.0f} s: dirija RETO PARA FRENTE agora...', flush=True)
    end = time.monotonic() + DURATION_S
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.shutdown()

    if state['n'] < MIN_SAMPLES:
        print(f'Poucas amostras andando para frente ({state["n"]}). Verifique se /base/odom '
              'e /rtabmap/icp_odom estao publicando e repita dirigindo para frente.')
        return 1
    error_deg = math.degrees(math.atan2(state['sum_y'], state['sum_x']))
    print(f'Amostras: {state["n"]}. Direcao do movimento segundo o ICP: {error_deg:+.0f} graus '
          '(0 = URDF correto).')
    if abs(error_deg) < 15:
        print('OK: ouster_yaw do URDF esta coerente.')
    else:
        print(f'Ajuste no URDF: ouster_yaw = (valor atual) - ({error_deg:+.0f} graus).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
