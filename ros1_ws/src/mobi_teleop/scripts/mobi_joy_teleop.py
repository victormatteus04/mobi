#!/usr/bin/env python3

import rospy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy


class MobiJoyTeleop:
    def __init__(self):
        self.axis_linear = rospy.get_param("~axis_linear", 4)
        self.axis_angular = rospy.get_param("~axis_angular", 3)
        self.scale_linear = rospy.get_param("~scale_linear", 0.25)
        self.scale_linear_turbo = rospy.get_param("~scale_linear_turbo", 0.50)
        self.scale_angular = rospy.get_param("~scale_angular", 0.60)
        self.scale_angular_turbo = rospy.get_param("~scale_angular_turbo", 1.20)
        self.turbo_button = rospy.get_param("~enable_turbo_button", 5)
        self.watchdog_timeout = rospy.Duration(
            rospy.get_param("~watchdog_timeout", 0.25)
        )

        self.last_joy = None
        self.watchdog_zero_sent = False
        self.publisher = rospy.Publisher("cmd_vel", Twist, queue_size=1)
        self.subscriber = rospy.Subscriber("joy", Joy, self.joy_callback, queue_size=1)
        self.timer = rospy.Timer(rospy.Duration(0.05), self.watchdog_callback)
        rospy.on_shutdown(self.publish_zero)

    def joy_callback(self, message):
        self.last_joy = rospy.Time.now()
        self.watchdog_zero_sent = False

        required_axis = max(self.axis_linear, self.axis_angular)
        if required_axis >= len(message.axes):
            rospy.logerr_throttle(
                2.0,
                "Joy possui %d eixos, mas a configuracao requer o eixo %d",
                len(message.axes),
                required_axis,
            )
            self.publish_zero()
            return

        turbo = (
            0 <= self.turbo_button < len(message.buttons)
            and message.buttons[self.turbo_button] != 0
        )
        linear_scale = self.scale_linear_turbo if turbo else self.scale_linear
        angular_scale = self.scale_angular_turbo if turbo else self.scale_angular

        command = Twist()
        command.linear.x = message.axes[self.axis_linear] * linear_scale
        command.angular.z = message.axes[self.axis_angular] * angular_scale
        self.publisher.publish(command)

    def watchdog_callback(self, event):
        if self.watchdog_zero_sent:
            return
        if self.last_joy is None or event.current_real - self.last_joy > self.watchdog_timeout:
            self.publish_zero()
            self.watchdog_zero_sent = True

    def publish_zero(self):
        self.publisher.publish(Twist())


if __name__ == "__main__":
    rospy.init_node("mobi_joy_teleop")
    MobiJoyTeleop()
    rospy.spin()
