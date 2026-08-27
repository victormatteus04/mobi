#!/usr/bin/env python3
"""Validacao pos-gravacao: gaps de tempo, taxa observada vs esperada
(config/topics.yaml), e topicos obrigatorios ausentes.

Nao decodifica o payload das mensagens (so os timestamps que o proprio
rosbag2 registrou), entao e rapido mesmo em bags grandes com imagem/nuvem.
"""
import argparse
import json
import os
import sys

import rosbag2_py
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topics_config  # noqa: E402

GAP_RATIO_WARN = 4.0  # gap > N vezes o intervalo mediano = suspeito
MIN_GAP_ABS_S = 0.05  # e o gap em si tem que passar de 50ms, senao e so jitter
MIN_RATE_RATIO_WARN = 0.6  # taxa observada < 60% da esperada = suspeito


def open_reader(bag_path):
    storage_options = rosbag2_py.StorageOptions(uri=bag_path, storage_id="mcap")
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)
    return reader


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
    return sorted_vals[idx]


def analyze_topic(timestamps_ns):
    timestamps_ns.sort()
    n = len(timestamps_ns)
    if n == 0:
        return {"count": 0}
    duration_s = (timestamps_ns[-1] - timestamps_ns[0]) / 1e9
    diffs = [(timestamps_ns[i + 1] - timestamps_ns[i]) / 1e9 for i in range(n - 1)]
    diffs_sorted = sorted(diffs)
    median_dt = percentile(diffs_sorted, 0.5) if diffs else None
    max_gap = max(diffs) if diffs else 0.0
    gap_threshold = median_dt * GAP_RATIO_WARN if median_dt else None
    # Precisa passar do limiar relativo (N x mediana) E de um piso absoluto:
    # se a mediana ficar perto de zero (timestamps duplicados/arredondados,
    # comum em topicos de alta taxa), "4x a mediana" vira quase zero e
    # qualquer micro-jitter normal passaria a contar como gap.
    gap_count = sum(
        1 for d in diffs
        if gap_threshold and d > gap_threshold and d > MIN_GAP_ABS_S
    )
    observed_rate = (n - 1) / duration_s if duration_s > 0 else None
    return {
        "count": n,
        "duration_s": round(duration_s, 3),
        "observed_rate_hz": round(observed_rate, 2) if observed_rate else None,
        "median_interval_s": round(median_dt, 4) if median_dt else None,
        "max_gap_s": round(max_gap, 3),
        "gaps_over_threshold": gap_count,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag-path", required=True)
    p.add_argument("--topics-config", default=os.environ.get(
        "MOBI_TOPICS_CONFIG", "/etc/mobi/topics.yaml"))
    p.add_argument("--metadata", default=None,
                    help="metadata.json da sessao (default: <bag-path>/metadata.json)")
    args = p.parse_args()

    reader = open_reader(args.bag_path)
    type_map = {m.name: m.type for m in reader.get_all_topics_and_types()}

    timestamps = {t: [] for t in type_map}
    while reader.has_next():
        topic, _data, t = reader.read_next()
        timestamps[topic].append(t)

    topic_reports = {}
    for topic, stamps in timestamps.items():
        report = analyze_topic(stamps)
        report["type"] = type_map[topic]
        topic_reports[topic] = report

    # taxa/obrigatoriedade esperada, a partir do topics.yaml
    expected_rate = {}
    required_topics_by_group = {}
    try:
        config = topics_config.load_config(args.topics_config)
        for entry in topics_config.all_entries(config):
            if "rate_hz" in entry:
                expected_rate[entry["topic"]] = entry["rate_hz"]
            if entry.get("required"):
                required_topics_by_group.setdefault(entry["group"], []).append(entry["topic"])
    except (FileNotFoundError, KeyError) as exc:
        print(f"[AVISO] nao foi possivel carregar topics.yaml: {exc}", file=sys.stderr)

    metadata_path = args.metadata or os.path.join(args.bag_path, "metadata.json")
    recorded_groups = []
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            recorded_groups = json.load(f).get("recording", {}).get("sensor_groups", [])

    findings = []
    for topic, rate in expected_rate.items():
        report = topic_reports.get(topic)
        if not report or report["count"] == 0:
            continue
        observed = report.get("observed_rate_hz")
        if observed is not None and observed < rate * MIN_RATE_RATIO_WARN:
            findings.append({
                "level": "warning",
                "topic": topic,
                "message": f"taxa observada {observed}Hz bem abaixo da esperada {rate}Hz",
            })
        report["expected_rate_hz"] = rate

    for topic, report in topic_reports.items():
        if report["count"] > 0 and report.get("gaps_over_threshold", 0) > 0:
            findings.append({
                "level": "warning",
                "topic": topic,
                "message": f"{report['gaps_over_threshold']} gap(s) de tempo suspeitos "
                           f"(maior: {report['max_gap_s']}s, mediana normal: "
                           f"{report['median_interval_s']}s)",
            })

    for group in recorded_groups:
        for topic in required_topics_by_group.get(group, []):
            if topic not in type_map or topic_reports.get(topic, {}).get("count", 0) == 0:
                findings.append({
                    "level": "error",
                    "topic": topic,
                    "message": f"topico obrigatorio do grupo '{group}' ausente ou vazio na bag",
                })

    status = "ok"
    if any(f["level"] == "error" for f in findings):
        status = "error"
    elif any(f["level"] == "warning" for f in findings):
        status = "warning"

    report = {
        "status": status,
        "findings": findings,
        "topics": topic_reports,
    }

    out_path = os.path.join(args.bag_path, "validation_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"[VALIDATE] status: {status}")
    for finding in findings:
        print(f"[VALIDATE] {finding['level'].upper()}: {finding['topic']}: {finding['message']}")
    if not findings:
        print("[VALIDATE] nenhum problema encontrado.")


if __name__ == "__main__":
    main()
