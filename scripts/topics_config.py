#!/usr/bin/env python3
"""Fonte unica de leitura de config/topics.yaml.

Usado como modulo importavel (pelo dashboard) e como CLI (pelos scripts
bash record-bag.sh / check-sensors.sh), para nao duplicar a lista de
grupos/topicos em dois lugares.
"""
import argparse
import os
import sys

import yaml

DEFAULT_CONFIG_PATH = os.environ.get("MOBI_TOPICS_CONFIG", "/etc/mobi/topics.yaml")


def load_config(path=None):
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("sensor_groups", {})


def group_names(config=None):
    config = config if config is not None else load_config()
    return list(config.keys())


def group_label(name, config=None):
    config = config if config is not None else load_config()
    return config.get(name, {}).get("label", name)


def _entries(config, groups, include_optional):
    seen = set()
    out = []
    for group in groups:
        spec = config.get(group)
        if spec is None:
            raise KeyError(f"grupo desconhecido: {group}")
        entries = list(spec.get("required", []))
        if include_optional:
            entries += list(spec.get("optional", []))
        for entry in entries:
            topic = entry["topic"]
            if topic not in seen:
                seen.add(topic)
                out.append(entry)
    return out


def topics_for(groups, include_optional=True, config=None):
    config = config if config is not None else load_config()
    return [e["topic"] for e in _entries(config, groups, include_optional)]


def required_for(groups, config=None):
    config = config if config is not None else load_config()
    out = []
    for group in groups:
        spec = config.get(group)
        if spec is None:
            raise KeyError(f"grupo desconhecido: {group}")
        for entry in spec.get("required", []):
            out.append({
                "topic": entry["topic"],
                "label": entry.get("label", entry["topic"]),
                "type": entry["type"],
                "group": group,
            })
    return out


def all_entries(config=None):
    """Todo topico (required+optional) de todo grupo, com o nome do grupo."""
    config = config if config is not None else load_config()
    out = []
    for group, spec in config.items():
        for entry in spec.get("required", []):
            out.append({**entry, "group": group, "required": True})
        for entry in spec.get("optional", []):
            out.append({**entry, "group": group, "required": False})
    return out


def _cmd_topics(args):
    groups = args.groups.split(",") if args.groups else group_names()
    for topic in topics_for(groups, include_optional=not args.required_only):
        print(topic)


def _cmd_required(args):
    groups = args.groups.split(",") if args.groups else group_names()
    for entry in required_for(groups):
        print(f"{entry['topic']}\t{entry['label']}\t{entry['type']}")


def _cmd_groups(_args):
    config = load_config()
    for name in config:
        print(f"{name}\t{group_label(name, config)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="caminho do topics.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_topics = sub.add_parser("topics", help="lista topicos (required+optional) dos grupos")
    p_topics.add_argument("groups", nargs="?", default="", help="grupos separados por virgula")
    p_topics.add_argument("--required-only", action="store_true")
    p_topics.set_defaults(func=_cmd_topics)

    p_required = sub.add_parser("required", help="lista 'topico<TAB>label' obrigatorios dos grupos")
    p_required.add_argument("groups", nargs="?", default="", help="grupos separados por virgula")
    p_required.set_defaults(func=_cmd_required)

    p_groups = sub.add_parser("groups", help="lista 'grupo<TAB>label' disponiveis")
    p_groups.set_defaults(func=_cmd_groups)

    args = parser.parse_args()
    global DEFAULT_CONFIG_PATH
    if args.config:
        DEFAULT_CONFIG_PATH = args.config
    try:
        args.func(args)
    except KeyError as e:
        print(f"erro: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
