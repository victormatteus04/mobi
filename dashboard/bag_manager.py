"""Controla gravacao de bag chamando o mesmo scripts/record-bag.sh usado
pelo terminal (mobi.sh bag) -- sem duplicar a logica de espera/QoS/MCAP."""
import glob
import os
import signal
import subprocess
import threading
import time


class BagManager:
    def __init__(self, bags_dir="/bags", record_script="/mobi/record-bag.sh"):
        self.bags_dir = bags_dir
        self.record_script = record_script
        self._lock = threading.Lock()
        self._proc = None
        self._name = None
        self._groups = []
        self._extra_topics = []
        self._started_at = None
        self._log_lines = []

    def start(self, name, groups, extra_topics, topics_only=False, metadata=None):
        metadata = metadata or {}
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False, "ja existe uma gravacao em andamento"
            if not name or "/" in name or name in (".", ".."):
                return False, "nome de sessao invalido"
            out_path = os.path.join(self.bags_dir, name)
            if os.path.exists(out_path):
                return False, f"sessao ja existe: {name}"
            if not groups and not extra_topics:
                return False, "selecione ao menos um grupo ou topico"

            env = os.environ.copy()
            env["BAG_SENSOR_SET"] = ",".join(groups) if groups else "base"
            env["BAG_TOPICS"] = ",".join(extra_topics)
            env["BAG_TOPICS_ONLY"] = "true" if topics_only else "false"
            env["MOBI_OPERATOR"] = metadata.get("operator", "")
            env["MOBI_LOCATION"] = metadata.get("location", "")
            env["MOBI_CONDITIONS"] = metadata.get("conditions", "")
            env["MOBI_NOTES"] = metadata.get("notes", "")
            env.setdefault("HOST_UID", "1000")
            env.setdefault("HOST_GID", "1000")

            sensor_arg = ",".join(groups) if groups else "base"
            self._proc = subprocess.Popen(
                ["bash", self.record_script, name, sensor_arg],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )
            self._name = name
            self._groups = groups
            self._extra_topics = extra_topics
            self._started_at = time.time()
            self._log_lines = []
            threading.Thread(target=self._drain_log, args=(self._proc,), daemon=True).start()
            return True, "gravacao iniciada"

    def _drain_log(self, proc):
        for line in proc.stdout:
            with self._lock:
                self._log_lines.append(line.rstrip("\n"))
                self._log_lines = self._log_lines[-200:]

    def stop(self):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return False, "nenhuma gravacao em andamento"
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGINT)
            except ProcessLookupError:
                pass
            proc = self._proc
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
        with self._lock:
            name = self._name
            self._proc = None
            self._name = None
            self._started_at = None
            return True, f"gravacao finalizada: {name}"

    def _bag_size(self, name):
        pattern = os.path.join(self.bags_dir, name, "*.mcap")
        return sum(os.path.getsize(f) for f in glob.glob(pattern))

    def status(self):
        with self._lock:
            recording = self._proc is not None and self._proc.poll() is None
            if not recording:
                return {"recording": False, "log": list(self._log_lines[-40:])}
            name = self._name
            groups = list(self._groups)
            extra_topics = list(self._extra_topics)
            started_at = self._started_at
            log = list(self._log_lines[-40:])
        return {
            "recording": True,
            "name": name,
            "groups": groups,
            "extra_topics": extra_topics,
            "elapsed_s": round(time.time() - started_at, 1),
            "size_bytes": self._bag_size(name),
            "log": log,
        }

    def list_bags(self):
        bags = []
        for entry in sorted(glob.glob(os.path.join(self.bags_dir, "*"))):
            if not os.path.isdir(entry):
                continue
            size = sum(os.path.getsize(f) for f in glob.glob(os.path.join(entry, "*.mcap")))
            mtime = os.path.getmtime(entry)
            bags.append({
                "name": os.path.basename(entry),
                "size_bytes": size,
                "modified_at": mtime,
            })
        bags.sort(key=lambda b: b["modified_at"], reverse=True)
        return bags
