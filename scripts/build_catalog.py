#!/usr/bin/env python3
"""Escaneia bags/*/ (cada uma com metadata.json) e gera um catalogo estatico
(index.html + catalog.json) para navegar as sessoes sem abrir cada bag.
Portatil: so referencias relativas, funciona local ou subido pra qualquer
lugar (Drive, servidor, bucket) sem mudar nada.
"""
import argparse
import glob
import html
import json
import os

STATUS_COLOR = {"ok": "#3ecf72", "warning": "#e0b13c", "error": "#e0503c", None: "#4a4f5a"}
STATUS_LABEL = {"ok": "OK", "warning": "AVISO", "error": "ERRO", None: "sem validacao"}


def fmt_bytes(n):
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def load_sessions(bags_dir):
    sessions = []
    for meta_path in sorted(glob.glob(os.path.join(bags_dir, "*", "metadata.json"))):
        session_dir = os.path.dirname(meta_path)
        name = os.path.basename(session_dir)
        with open(meta_path) as f:
            metadata = json.load(f)

        validation = None
        val_path = os.path.join(session_dir, "validation_report.json")
        if os.path.exists(val_path):
            with open(val_path) as f:
                validation = json.load(f)

        thumb_rel = None
        thumb_path = os.path.join(session_dir, "preview", "thumbnail.jpg")
        if os.path.exists(thumb_path):
            thumb_rel = f"{name}/preview/thumbnail.jpg"

        sessions.append({
            "name": name,
            "metadata": metadata,
            "validation_status": validation["status"] if validation else None,
            "validation_findings": validation["findings"] if validation else [],
            "thumbnail": thumb_rel,
        })
    sessions.sort(key=lambda s: s["metadata"]["session"].get("recorded_start_utc") or s["name"],
                  reverse=True)
    return sessions


def render_html(sessions):
    cards = []
    for s in sessions:
        m = s["metadata"]
        sess = m["session"]
        rec = m["recording"]
        status = s["validation_status"]
        color = STATUS_COLOR.get(status)
        label = STATUS_LABEL.get(status)
        thumb_html = (
            f'<img src="{html.escape(s["thumbnail"])}" class="thumb">'
            if s["thumbnail"] else '<div class="thumb thumb-empty">sem preview</div>'
        )
        groups = ", ".join(rec.get("sensor_groups") or []) or "(topicos avulsos)"
        findings_html = ""
        if s["validation_findings"]:
            items = "".join(
                f'<li class="finding-{f["level"]}">{html.escape(f["topic"])}: {html.escape(f["message"])}</li>'
                for f in s["validation_findings"]
            )
            findings_html = f'<ul class="findings">{items}</ul>'

        cards.append(f"""
        <div class="card">
          <a href="{html.escape(s['name'])}/README.md">{thumb_html}</a>
          <div class="card-body">
            <div class="card-title">
              <a href="{html.escape(s['name'])}/README.md">{html.escape(s['name'])}</a>
              <span class="badge" style="background:{color}">{label}</span>
            </div>
            <div class="meta">
              {html.escape(sess.get('recorded_start_utc') or '-')} &middot;
              {sess.get('duration_s') or '?'}s &middot;
              {fmt_bytes(m.get('total_size_bytes'))}
            </div>
            <div class="meta">Sensores: {html.escape(groups)}</div>
            <div class="meta">Local: {html.escape(sess.get('location') or '-')} &middot;
              Operador: {html.escape(sess.get('operator') or '-')}</div>
            {findings_html}
          </div>
        </div>""")

    return f"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Catalogo de datasets - Mobi</title>
<style>
  body {{ font-family: -apple-system, Roboto, Arial, sans-serif; background:#14161a; color:#e7e9ee; margin:0; padding:24px; }}
  h1 {{ font-weight:600; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap:16px; }}
  .card {{ background:#1c1f26; border:1px solid #2b2f38; border-radius:10px; overflow:hidden; display:flex; }}
  .thumb {{ width:140px; height:140px; object-fit:cover; flex:none; }}
  .thumb-empty {{ display:flex; align-items:center; justify-content:center; color:#8b93a3; font-size:0.8rem; }}
  .card-body {{ padding:10px 12px; flex:1; min-width:0; }}
  .card-title {{ display:flex; justify-content:space-between; align-items:center; gap:8px; font-weight:600; }}
  .card-title a {{ color:#e7e9ee; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .badge {{ font-size:0.7rem; padding:2px 8px; border-radius:10px; color:#0c0d0f; font-weight:700; flex:none; }}
  .meta {{ color:#8b93a3; font-size:0.82rem; margin-top:4px; }}
  .findings {{ margin:8px 0 0; padding-left:16px; font-size:0.78rem; }}
  .finding-warning {{ color:#e0b13c; }}
  .finding-error {{ color:#e0503c; }}
</style>
</head>
<body>
  <h1>Catalogo de datasets - Mobi</h1>
  <p style="color:#8b93a3">{len(sessions)} sessao(oes)</p>
  <div class="grid">
    {"".join(cards)}
  </div>
</body>
</html>
"""


def log(msg):
    print(msg, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bags-dir", default="/bags")
    args = p.parse_args()

    log(f"[CATALOG] escaneando {args.bags_dir}/*/metadata.json ...")
    sessions = load_sessions(args.bags_dir)
    log(f"[CATALOG] {len(sessions)} sessao(oes) encontrada(s), gerando index.html/catalog.json")

    with open(os.path.join(args.bags_dir, "catalog.json"), "w") as f:
        json.dump({"sessions": [
            {"name": s["name"], "metadata": s["metadata"],
             "validation_status": s["validation_status"]}
            for s in sessions
        ]}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(os.path.join(args.bags_dir, "index.html"), "w") as f:
        f.write(render_html(sessions))

    log(f"[CATALOG] concluido: {len(sessions)} sessao(oes) -> {args.bags_dir}/index.html")


if __name__ == "__main__":
    main()
