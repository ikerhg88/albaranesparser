from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from common import normalize_spaces, to_float
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first,
    extract_first_item_row,
    find_header_index,
    normalize_albaran,
    normalize_supedido,
)

PARSER_ID = "leycolan"
PROVIDER_NAME = "LEYCOLAN"
BRAND_ALIASES = [
    "LEYCOLAN",
    "LEYCOLAN S.A.L",
    "ILUMINACION Y CONTROL",
    "INFO@LEYCOLAN.COM",
    "A75141275",
]

_HEADER_NOISE_TOKENS = (
    "CIF",
    "NIF",
    "TEL",
    "FAX",
    "MOVIL",
    "DOMICILIO",
    "DIRECCION",
    "CALLE",
    "POLIG",
    "CODIGO POSTAL",
    "C.P",
)


def _resolve_tesseract_cmd() -> str | None:
    exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    project_root = Path(__file__).resolve().parent.parent
    candidates: list[str] = []
    try:
        from config import OCR_CONFIG as _OCR_CONFIG

        tess_cfg = (_OCR_CONFIG or {}).get("tesseract") or {}
        ocrmypdf_cfg = (_OCR_CONFIG or {}).get("ocrmypdf") or {}
        for raw in (tess_cfg.get("cmd"), ocrmypdf_cfg.get("tesseract_cmd")):
            if isinstance(raw, str) and raw.strip():
                candidates.append(raw.strip())
    except Exception:
        pass

    for raw in candidates:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists():
            return str(candidate)
    found = shutil.which(exe_name)
    return str(found) if found else None


def _ocr_supedido_text(page) -> str:
    tess_cmd = _resolve_tesseract_cmd()
    if not tess_cmd:
        return ""
    tmp_pdf_render: Path | None = None
    try:
        import fitz  # type: ignore

        pdf_stream = getattr(getattr(page, "pdf", None), "stream", None)
        pdf_name = getattr(pdf_stream, "name", None)
        if pdf_name:
            doc = fitz.open(str(pdf_name))
            try:
                pix = doc[int(page.page_number) - 1].get_pixmap(dpi=300)
            finally:
                doc.close()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                tmp_pdf_render = Path(tmp_img.name)
            pix.save(str(tmp_pdf_render))
    except Exception:
        tmp_pdf_render = None

    try:
        if tmp_pdf_render and tmp_pdf_render.exists():
            image_path = tmp_pdf_render
        else:
            pil_img = page.to_image(resolution=300).original.convert("L")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image_path = Path(tmp.name)
            pil_img.save(image_path, format="PNG")
    except Exception:
        return ""
    try:
        proc = subprocess.run(
            [
                tess_cmd,
                str(image_path),
                "stdout",
                "-l",
                "spa+eng",
                "--oem",
                "1",
                "--psm",
                "11",
            ],
            capture_output=True,
            text=False,
            check=False,
        )
        out = proc.stdout.decode("utf-8", "ignore") if proc.stdout else ""
        return out.strip()
    except Exception:
        return ""
    finally:
        try:
            image_path.unlink()
        except Exception:
            pass
        try:
            if tmp_pdf_render and tmp_pdf_render.exists():
                tmp_pdf_render.unlink()
        except Exception:
            pass


def _extract_albaran(lines: list[str], joined: str) -> str:
    raw = extract_first(
        joined,
        [
            r"\b(ALB\s*[-./]?\s*\d{2}\s*[-./]?\s*\d{2,6})\b",
            r"ALBAR[\u00C1A]N[^A-Z0-9]{0,10}([A-Z0-9./-]{4,})",
        ],
    )
    if not raw:
        for line in lines[:14]:
            m = re.search(r"\bALB[-./]?\d{2}[-./]?\d{2,6}\b", line, flags=re.IGNORECASE)
            if m:
                raw = m.group(0)
                break
    return normalize_albaran(raw, compact=True)


