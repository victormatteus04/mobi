#!/usr/bin/env python3
"""Gera previews de uma bag sem precisar abrir nada manualmente:
  - thumbnail.jpg: um frame de uma camera (meio da gravacao)
  - contact_sheet.jpg: grade de N frames ao longo do tempo
  - trajectory.png: vista de cima (X/Y) de um topico de odometria, se houver
  - pointcloud_top_view.png: vista de cima acumulada de um PointCloud2, se houver

So usa cv2/numpy (ja presentes na imagem), sem dependencia nova.
"""
import argparse
import os

import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

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


def image_to_bgr(msg):
    h, w = msg.height, msg.width
    dtype = np.uint16 if msg.encoding in ("16UC1", "mono16") else np.uint8
    channels = 3 if msg.encoding in ("rgb8", "bgr8") else 1
    arr = np.frombuffer(msg.data, dtype=dtype).reshape(
        (h, w, channels) if channels > 1 else (h, w))
    if msg.encoding == "rgb8":
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if dtype == np.uint16:
        arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        arr = cv2.applyColorMap(arr, cv2.COLORMAP_TURBO)
    elif channels == 1:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    return arr


def pick_topic(type_map, wanted_type, name_hint=None, exclude_hints=()):
    candidates = [t for t, ty in type_map.items() if ty == wanted_type]
    if not candidates:
        return None
    if exclude_hints:
        filtered = [t for t in candidates if not any(ex in t for ex in exclude_hints)]
        if filtered:
            candidates = filtered
    if name_hint:
        for t in sorted(candidates):
            if name_hint in t:
                return t
    return sorted(candidates)[0]


