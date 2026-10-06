#!/usr/bin/env python3
"""Extrai uma bag MCAP para formatos abertos (PNG, PCD, CSV, TUM, YAML),
sem exigir ROS instalado para consumir o resultado depois.

Despacha por TIPO de mensagem (nao por nome de topico), entao funciona pra
qualquer sessao gravada com config/topics.yaml, sem precisar de logica por
sensor:
  sensor_msgs/Image           -> PNG por frame (images/<topico>/)
  sensor_msgs/CompressedImage -> JPG por frame
  sensor_msgs/PointCloud2     -> PCD binario por frame (pointclouds/<topico>/)
  sensor_msgs/Imu             -> CSV (imu/<topico>.csv)
  nav_msgs/Odometry           -> TUM + CSV (trajectories/<topico>.tum/.csv)
  sensor_msgs/CameraInfo      -> YAML, uma vez por topico (camera_info/<topico>.yaml)
  tf2_msgs/TFMessage (/tf_static) -> extrinsics.yaml (uma arvore so)

Uso:
  extract_bag.py --bag-path /bags/SESSAO [--images-format png|jpg] [--topics t1,t2]
"""
import argparse
import csv
import os
import struct
import sys
import time

import numpy as np
import rosbag2_py
import yaml
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

PROGRESS_INTERVAL_S = 2.0


def log(msg):
    print(msg, flush=True)


class ProgressLogger:
    def __init__(self, label, total=None, interval_s=PROGRESS_INTERVAL_S):
        self.label = label
        self.total = total
        self.interval_s = interval_s
        self.count = 0
        self.start = time.monotonic()
        self.last_print = self.start

    def step(self, n=1):
        self.count += n
        now = time.monotonic()
        if now - self.last_print >= self.interval_s:
            self._print(now)
            self.last_print = now

    def _print(self, now):
        elapsed = now - self.start
        if self.total:
            pct = 100.0 * self.count / self.total
            log(f"[{self.label}] {self.count}/{self.total} mensagens ({pct:.0f}%) - {elapsed:.0f}s")
        else:
            log(f"[{self.label}] {self.count} mensagens - {elapsed:.0f}s")

    def done(self):
        self._print(time.monotonic())


try:
    import cv2
except ImportError:
    cv2 = None


def open_reader(bag_path):
    storage_options = rosbag2_py.StorageOptions(uri=bag_path, storage_id="mcap")
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)
    return reader


def safe_name(topic):
    return topic.strip("/").replace("/", "_")


def stamp_ns(msg):
    try:
        h = msg.header.stamp
        return h.sec * 1_000_000_000 + h.nanosec
    except AttributeError:
        return None


class ImageExtractor:
    def __init__(self, out_dir, topic, fmt="png"):
        self.dir = os.path.join(out_dir, "images", safe_name(topic))
        os.makedirs(self.dir, exist_ok=True)
        self.fmt = fmt
        self.count = 0

    def write(self, msg, t_ns):
        if cv2 is None:
            return
        h, w = msg.height, msg.width
        dtype = np.uint16 if msg.encoding in ("16UC1", "mono16") else np.uint8
        channels = 3 if msg.encoding in ("rgb8", "bgr8") else 1
        arr = np.frombuffer(msg.data, dtype=dtype).reshape(
            (h, w, channels) if channels > 1 else (h, w))
        if msg.encoding == "rgb8":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        ts = t_ns if t_ns is not None else self.count
        path = os.path.join(self.dir, f"{self.count:06d}_{ts}.{self.fmt}")
        cv2.imwrite(path, arr)
        self.count += 1


