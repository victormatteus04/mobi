#!/usr/bin/env python3
"""Gera previews de uma bag sem precisar abrir nada manualmente:
  - thumbnail.jpg: um frame de uma camera (meio da gravacao)
  - contact_sheet.jpg: grade de N frames ao longo do tempo
  - trajectory.png: vista de cima (X/Y) de um topico de odometria, se houver
  - pointcloud_top_view.png: vista de cima acumulada de um PointCloud2, se houver

So usa cv2/numpy (ja presentes na imagem), sem dependencia nova. Um unico
passe pela bag (nao um por artefato) e com log de progresso, ja que bags de
sensor real facilmente passam de dezenas de GB e minutos de leitura.
"""
import argparse
import os
import time

import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

try:
    import cv2
except ImportError:
    cv2 = None

PROGRESS_INTERVAL_S = 2.0
POINTCLOUD_MAX_FRAMES = 30


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


def collect(bag_path, image_topic, odom_topic, pc_topic, total_messages):
    """Um unico passe pela bag, distribuindo cada mensagem pro coletor certo."""
    reader = open_reader(bag_path)
    image_frames = []  # (t, raw_bytes), imagem so e deserializada depois
    odom_xy = []
    pc_xy_chunks = []
    pc_count = 0

    progress = ProgressLogger("PREVIEW-LEITURA", total=total_messages)
    odom_msg_type = get_message("nav_msgs/msg/Odometry") if odom_topic else None
    pc_msg_type = get_message("sensor_msgs/msg/PointCloud2") if pc_topic else None

    while reader.has_next():
        topic, data, t = reader.read_next()
        progress.step()

        if topic == image_topic:
            image_frames.append((t, data))
            continue

        if topic == odom_topic:
            msg = deserialize_message(data, odom_msg_type)
            odom_xy.append((msg.pose.pose.position.x, msg.pose.pose.position.y))
            continue

        if topic == pc_topic and pc_count < POINTCLOUD_MAX_FRAMES:
            pc_count += 1
            msg = deserialize_message(data, pc_msg_type)
            fields = {f.name: f for f in msg.fields}
            n_points = msg.width * msg.height
            if "x" in fields and "y" in fields and n_points > 0:
                raw = np.frombuffer(msg.data, dtype=np.uint8)[: n_points * msg.point_step]
                raw = raw.reshape(n_points, msg.point_step)
                x = raw[:, fields["x"].offset:fields["x"].offset + 4].copy().view(np.float32).reshape(-1)
                y = raw[:, fields["y"].offset:fields["y"].offset + 4].copy().view(np.float32).reshape(-1)
                valid = np.isfinite(x) & np.isfinite(y)
                pc_xy_chunks.append(np.column_stack([x[valid], y[valid]]))

    progress.done()
    return image_frames, odom_xy, pc_xy_chunks


def render_image_previews(image_frames, out_dir, n_frames=9):
    if not image_frames:
        return
    log(f"[PREVIEW] renderizando thumbnail/contact_sheet ({len(image_frames)} frames capturados)")
    msg_type = get_message("sensor_msgs/msg/Image")
    idxs = np.linspace(0, len(image_frames) - 1, min(n_frames, len(image_frames))).astype(int)
    idxs = sorted(set(idxs.tolist()))
    tiles = []
    for i in idxs:
        msg = deserialize_message(image_frames[i][1], msg_type)
        tiles.append(cv2.resize(image_to_bgr(msg), (160, 120)))

    mid = deserialize_message(image_frames[len(image_frames) // 2][1], msg_type)
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
    log("[PREVIEW] thumbnail.jpg e contact_sheet.jpg gravados")


def render_trajectory(odom_xy, out_dir, size=500, margin=40):
    if len(odom_xy) < 2:
        return
    log(f"[PREVIEW] renderizando trajectory.png ({len(odom_xy)} poses)")
    xs = np.array([p[0] for p in odom_xy])
    ys = np.array([p[1] for p in odom_xy])
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
    log("[PREVIEW] trajectory.png gravado")


def render_pointcloud_top_view(pc_xy_chunks, out_dir, size=500, margin=20):
    if not pc_xy_chunks:
        return
    xy = np.concatenate(pc_xy_chunks)
    if len(xy) == 0:
        return
    log(f"[PREVIEW] renderizando pointcloud_top_view.png ({len(xy)} pontos, {len(pc_xy_chunks)} frames)")
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
    log("[PREVIEW] pointcloud_top_view.png gravado")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag-path", required=True)
    p.add_argument("--out-dir", default=None, help="default: <bag-path>/preview")
    args = p.parse_args()

    if cv2 is None:
        log("[PREVIEW] cv2 indisponivel, pulando.")
        return

    out_dir = args.out_dir or os.path.join(args.bag_path, "preview")

    reader = open_reader(args.bag_path)
    type_map = {m.name: m.type for m in reader.get_all_topics_and_types()}
    total_messages = reader.get_metadata().message_count
    log(f"[PREVIEW] bag com {total_messages} mensagens em {len(type_map)} topicos")

    image_topic = pick_topic(type_map, "sensor_msgs/msg/Image", name_hint="color",
                              exclude_hints=("depth", "infra"))
    odom_topic = pick_topic(type_map, "nav_msgs/msg/Odometry", name_hint="t265")
    pc_topic = pick_topic(type_map, "sensor_msgs/msg/PointCloud2")

    if not (image_topic or odom_topic or pc_topic):
        log("[PREVIEW] nenhum topico compativel encontrado (Image/Odometry/PointCloud2).")
        return

    log(f"[PREVIEW] fontes escolhidas: imagem={image_topic or '-'} "
        f"odometria={odom_topic or '-'} nuvem={pc_topic or '-'}")

    image_frames, odom_xy, pc_xy_chunks = collect(
        args.bag_path, image_topic, odom_topic, pc_topic, total_messages)

    render_image_previews(image_frames, out_dir)
    render_trajectory(odom_xy, out_dir)
    render_pointcloud_top_view(pc_xy_chunks, out_dir)
    log("[PREVIEW] concluido.")


if __name__ == "__main__":
    main()
