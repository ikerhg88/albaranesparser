# debugkit.py
from pathlib import Path
import json
from datetime import datetime

try:
    from config import DEBUG_ENABLED, DEBUG_LEVEL, DEBUG_DIR
except Exception:
    DEBUG_ENABLED, DEBUG_LEVEL, DEBUG_DIR = True, "basic", "debug"

ROOT = Path(DEBUG_DIR)

def _on(level="basic"):
    if not DEBUG_ENABLED:
        return False
    if DEBUG_LEVEL == "off":
        return False
    if DEBUG_LEVEL == "basic":
        return level in ("basic",)
    if DEBUG_LEVEL == "verbose":
        return level in ("basic", "verbose")
    return False

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def dbg_page_text(pdf_name: str, page: int, lines: list[str], joined: str):
    """Siempre que el debug esté ON, vuelca texto por página (líneas y unido)."""
    if not _on("basic"): return
    d = ROOT / "pages" / Path(pdf_name).stem
    _ensure_dir(d)
    (d / f"p{page:02d}_lines.txt").write_text(
        "\n".join(f"{i+1:03d}: {ln}" for i, ln in enumerate(lines)), encoding="utf-8")
    (d / f"p{page:02d}_joined.txt").write_text(joined or "", encoding="utf-8")

def dbg_detect_step(pdf_name: str, page: int, step: str, info: dict):
    """Traza paso a paso de la detección (init)."""
    if not _on("verbose"): return
    d = ROOT / "pages" / Path(pdf_name).stem
    _ensure_dir(d)
    payload = {"ts": datetime.now().isoformat(timespec="seconds"), "step": step, **(info or {})}
    f = d / f"p{page:02d}_detect.log"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

def dbg_detect_result(pdf_name: str, page: int, detected: str, parser_id: str | None):
    """Resultado final de la detección por página."""
    if not _on("basic"): return
    d = ROOT / "pages" / Path(pdf_name).stem
    _ensure_dir(d)
    payload = {"detected_proveedor": detected or "", "resolved_parser": (parser_id or "")}
    (d / f"p{page:02d}_detect.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def dbg_parser_page(parser: str, page: int, header: dict | None = None,
                    items: list[dict] | None = None, meta: dict | None = None):
    """Volcado de cada parser por página: header, items (JSON+TSV), meta."""
    if not _on("basic"): return
    d = ROOT / f"parser_{parser}"
    _ensure_dir(d)
    if header is not None:
        (d / f"p{page:02d}_header.json").write_text(json.dumps(header, ensure_ascii=False, indent=2), encoding="utf-8")
    if items is not None:
        (d / f"p{page:02d}_items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        # TSV para inspección rápida
        cols = sorted({k for it in items for k in it.keys()}) if items else []
        tsv = ["\t".join(cols)]
        for it in (items or []):
            tsv.append("\t".join("" if it.get(c) is None else str(it.get(c)) for c in cols))
        (d / f"p{page:02d}_items.tsv").write_text("\n".join(tsv), encoding="utf-8")
    if meta is not None:
        (d / f"p{page:02d}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def dbg_run_summary(summary: dict, errors: list[dict]):
    """Resumen de ejecución (conteos y errores)."""
    if not _on("basic"): return
    d = ROOT / "run"
    _ensure_dir(d)
    (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # Informe legible
    lines = []
    lines.append("# RESUMEN")
    for k, v in summary.items():
        lines.append(f"- {k}: {v}")
    lines.append("\n# ERRORES")
    if not errors:
        lines.append("(sin errores)")
    else:
        for e in errors:
            lines.append(f"- {e.get('pdf')} p.{e.get('page')}: {e.get('msg')}  "
                         f"[detect={e.get('detected')}, parser={e.get('parser_id')}, items={e.get('items')}]")
    (d / "errors_report.txt").write_text("\n".join(lines), encoding="utf-8")
