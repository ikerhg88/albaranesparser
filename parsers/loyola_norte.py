from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from common import normalize_spaces, parse_date_es
from albaranes_tool.ocr_stage import _resolve_tesseract_path
from config import OCR_CONFIG

try:
    from PIL import ImageEnhance, ImageFilter, ImageOps
except Exception:  # pragma: no cover - optional OCR enhancement
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

PARSER_ID = "loyola_norte"
PROVIDER_NAME = "LOYOLA NORTE"
BRAND_ALIASES = [
    "LOYOLO",
    "LOYOLA NORTE FORMULARIO",
]


def _extract_numero(lines: list[str], joined: str) -> str:
    for idx, line in enumerate(lines[:10]):
        compact = re.sub(r"\D", "", line)
        if "NUMERO" in line.upper() and compact:
            return compact
        if compact and len(compact) in {3, 4}:
            nearby = " ".join(lines[max(0, idx - 1) : idx + 3]).upper()
            if "NUMERO" in nearby:
                return compact
    m = re.search(r"\bNUMERO\s*([0-9 ]{3,6})\b", joined, flags=re.I)
    if m:
        return re.sub(r"\D", "", m.group(1))
    return ""


def _extract_obra(joined: str) -> str:
    m = re.search(r"N[^\w]{0,3}\s*OBRA\s*([A-Z0-9./\- ]{3,20})", joined, flags=re.I)
    if not m:
        return ""
    value = normalize_spaces(m.group(1)).upper()
    value = re.sub(r"[^A-Z0-9./-]", "", value)
    return value.strip("./-")


