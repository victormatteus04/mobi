#!/usr/bin/env python3
"""Gera metadata.json + README.md dentro de uma sessao de bag ja gravada.

Best-effort: nunca deve fazer o processo de gravacao falhar. Le o
metadata.yaml que o proprio rosbag2 escreve (fonte de verdade sobre o que
realmente foi gravado: topicos, tipos, contagem de mensagens) em vez de
tentar repassar essa lista pelo bash.
"""
import argparse
import hashlib
import json
import os
import sys

import yaml

SCHEMA_VERSION = "1.0"


def sha256_of(path, chunk_size=8 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_bag_metadata(output_path):
    meta_path = os.path.join(output_path, "metadata.yaml")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("rosbag2_bagfile_information", {})


def topics_from_bag_metadata(bag_meta):
    topics = []
    for entry in bag_meta.get("topics_with_message_count", []):
        tm = entry.get("topic_metadata", {})
        topics.append({
            "name": tm.get("name"),
            "type": tm.get("type"),
            "serialization_format": tm.get("serialization_format"),
            "message_count": entry.get("message_count"),
        })
    return topics


def ns_to_iso(nanoseconds_since_epoch):
    if nanoseconds_since_epoch is None:
        return None
    import datetime
    dt = datetime.datetime.fromtimestamp(
        nanoseconds_since_epoch / 1e9, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-path", required=True)
    p.add_argument("--session-name", required=True)
    p.add_argument("--sensor-groups", default="")
    p.add_argument("--extra-topics", default="")
    p.add_argument("--topics-only", default="false")
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--operator", default="")
    p.add_argument("--location", default="")
    p.add_argument("--conditions", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--git-commit", default="")
    p.add_argument("--git-dirty", default="")
    p.add_argument("--config-fingerprint", default="")
    args = p.parse_args()

    bag_meta = load_bag_metadata(args.output_path)

    duration_s = None
    recorded_start = args.start_time or None
    recorded_end = args.end_time or None
    topics = []
    message_count = None
    compression_format = None
    compression_mode = None

    if bag_meta:
        duration_ns = bag_meta.get("duration", {}).get("nanoseconds")
        if duration_ns is not None:
            duration_s = round(duration_ns / 1e9, 3)
        starting_ns = bag_meta.get("starting_time", {}).get("nanoseconds_since_epoch")
        if starting_ns is not None:
            recorded_start = ns_to_iso(starting_ns)
            if duration_ns is not None:
                recorded_end = ns_to_iso(starting_ns + duration_ns)
        topics = topics_from_bag_metadata(bag_meta)
        message_count = bag_meta.get("message_count")
        compression_format = bag_meta.get("compression_format") or None
        compression_mode = bag_meta.get("compression_mode") or None

    files = []
    for fname in sorted(os.listdir(args.output_path)):
        if fname.endswith(".mcap"):
            fpath = os.path.join(args.output_path, fname)
            files.append({
                "name": fname,
                "sha256": sha256_of(fpath),
                "size_bytes": os.path.getsize(fpath),
            })
    total_size = sum(f["size_bytes"] for f in files)

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "session": {
            "name": args.session_name,
            "operator": args.operator or None,
            "location": args.location or None,
            "conditions": args.conditions or None,
            "notes": args.notes or None,
            "recorded_start_utc": recorded_start,
            "recorded_end_utc": recorded_end,
            "duration_s": duration_s,
        },
        "recording": {
            "sensor_groups": [g for g in args.sensor_groups.split(",") if g],
            "extra_topics": [t for t in args.extra_topics.split(",") if t],
            "topics_only": args.topics_only.lower() == "true",
            "message_count": message_count,
            "storage": {
                "format": "mcap",
                "compression_format": compression_format,
                "compression_mode": compression_mode,
            },
            "topics": topics,
        },
        "software": {
            "git_commit": args.git_commit or None,
            "git_dirty": (args.git_dirty.lower() == "true") if args.git_dirty else None,
            "config_fingerprint_sha256": args.config_fingerprint or None,
        },
        "files": files,
        "total_size_bytes": total_size,
    }

    with open(os.path.join(args.output_path, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
        f.write("\n")

    write_readme(args.output_path, metadata)


def fmt_bytes(n):
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def write_readme(output_path, m):
    s = m["session"]
    r = m["recording"]
    lines = [
        f"# Sessao: {s['name']}",
        "",
        f"- Inicio (UTC): {s['recorded_start_utc'] or '?'}",
        f"- Fim (UTC): {s['recorded_end_utc'] or '?'}",
        f"- Duracao: {s['duration_s']}s" if s["duration_s"] else "- Duracao: ?",
        f"- Operador: {s['operator'] or '-'}",
        f"- Local: {s['location'] or '-'}",
        f"- Condicoes: {s['conditions'] or '-'}",
        f"- Notas: {s['notes'] or '-'}",
        "",
        f"## Sensores gravados: {', '.join(r['sensor_groups']) or '(nenhum grupo, so topicos extra)'}",
    ]
    if r["extra_topics"]:
        lines.append(f"Topicos extra: {', '.join(r['extra_topics'])}")
    lines += [
        "",
        f"## Armazenamento: {r['storage']['format']}"
        + (f" (compressao {r['storage']['compression_format']}/{r['storage']['compression_mode']})"
           if r['storage']['compression_format'] else " (sem compressao)"),
        f"Tamanho total: {fmt_bytes(m['total_size_bytes'])} | Mensagens: {r['message_count'] or '?'}",
        "",
        "## Topicos",
        "",
        "| Topico | Tipo | Mensagens |",
        "|---|---|---|",
    ]
    for t in sorted(r["topics"], key=lambda x: x["name"] or ""):
        lines.append(f"| `{t['name']}` | `{t['type']}` | {t['message_count']} |")

    lines += [
        "",
        "## Reproduzir",
        "",
        "```bash",
        f"./mobi.sh play {s['name']}",
        "```",
        "",
    ]
    git_commit = m["software"]["git_commit"]
    if git_commit:
        dirty_note = " (com alteracoes locais nao commitadas)" if m["software"]["git_dirty"] else ""
        lines.append(f"Software: commit `{git_commit[:12]}`{dirty_note}")
    else:
        lines.append(f"Fingerprint da configuracao usada: `{m['software']['config_fingerprint_sha256'] or '-'}`")
    with open(os.path.join(output_path, "README.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # nunca derruba a gravacao por causa do metadata
        print(f"[AVISO] Falha ao gerar metadata.json/README.md: {exc}", file=sys.stderr)
        sys.exit(0)
