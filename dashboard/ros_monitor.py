"""Node ROS2 que assina todos os topicos do config/topics.yaml e mantem,
em memoria, a taxa de mensagens e o tempo desde a ultima mensagem de cada um.
Roda em background thread; o Flask so le o snapshot (thread-safe)."""
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

RATE_WINDOW_S = 5.0


def _qos_for(kind):
    if kind == "sensor_data":
        return QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )
    if kind == "static":
        return QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=20,
        )
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )


class TopicMonitor(Node):
    def __init__(self, entries):
        super().__init__("mobi_dashboard_monitor")
        self._lock = threading.Lock()
        self._status = {}
        for entry in entries:
            topic = entry["topic"]
            try:
                msg_type = get_message(entry["type"])
            except (ValueError, ModuleNotFoundError, AttributeError) as exc:
                self.get_logger().warn(f"tipo desconhecido '{entry['type']}' para {topic}: {exc}")
                continue
            qos = _qos_for(entry.get("qos"))
            self.create_subscription(msg_type, topic, self._callback(topic), qos)
            self._status[topic] = {
                "group": entry.get("group"),
                "required": entry.get("required", False),
                "label": entry.get("label", topic),
                "last_seen": None,
                "count": 0,
                "window": [],
            }

    def _callback(self, topic):
        def _cb(_msg):
            now = time.monotonic()
            with self._lock:
                st = self._status[topic]
                st["last_seen"] = now
                st["count"] += 1
                st["window"].append(now)
                cutoff = now - RATE_WINDOW_S
                st["window"] = [t for t in st["window"] if t >= cutoff]
        return _cb

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            out = {}
            for topic, st in self._status.items():
                age = (now - st["last_seen"]) if st["last_seen"] is not None else None
                out[topic] = {
                    "group": st["group"],
                    "required": st["required"],
                    "label": st["label"],
                    "rate_hz": round(len(st["window"]) / RATE_WINDOW_S, 2),
                    "age_s": round(age, 1) if age is not None else None,
                    "count": st["count"],
                }
            return out


def spin_in_background(node):
    executor_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    executor_thread.start()
    return executor_thread