class PointCloudExtractor:
    """PointCloud2 -> PCD binario.

    Repacka campo a campo (nao um memcpy direto de msg.data): muitos drivers
    (Ouster incluso) deixam padding/alinhamento entre campos dentro de
    point_step que o formato PCD nao representa. Copiar o buffer cru daria
    uma nuvem com os campos desalinhados/lixo. Aqui cada campo e extraido
    pelo seu proprio offset e reescrito lado a lado, sem padding.
    """
    # sensor_msgs/PointField: INT8=1 UINT8=2 INT16=3 UINT16=4 INT32=5 UINT32=6
    # FLOAT32=7 FLOAT64=8
    PCD_TYPE = {1: "I", 2: "U", 3: "I", 4: "U", 5: "I", 6: "U", 7: "F", 8: "F"}
    NUMPY_DTYPE = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}

    def __init__(self, out_dir, topic):
        self.dir = os.path.join(out_dir, "pointclouds", safe_name(topic))
        os.makedirs(self.dir, exist_ok=True)
        self.count = 0

    def write(self, msg, t_ns):
        fields = sorted(msg.fields, key=lambda f: f.offset)
        n_points = msg.width * msg.height
        if n_points == 0:
            return

        raw = np.frombuffer(msg.data, dtype=np.uint8)
        raw = raw[: n_points * msg.point_step].reshape(n_points, msg.point_step)

        struct_dtype = np.dtype(
            [(f.name, self.NUMPY_DTYPE[f.datatype]) for f in fields], align=False)
        packed = np.zeros(n_points, dtype=struct_dtype)
        for f in fields:
            np_dt = np.dtype(self.NUMPY_DTYPE[f.datatype])
            column = raw[:, f.offset:f.offset + np_dt.itemsize].copy().view(np_dt).reshape(n_points)
            packed[f.name] = column

        names = [f.name for f in fields]
        types = [self.PCD_TYPE[f.datatype] for f in fields]
        sizes = [str(np.dtype(self.NUMPY_DTYPE[f.datatype]).itemsize) for f in fields]
        counts = ["1"] * len(fields)

        header = "\n".join([
            "# .PCD v0.7 - Point Cloud Data file format",
            "VERSION 0.7",
            f"FIELDS {' '.join(names)}",
            f"SIZE {' '.join(sizes)}",
            f"TYPE {' '.join(types)}",
            f"COUNT {' '.join(counts)}",
            f"WIDTH {n_points}",
            "HEIGHT 1",
            "VIEWPOINT 0 0 0 1 0 0 0",
            f"POINTS {n_points}",
            "DATA binary",
            "",
        ])
        ts = t_ns if t_ns is not None else self.count
        path = os.path.join(self.dir, f"{self.count:06d}_{ts}.pcd")
        with open(path, "wb") as f:
            f.write(header.encode("ascii"))
            f.write(packed.tobytes())
        self.count += 1


class ImuExtractor:
    def __init__(self, out_dir, topic):
        os.makedirs(os.path.join(out_dir, "imu"), exist_ok=True)
        path = os.path.join(out_dir, "imu", f"{safe_name(topic)}.csv")
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow([
            "timestamp_ns", "qx", "qy", "qz", "qw",
            "wx", "wy", "wz", "ax", "ay", "az",
        ])

    def write(self, msg, t_ns):
        o, av, la = msg.orientation, msg.angular_velocity, msg.linear_acceleration
        self.w.writerow([t_ns, o.x, o.y, o.z, o.w, av.x, av.y, av.z, la.x, la.y, la.z])

    def close(self):
        self.f.close()


class OdometryExtractor:
    def __init__(self, out_dir, topic):
        os.makedirs(os.path.join(out_dir, "trajectories"), exist_ok=True)
        base = os.path.join(out_dir, "trajectories", safe_name(topic))
        self.tum = open(base + ".tum", "w", newline="")
        self.csv_f = open(base + ".csv", "w", newline="")
        self.csv_w = csv.writer(self.csv_f)
        self.csv_w.writerow([
            "timestamp_ns", "tx", "ty", "tz", "qx", "qy", "qz", "qw",
            "vx", "vy", "vz", "wx", "wy", "wz",
        ])

    def write(self, msg, t_ns):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        t_s = (t_ns / 1e9) if t_ns is not None else 0.0
        self.tum.write(f"{t_s:.9f} {p.x} {p.y} {p.z} {q.x} {q.y} {q.z} {q.w}\n")
        lv, av = msg.twist.twist.linear, msg.twist.twist.angular
        self.csv_w.writerow([t_ns, p.x, p.y, p.z, q.x, q.y, q.z, q.w,
                              lv.x, lv.y, lv.z, av.x, av.y, av.z])

    def close(self):
        self.tum.close()
        self.csv_f.close()


