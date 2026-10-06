#!/usr/bin/env python3
"""Unico no que publica /cmd_vel para a base Mobi.

Prioridade, avaliada a cada ciclo (output_rate):
  1. joystick: analogico fora do zero (cmd_vel_joy recente e nao nulo);
  2. navegacao: botao de homem-morto segurado (nav_enable_button) E
     cmd_vel_nav recente;
  3. zero.

Qualquer falha cai no caso 3: soltar o homem-morto, controle desconectado
(/joy para de chegar), ponte ROS 2 ou Nav2 parados (cmd_vel_nav envelhece).
Fica no ROS 1 de proposito: o controle manual nao depende do lado ROS 2.
"""

import rospy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy
from std_msgs.msg import String

ZERO_EPS = 1e-3


def is_zero(cmd):
    return (abs(cmd.linear.x) < ZERO_EPS and abs(cmd.linear.y) < ZERO_EPS
            and abs(cmd.angular.z) < ZERO_EPS)


class MobiCmdMux:
    def __init__(self):
        # -1 desliga a navegacao (cmd_vel_nav nunca passa).
        self.nav_enable_button = rospy.get_param("~nav_enable_button", -1)
        self.joy_timeout = rospy.Duration(rospy.get_param("~joy_timeout", 0.5))
        self.nav_timeout = rospy.Duration(rospy.get_param("~nav_timeout", 0.5))
        rate = rospy.get_param("~output_rate", 20.0)

        self.joy_cmd, self.joy_cmd_stamp = Twist(), rospy.Time(0)
        self.nav_cmd, self.nav_cmd_stamp = Twist(), rospy.Time(0)
        self.deadman, self.joy_stamp = False, rospy.Time(0)
        self.source = None

        self.cmd_pub = rospy.Publisher("cmd_vel", Twist, queue_size=1)
        self.source_pub = rospy.Publisher("cmd_vel_source", String, queue_size=1, latch=True)
        rospy.Subscriber("cmd_vel_joy", Twist, self.on_joy_cmd, queue_size=1)
        rospy.Subscriber("cmd_vel_nav", Twist, self.on_nav_cmd, queue_size=1)
        rospy.Subscriber("joy", Joy, self.on_joy, queue_size=1)
        rospy.Timer(rospy.Duration(1.0 / rate), self.on_timer)
        rospy.on_shutdown(lambda: self.cmd_pub.publish(Twist()))

    def on_joy_cmd(self, msg):
        self.joy_cmd, self.joy_cmd_stamp = msg, rospy.Time.now()

    def on_nav_cmd(self, msg):
        self.nav_cmd, self.nav_cmd_stamp = msg, rospy.Time.now()

    def on_joy(self, msg):
        button = self.nav_enable_button
        self.deadman = 0 <= button < len(msg.buttons) and msg.buttons[button] != 0
        self.joy_stamp = rospy.Time.now()

    def select(self, now):
        if now - self.joy_cmd_stamp < self.joy_timeout and not is_zero(self.joy_cmd):
            return "joy", self.joy_cmd
        deadman_held = self.deadman and now - self.joy_stamp < self.joy_timeout
        if deadman_held and now - self.nav_cmd_stamp < self.nav_timeout:
            return "nav", self.nav_cmd
        return "idle", Twist()

    def on_timer(self, _event):
        source, cmd = self.select(rospy.Time.now())
        self.cmd_pub.publish(cmd)
        if source != self.source:
            rospy.loginfo("cmd_vel: %s -> %s", self.source, source)
            self.source = source
            self.source_pub.publish(source)


if __name__ == "__main__":
    rospy.init_node("mobi_cmd_mux")
    MobiCmdMux()
    rospy.spin()