def _extract_supedido(lines: list[str], joined: str) -> str:
    def _normalize_obra_code(raw: str) -> str:
        value = normalize_spaces(raw or "").upper()
        if not value:
            return ""
        m = re.search(r"(?<!\d)(\d{2})[./-]?(\d{3})(?:[-/][A-Z0-9]{1,4})?(?!\d)", value)
        if m:
            return f"{m.group(1)}{m.group(2)}"
        return normalize_supedido(value)

    raw = extract_first(
        joined,
        [
            r"(?:N[\u00BAO2]\s*PEDIDO|CODIGO\s+PROVEEDOR)[^A-Z0-9]{0,24}([0-9]{2}[./-]?[0-9]{3}(?:[-/][A-Z0-9]{1,4})?)",
            r"S/?PED(?:IDO)?\.?\s*[:#-]?\s*([A-Z0-9./-]{4,})",
            r"CODIGO\s+PROVEEDOR[^A-Z0-9]{0,8}([A-Z0-9./-]{4,})",
            r"PEDIDO\s*[:#-]?\s*([A-Z0-9./-]{4,})",
        ],
    )
    if raw:
        norm = _normalize_obra_code(raw)
        if norm:
            return norm

    for idx, line in enumerate(lines[:32]):
        up = line.upper()
        if "CODIGO PROVEEDOR" not in up and "PEDIDO" not in up:
            continue
        window = " ".join(lines[idx : idx + 5])
        m = re.search(
            r"(?<!\d)(\d{2})[./](\d{3})(?:[-/][A-Z0-9]{1,4})?(?!\d)",
            window,
            flags=re.IGNORECASE,
        )
        if m:
            return f"{m.group(1)}{m.group(2)}"
        m2 = re.search(r"(?<!\d)(\d{5})(?:[-/][A-Z0-9]{1,4})?(?!\d)", window)
        if m2:
            return m2.group(1)

    # Fallback generico: primer codigo numerico de 5+ digitos en cabecera.
    candidates: list[str] = []
    for line in lines[:24]:
        up = line.upper()
        if any(tok in up for tok in _HEADER_NOISE_TOKENS):
            continue
        for tok in re.findall(r"\b\d{5,}\b", line):
            # Evita codigos demasiado largos (normalmente identificadores fiscales).
            if len(tok) > 8:
                continue
            candidates.append(tok)
    return normalize_supedido(candidates[0] if candidates else "")


def _parse_table_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    header_idx = find_header_index(lines, ["ARTICULO", "DESCRIPCION", "CANTIDAD"])
    if header_idx < 0:
        return []

    items: list[dict] = []
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None:
            current["Descripcion"] = normalize_spaces(current.get("Descripcion", ""))
            items.append(current)
            current = None

    for line in lines[header_idx + 1 :]:
        up = line.upper()
        if any(marker in up for marker in ("TRANSPORTISTA", "BULTOS", "FIRMA", "PORTES DEBIDOS")):
            break
        if not line.strip("-_ /"):
            continue
        m = re.match(r"^(?P<body>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)$", line)
        if m:
            _flush()
            body = normalize_spaces(m.group("body"))
            qty = to_float(m.group("qty"))
            code = ""
            desc = body
            if body.upper().startswith("ONA "):
                desc = body[4:].strip()
            elif re.match(r"^[A-Z]{2,}[-A-Z0-9]*\s+", body):
                first, rest = body.split(" ", 1)
                if re.search(r"\d", first) or first.upper() in {"NODO"}:
                    code = first
                    desc = rest
            current = {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": code,
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": 0.0,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "leycolan_structured",
            }
            continue
        if current is not None:
            current["Descripcion"] = f"{current.get('Descripcion', '')} {line}"

    _flush()
    return items


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = _extract_albaran(lines, joined)
    su_pedido = _extract_supedido(lines, joined)
    if not su_pedido:
        ocr_text = _ocr_supedido_text(page)
        if ocr_text:
            ocr_lines = [normalize_spaces(ln) for ln in ocr_text.splitlines() if ln.strip()]
            su_pedido = _extract_supedido(ocr_lines, " ".join(ocr_lines))
    fecha = default_fecha(lines, joined)

    items = _parse_table_items(lines, page_num, albaran, fecha, su_pedido)
    if items:
        meta = {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "SumaImportesLineas": 0.0,
            "NetoComercialPie": np.nan,
            "TotalAlbaranPie": np.nan,
        }
        return items, meta

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha,
        su_pedido=su_pedido,
        descripcion=" | ".join(lines[:12]),
        importe=0.0,
        parse_warn="leycolan_structured",
    )