def build_image_previews(bag_path, out_dir, image_topic, n_frames=9):
    reader = open_reader(bag_path)
    msg_type = get_message("sensor_msgs/msg/Image")
    frames = []
    for topic, data, t in _iter(reader):
        if topic != image_topic:
            continue
        frames.append((t, data))
    if not frames:
        return
    idxs = np.linspace(0, len(frames) - 1, min(n_frames, len(frames))).astype(int)
    idxs = sorted(set(idxs.tolist()))
    tiles = []
    for i in idxs:
        msg = deserialize_message(frames[i][1], msg_type)
        tiles.append(cv2.resize(image_to_bgr(msg), (160, 120)))

    mid = deserialize_message(frames[len(frames) // 2][1], msg_type)
    thumb = cv2.resize(image_to_bgr(mid), (320, 240))
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(os.path.join(out_dir, "thumbnail.jpg"), thumb)

    cols = min(3, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    canvas = np.zeros((rows * 120, cols * 160, 3), dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas[r * 120:(r + 1) * 120, c * 160:(c + 1) * 160] = tile
    cv2.imwrite(os.path.join(out_dir, "contact_sheet.jpg"), canvas)


def _iter(reader):
    while reader.has_next():
        yield reader.read_next()


def build_trajectory_preview(bag_path, out_dir, odom_topic, size=500, margin=40):
    reader = open_reader(bag_path)
    msg_type = get_message("nav_msgs/msg/Odometry")
    xs, ys = [], []
    for topic, data, _t in _iter(reader):
        if topic != odom_topic:
            continue
        msg = deserialize_message(data, msg_type)
        xs.append(msg.pose.pose.position.x)
        ys.append(msg.pose.pose.position.y)
    if len(xs) < 2:
        return
    xs, ys = np.array(xs), np.array(ys)
    x_min, x_max = xs.min(), xs.max()
    y_min, y_max = ys.min(), ys.max()
    span = max(x_max - x_min, y_max - y_min, 1e-3)
    scale = (size - 2 * margin) / span

    canvas = np.full((size, size, 3), 255, dtype=np.uint8)

    def to_px(x, y):
        px = int(margin + (x - x_min) * scale)
        py = int(size - margin - (y - y_min) * scale)
        return px, py

    pts = [to_px(x, y) for x, y in zip(xs, ys)]
    for a, b in zip(pts[:-1], pts[1:]):
        cv2.line(canvas, a, b, (200, 120, 0), 2)
    cv2.circle(canvas, pts[0], 6, (0, 180, 0), -1)
    cv2.circle(canvas, pts[-1], 6, (0, 0, 200), -1)
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(os.path.join(out_dir, "trajectory.png"), canvas)


def build_pointcloud_top_view(bag_path, out_dir, pc_topic, size=500, margin=20, max_frames=30):
    reader = open_reader(bag_path)
    msg_type = get_message("sensor_msgs/msg/PointCloud2")
    all_xy = []
    count = 0
    for topic, data, _t in _iter(reader):
        if topic != pc_topic:
            continue
        count += 1
        if count > max_frames:
            break
        msg = deserialize_message(data, msg_type)
        fields = {f.name: f for f in msg.fields}
        if "x" not in fields or "y" not in fields:
            continue
        n_points = msg.width * msg.height
        if n_points == 0:
            continue
        raw = np.frombuffer(msg.data, dtype=np.uint8)[: n_points * msg.point_step]
        raw = raw.reshape(n_points, msg.point_step)
        x = raw[:, fields["x"].offset:fields["x"].offset + 4].copy().view(np.float32).reshape(-1)
        y = raw[:, fields["y"].offset:fields["y"].offset + 4].copy().view(np.float32).reshape(-1)
        valid = np.isfinite(x) & np.isfinite(y)
        all_xy.append(np.column_stack([x[valid], y[valid]]))
    if not all_xy:
        return
    xy = np.concatenate(all_xy)
    if len(xy) == 0:
        return
    x_min, x_max = xy[:, 0].min(), xy[:, 0].max()
    y_min, y_max = xy[:, 1].min(), xy[:, 1].max()
    span = max(x_max - x_min, y_max - y_min, 1e-3)
    scale = (size - 2 * margin) / span

    canvas = np.zeros((size, size), dtype=np.uint32)
    px = (margin + (xy[:, 0] - x_min) * scale).astype(int)
    py = (size - margin - (xy[:, 1] - y_min) * scale).astype(int)
    valid = (px >= 0) & (px < size) & (py >= 0) & (py < size)
    np.add.at(canvas, (py[valid], px[valid]), 1)

    density = np.log1p(canvas.astype(np.float32))
    if density.max() > 0:
        density = (density / density.max() * 255).astype(np.uint8)
    else:
        density = density.astype(np.uint8)
    img = cv2.applyColorMap(density, cv2.COLORMAP_VIRIDIS)
    img[canvas == 0] = (30, 30, 30)
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(os.path.join(out_dir, "pointcloud_top_view.png"), img)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag-path", required=True)
    p.add_argument("--out-dir", default=None, help="default: <bag-path>/preview")
    args = p.parse_args()

    if cv2 is None:
        print("[PREVIEW] cv2 indisponivel, pulando.")
        return

    out_dir = args.out_dir or os.path.join(args.bag_path, "preview")

    reader = open_reader(args.bag_path)
    type_map = {m.name: m.type for m in reader.get_all_topics_and_types()}

    image_topic = pick_topic(type_map, "sensor_msgs/msg/Image", name_hint="color",
                              exclude_hints=("depth", "infra"))
    odom_topic = pick_topic(type_map, "nav_msgs/msg/Odometry", name_hint="t265")
    pc_topic = pick_topic(type_map, "sensor_msgs/msg/PointCloud2")

    if image_topic:
        build_image_previews(args.bag_path, out_dir, image_topic)
        print(f"[PREVIEW] thumbnail/contact_sheet a partir de {image_topic}")
    if odom_topic:
        build_trajectory_preview(args.bag_path, out_dir, odom_topic)
        print(f"[PREVIEW] trajectory.png a partir de {odom_topic}")
    if pc_topic:
        build_pointcloud_top_view(args.bag_path, out_dir, pc_topic)
        print(f"[PREVIEW] pointcloud_top_view.png a partir de {pc_topic}")
    if not (image_topic or odom_topic or pc_topic):
        print("[PREVIEW] nenhum topico compativel encontrado (Image/Odometry/PointCloud2).")


if __name__ == "__main__":
    main()