class CameraInfoExtractor:
    def __init__(self, out_dir, topic):
        self.dir = os.path.join(out_dir, "camera_info")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, f"{safe_name(topic)}.yaml")
        self.written = False

    def write(self, msg, _t_ns):
        if self.written:
            return
        data = {
            "image_width": int(msg.width),
            "image_height": int(msg.height),
            "camera_name": safe_name(self.path),
            "distortion_model": msg.distortion_model,
            "distortion_coefficients": {"rows": 1, "cols": len(msg.d), "data": [float(v) for v in msg.d]},
            "camera_matrix": {"rows": 3, "cols": 3, "data": [float(v) for v in msg.k]},
            "rectification_matrix": {"rows": 3, "cols": 3, "data": [float(v) for v in msg.r]},
            "projection_matrix": {"rows": 3, "cols": 4, "data": [float(v) for v in msg.p]},
        }
        with open(self.path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        self.written = True


def collect_static_transform(msg, transforms):
    """Acumula um TFMessage de /tf_static num dict (chamado do loop principal,
    sem precisar de uma segunda passada pela bag so pra isso)."""
    for tf in msg.transforms:
        key = f"{tf.header.frame_id} -> {tf.child_frame_id}"
        t, r = tf.transform.translation, tf.transform.rotation
        transforms[key] = {
            "parent_frame": tf.header.frame_id,
            "child_frame": tf.child_frame_id,
            "translation": {"x": float(t.x), "y": float(t.y), "z": float(t.z)},
            "rotation": {"x": float(r.x), "y": float(r.y), "z": float(r.z), "w": float(r.w)},
        }


def write_extrinsics_yaml(transforms, out_dir):
    if not transforms:
        return
    with open(os.path.join(out_dir, "extrinsics.yaml"), "w") as f:
        yaml.safe_dump({"static_transforms": list(transforms.values())}, f,
                        default_flow_style=False, sort_keys=False)


EXTRACTOR_BY_TYPE = {
    "sensor_msgs/msg/Image": ImageExtractor,
    "sensor_msgs/msg/PointCloud2": PointCloudExtractor,
    "sensor_msgs/msg/Imu": ImuExtractor,
    "nav_msgs/msg/Odometry": OdometryExtractor,
    "sensor_msgs/msg/CameraInfo": CameraInfoExtractor,
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag-path", required=True)
    p.add_argument("--out-dir", default=None, help="default: <bag-path>/extracted")
    p.add_argument("--images-format", default="png", choices=["png", "jpg"])
    p.add_argument("--topics", default="", help="filtro opcional, separado por virgula")
    args = p.parse_args()

    out_dir = args.out_dir or os.path.join(args.bag_path, "extracted")
    os.makedirs(out_dir, exist_ok=True)
    topic_filter = set(t for t in args.topics.split(",") if t) or None

    reader = open_reader(args.bag_path)
    type_map = {m.name: m.type for m in reader.get_all_topics_and_types()}
    total_messages = reader.get_metadata().message_count
    log(f"[EXTRACT] bag com {total_messages} mensagens em {len(type_map)} topicos")

    extractors = {}
    msg_types = {}
    counts = {}
    static_transforms = {}
    tf_static_msg_type = (get_message(type_map["/tf_static"])
                           if type_map.get("/tf_static") else None)

    progress = ProgressLogger("EXTRACT-LEITURA", total=total_messages)
    while reader.has_next():
        topic, data, t = reader.read_next()
        progress.step()

        if topic == "/tf_static" and tf_static_msg_type:
            collect_static_transform(deserialize_message(data, tf_static_msg_type),
                                      static_transforms)

        if topic_filter and topic not in topic_filter:
            continue
        ros_type = type_map.get(topic)
        if ros_type not in EXTRACTOR_BY_TYPE:
            continue

        if topic not in extractors:
            cls = EXTRACTOR_BY_TYPE[ros_type]
            if cls is ImageExtractor:
                extractors[topic] = cls(out_dir, topic, fmt=args.images_format)
            else:
                extractors[topic] = cls(out_dir, topic)
            msg_types[topic] = get_message(ros_type)
            counts[topic] = 0
            log(f"[EXTRACT] iniciando {topic} ({ros_type})")

        msg = deserialize_message(data, msg_types[topic])
        stamp = stamp_ns(msg)
        t_ns = stamp if stamp else t
        extractors[topic].write(msg, t_ns)
        counts[topic] += 1
    progress.done()

    for ex in extractors.values():
        if hasattr(ex, "close"):
            ex.close()

    write_extrinsics_yaml(static_transforms, out_dir)

    manifest = {
        "source_bag": os.path.basename(args.bag_path.rstrip("/")),
        "extracted": {t: {"type": type_map[t], "count": c} for t, c in counts.items()},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        import json
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    log("[EXTRACT] concluido:")
    for topic, c in counts.items():
        log(f"[EXTRACT]   {topic} ({type_map[topic]}): {c} mensagens")
    if not counts:
        print("[EXTRACT] nenhum topico com tipo suportado encontrado.", file=sys.stderr)


if __name__ == "__main__":
    main()