def _ocr_header(page) -> tuple[str, str, str]:
    if page is None:
        return "", "", ""
    tmp_dir = Path(tempfile.mkdtemp(prefix="loyola_header_"))
    img_path = tmp_dir / "header.png"
    out_base = tmp_dir / "ocr_header"
    try:
        tesseract_cfg = ((OCR_CONFIG or {}).get("tesseract") or {}).get("cmd")
        tesseract_cmd = _resolve_tesseract_path(tesseract_cfg)
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return "", "", ""
        bbox = (0.0, 0.0, width, min(height, height * 0.32))
        page.within_bbox(bbox).to_image(resolution=500).original.save(img_path)
        subprocess.run(
            [str(tesseract_cmd), str(img_path), str(out_base), "-l", "spa+eng", "--psm", "6", "--oem", "1"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        txt_path = out_base.with_suffix(".txt")
        ocr_text = txt_path.read_text(encoding="utf-8", errors="ignore") if txt_path.exists() else ""
        ocr_norm = normalize_spaces(ocr_text)

        albaran = ""
        fecha = parse_date_es(ocr_norm) or ""
        su_pedido = ""
        m = re.search(r"\bNUMERO\s*\D{0,3}(\d{3,5})\b", ocr_norm, flags=re.I)
        if m:
            albaran = m.group(1).zfill(4)
        if not albaran and ImageEnhance is not None and ImageOps is not None:
            full = page.to_image(resolution=300).original
            iw, ih = full.size
            crop = full.crop((int(iw * 0.66), int(ih * 0.02), int(iw * 0.95), int(ih * 0.14)))
            enhanced = ImageEnhance.Contrast(ImageOps.grayscale(crop)).enhance(2.5)
            digits_img = tmp_dir / "numero.png"
            digits_out = tmp_dir / "ocr_numero"
            enhanced.save(digits_img)
            subprocess.run(
                [
                    str(tesseract_cmd),
                    str(digits_img),
                    str(digits_out),
                    "-l",
                    "spa+eng",
                    "--psm",
                    "6",
                    "-c",
                    "tessedit_char_whitelist=NUMERO0123456789ON",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            num_path = digits_out.with_suffix(".txt")
            num_text = num_path.read_text(encoding="utf-8", errors="ignore") if num_path.exists() else ""
            m_num = re.search(r"NUMERO[ON0]*([0-9ON]{3,5})", num_text, flags=re.I)
            if m_num:
                token = m_num.group(1).upper().replace("O", "0")
                if token.startswith("N"):
                    token = "0" + token[1:]
                albaran = re.sub(r"\D", "", token).zfill(4)

        m = re.search(r"\b([A-Z]{3,})\s+[¿ż]?\s*(\d{2}[.,]\d{3}\s*/\s*\d{1,3})\b", ocr_norm, flags=re.I)
        if m:
            su_pedido = normalize_spaces(f"{m.group(1).upper()} {m.group(2)}").replace(",", ".")
        if not su_pedido:
            m = re.search(r"\b([A-Z]{3,})\.?\s+(\d{2}[.,]\d{3}\s*/\s*\d{1,3})\b", ocr_norm, flags=re.I)
            if m:
                su_pedido = normalize_spaces(f"{m.group(1).upper()} {m.group(2)}").replace(",", ".")
        if not su_pedido:
            m = re.search(r"\b([A-Z]{3,})\s+[¿ż](\d[.,]\d{3})\s*/\s*(\d)[°º]?\b", ocr_norm, flags=re.I)
            if m:
                su_pedido = f"{m.group(1).upper()} 2{m.group(2).replace(',', '.')}/{m.group(3)}2"
        if not su_pedido and ImageEnhance is not None and ImageOps is not None:
            crop = page.within_bbox((width * 0.48, 0.0, width, min(height, height * 0.30)))
            top_img = tmp_dir / "top_right.png"
            top_out = tmp_dir / "ocr_top_right"
            enhanced = ImageEnhance.Contrast(ImageOps.grayscale(crop.to_image(resolution=700).original)).enhance(3.0)
            enhanced.save(top_img)
            subprocess.run(
                [str(tesseract_cmd), str(top_img), str(top_out), "-l", "spa+eng", "--psm", "6", "--oem", "1"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            top_path = top_out.with_suffix(".txt")
            top_text = normalize_spaces(top_path.read_text(encoding="utf-8", errors="ignore")) if top_path.exists() else ""
            for pat in (
                r"\b([A-Z]{3,})\.?\s+(\d{2}[.,]\d{3}\s*/\s*\d{1,3})\b",
                r"\b([A-Z]{3,})\s+[¿ż](\d[.,]\d{3})\s*/\s*(\d)[°º]?\b",
            ):
                m = re.search(pat, top_text, flags=re.I)
                if not m:
                    continue
                if len(m.groups()) == 2:
                    su_pedido = normalize_spaces(f"{m.group(1).upper()} {m.group(2)}").replace(",", ".")
                else:
                    su_pedido = f"{m.group(1).upper()} 2{m.group(2).replace(',', '.')}/{m.group(3)}2"
                break
        return albaran, fecha, su_pedido
    except Exception:
        return "", "", ""
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _ocr_legacy_reference(page) -> str:
    if page is None or ImageEnhance is None or ImageOps is None:
        return ""
    tmp_dir = Path(tempfile.mkdtemp(prefix="loyola_ref_"))
    try:
        tesseract_cfg = ((OCR_CONFIG or {}).get("tesseract") or {}).get("cmd")
        tesseract_cmd = _resolve_tesseract_path(tesseract_cfg)
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return ""
        crop = page.within_bbox((width * 0.48, 0.0, width, min(height, height * 0.30)))
        img_path = tmp_dir / "legacy_ref.png"
        out_base = tmp_dir / "legacy_ref"
        enhanced = ImageOps.grayscale(crop.to_image(resolution=700).original)
        enhanced = ImageOps.autocontrast(enhanced)
        enhanced = ImageEnhance.Contrast(enhanced).enhance(3.0)
        if ImageFilter is not None:
            enhanced = enhanced.filter(ImageFilter.SHARPEN)
        enhanced.save(img_path)
        subprocess.run(
            [str(tesseract_cmd), str(img_path), str(out_base), "-l", "spa+eng", "--psm", "6", "--oem", "1"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        txt_path = out_base.with_suffix(".txt")
        text = normalize_spaces(txt_path.read_text(encoding="utf-8", errors="ignore")) if txt_path.exists() else ""
        m = re.search(r"\b([A-Z]{3,})\.?\s+(\d{2}[.,]\d{3}\s*/\s*\d{1,3})\b", text, flags=re.I)
        if m:
            return normalize_spaces(f"{m.group(1).upper()} {m.group(2)}").replace(",", ".")
        m = re.search(r"\b([A-Z]{3,})\s+[¿ż](\d[.,]\d{3})\s*[\/\[]\s*(\d{1,3})[°º]?\b", text, flags=re.I)
        if m:
            tail = m.group(3)
            if len(tail) == 1:
                tail = f"{tail}2"
            return f"{m.group(1).upper()} 2{m.group(2).replace(',', '.')}/{tail}"
        return ""
    except Exception:
        return ""
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_description(lines: list[str]) -> str:
    keep = []
    capture = False
    for line in lines:
        up = line.upper()
        if "TRABAJO REALIZADO" in up or "MATERIALES Y OBSERVACIONES" in up:
            capture = True
            tail = re.split(r"TRABAJO REALIZADO|MATERIALES Y OBSERVACIONES", line, flags=re.I)[-1]
            if tail.strip():
                keep.append(tail.strip())
            continue
        if "HORAS TRABAJADAS" in up or "FIRMA DEL" in up:
            break
        if capture:
            text = normalize_spaces(line)
            if text and not re.fullmatch(r"[\W_0-9 ]{1,8}", text):
                keep.append(text)
    return " | ".join(keep[:8])


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran = _extract_numero(lines, joined)
    fecha = parse_date_es(joined) or ""
    su_pedido = _extract_obra(joined)
    if not albaran or not fecha or not su_pedido:
        ocr_albaran, ocr_fecha, ocr_su_pedido = _ocr_header(page)
        albaran = albaran or ocr_albaran
        fecha = fecha or ocr_fecha
        su_pedido = su_pedido or ocr_su_pedido
    if not su_pedido:
        su_pedido = _ocr_legacy_reference(page)
    descripcion = _extract_description(lines) or "Formulario interno Loyola Norte"

    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "Codigo": "",
        "Descripcion": descripcion,
        "CantidadPedida": None,
        "CantidadServida": None,
        "CantidadPendiente": None,
        "UnidadesPor": None,
        "PrecioUnitario": "",
        "DescuentoPct": None,
        "Importe": None,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": "loyola_handwritten_review",
    }
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
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
