import os
import sys
import threading
import time

import rclpy
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, "/mobi")
import topics_config  # noqa: E402

from bag_manager import BagManager  # noqa: E402
from ros_monitor import TopicMonitor, spin_in_background  # noqa: E402

BAGS_DIR = os.environ.get("MOBI_BAGS_DIR", "/bags")
RECORD_SCRIPT = os.environ.get("MOBI_RECORD_SCRIPT", "/mobi/record-bag.sh")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))

app = Flask(__name__, static_folder="static", static_url_path="")
bag_mgr = BagManager(bags_dir=BAGS_DIR, record_script=RECORD_SCRIPT)

_config = topics_config.load_config()
_entries = topics_config.all_entries(_config)

rclpy.init()
monitor = TopicMonitor(_entries)
spin_in_background(monitor)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/config")
def api_config():
    groups = []
    for name, spec in _config.items():
        groups.append({
            "name": name,
            "label": spec.get("label", name),
            "required": [e["topic"] for e in spec.get("required", [])],
            "optional": [e["topic"] for e in spec.get("optional", [])],
        })
    return jsonify({"groups": groups})


@app.route("/api/status")
def api_status():
    return jsonify(monitor.snapshot())


@app.route("/api/bags")
def api_bags():
    return jsonify(bag_mgr.list_bags())


@app.route("/api/record/status")
def api_record_status():
    return jsonify(bag_mgr.status())


@app.route("/api/record/start", methods=["POST"])
def api_record_start():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    groups = data.get("groups") or []
    extra_topics = [t.strip() for t in (data.get("extra_topics") or []) if t.strip()]
    topics_only = bool(data.get("topics_only", False))
    metadata = {
        "operator": (data.get("operator") or "").strip(),
        "location": (data.get("location") or "").strip(),
        "conditions": (data.get("conditions") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
    }
    ok, message = bag_mgr.start(name, groups, extra_topics, topics_only, metadata)
    return jsonify({"ok": ok, "message": message})


@app.route("/api/record/stop", methods=["POST"])
def api_record_stop():
    ok, message = bag_mgr.stop()
    return jsonify({"ok": ok, "message": message})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
