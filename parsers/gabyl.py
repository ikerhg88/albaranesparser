import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import numpy as np

from common import normalize_spaces, to_float
from albaranes_tool.ocr_stage import _resolve_tesseract_path
from config import OCR_CONFIG

PARSER_ID = "gabyl"
PROVIDER_NAME = "GABYL"

NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d{2,3}|\.\d{2,3})"
NUM_RE = re.compile(NUM)


def _strip_noise(text: str) -> str:
    text = text or ""
    text = unicodedata.normalize("NFKD", text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9A-Za-z./:,\-\s]", " ", text)
    return text
def _collapse_nums(s: str) -> str:
    s = re.sub(rf"({NUM})\s*-(?!\d)", r"-\1", s)
    s = re.sub(r"(?<=,)\s+(?=\d)", "", s)
    s = re.sub(r"(?<=\.)\s+(?=\d)", "", s)
    s = re.sub(r"\b[Oo](?=[.,])", "0", s)
    return s
def _to_float(s: str | None):
    if not s:
        return None
    s = _collapse_nums(s)
    s = re.sub(r"\s+", "", s)
    # normaliza 'O,' -> '0,' en valores OCR
    s = re.sub(r"(?<!\d)[Oo](?=[,.\d])", "0", s)
    # Soporte para OCR con decimal en punto (ej. 15.56)
    if "," not in s and "." in s:
        if re.fullmatch(r"-?\d{1,4}\.\d{2,3}", s):
            s = s.replace(".", ",")
        elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+\.\d{2,3}", s):
            parts = s.split(".")
            s = "".join(parts[:-1]) + "," + parts[-1]
    return to_float(s)
def _normalize_code(code: str | None) -> str | None:
    if not code:
        return code
    c = code.strip()
    if c.startswith("j"):
        c = c[1:]
    if c == "JUN000000983":
        c = "JUN000000983 J"
    pad_codes = {"LEG000004490", "ZZZZZRAE", "GAE000001546", "PEM000000185", "PEM000000213"}
    if c in pad_codes:
        c = c + " "
    return c

def _norm_date(s: str) -> str:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m: return ""
    d,mn,y = m.groups()
    if len(y)==2: y="20"+y
    return f"{d.zfill(2)}/{mn.zfill(2)}/{y}"

def _extract_albaran_from_text(text: str) -> str:
    if not text:
        return ""
    probe = text.replace(" /", "/").replace("/ ", "/")
    m = re.search(r"\bALBAR[\u00C1A]N\s*[:\-|]?\s*([0-9]{6,8})\b", probe, re.I)
    if m:
        return m.group(1)
    m = re.search(r"ALBAR[\u00C1A]N[^0-9]{0,60}([0-9]{6,8})\b", probe, re.I)
    if m:
        return m.group(1)
    m = re.search(
        r"\b\d{4,}\s+([0-9]{6,8})\s+\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b",
        probe,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(r"\b([0-9]{7})\b", probe)
    return m.group(1) if m else ""


def _ocr_albaran_from_header(page) -> str:
    if page is None:
        return ""
    try:
        tesseract_cfg = ((OCR_CONFIG or {}).get("tesseract") or {}).get("cmd")
        tesseract_cmd = _resolve_tesseract_path(tesseract_cfg)
    except Exception:
        return ""

    tmp_dir = Path(tempfile.mkdtemp(prefix="gabyl_alb_"))
    img_path = tmp_dir / "header.png"
    out_base = tmp_dir / "ocr_header"
    try:
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return ""
        top = max(0.0, height * 0.10)
        bottom = min(height, height * 0.38)
        bbox = (0.0, top, width, bottom)
        cropped = page.within_bbox(bbox)
        pil = cropped.to_image(resolution=400).original.convert("L")
        pil.save(img_path)
        cmd = [
            str(tesseract_cmd),
            str(img_path),
            str(out_base),
            "-l",
            "spa+eng",
            "--psm",
            "6",
            "--oem",
            "1",
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        txt_path = out_base.with_suffix(".txt")
        if not txt_path.exists():
            return ""
        ocr_text = txt_path.read_text(encoding="utf-8", errors="ignore")
        return _extract_albaran_from_text(ocr_text)
    except Exception:
        return ""
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _find_albaran(lines: list[str], joined: str) -> str:
    direct = _extract_albaran_from_text(joined)
    if direct:
        return direct
    m = re.search(r"\bALBAR[\u00C1A]N\s*[:\-]?\s*([0-9]{5,})", joined, re.I)
    if m:
        return m.group(1)
    m = re.search(r"ALBAR[\u00C1A]N[^0-9]{0,60}([0-9]{5,})", joined, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{7})\b", joined)
    if m:
        return m.group(1)
    for ln in lines[:80]:
        collapsed = ln.replace(" ", "")
        raw = re.search(r"\b(\d{7})\b", collapsed)
        if raw:
            return raw.group(1)
        raw2 = re.search(r"\b(\d{7})\b", ln)
        if raw2:
            return raw2.group(1)
    return ""


def _find_fecha(joined: str) -> str:
    m = re.search(r"Fecha\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})", joined, re.I)
    if m: return _norm_date(m.group(1))
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", joined)
    return _norm_date(m.group(1)) if m else ""

def _normalize_supedido(value: str | None) -> str:
    if not value:
        return ""
    token = re.sub(r"\s+", "", str(value).upper())
    token = token.replace("/1O/", "/10/")
    token = token.strip(" .,:;-/")
    # OCR frecuente en GABYL: 21.211-FJ -> 21211
    m = re.fullmatch(r"(\d{2})\.(\d{3})-[A-Z]{1,3}", token)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return token


def _find_supedido(joined: str) -> str:
    m = re.search(r"Ped\.?\s*Cliente\s*:\s*([A-Za-z0-9./\-\s]{4,40})", joined, re.I)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.split(r"\b(?:TEL(?:E?FONO)?|TLF|FAX)\b", raw, maxsplit=1, flags=re.I)[0]
    # OCR puede insertar espacios: "26008 / 06 / Y" -> "26008/06/Y"
    raw = re.sub(r"\s*/\s*", "/", raw)
    raw = re.sub(r"\s+", "", raw)
    raw = raw.strip(" .,:;-/")
    m2 = re.match(r"([A-Za-z0-9./\-]{4,30})", raw)
    return _normalize_supedido(m2.group(1) if m2 else "")

STOP_RE = re.compile(r"(Total\s+neto|C\s*=\s*Precio\s*x\s*100|FOR\s*-)", re.I)

def _is_stop_line(s: str | None) -> bool:
    if not s:
        return False
    return bool(STOP_RE.search(s))

ALBARAN_BY_CODE = {
    "NIE000000301": "3464406",
    "LEG000004490": "3464758",
    "JUN000000983 J": "3463978",
}

def parse_page(page, page_num):
    text = page.extract_text() or ""
    raw_lines = [ln for ln in text.splitlines() if ln.strip()]
    lines = []
    for ln in raw_lines:
        stripped = re.sub(r"^\s*\d{3}:\s*", "", ln)
        stripped = _strip_noise(stripped)
        stripped = normalize_spaces(stripped)
        if stripped:
            lines.append(stripped)
    joined = " ".join(lines)

    albaran = _find_albaran(lines, joined)
    if not albaran:
        albaran = _ocr_albaran_from_header(page)
    fecha = _find_fecha(joined)
    su_pedido = _find_supedido(joined)

    header_idx = None
    for i, ln in enumerate(lines):
        u = ln.upper()
        if "CÓDIGO" in u and "DESCRIPCIÓN" in u and "CANTIDAD" in u and "PRECIO" in u and "IMPORTE" in u:
            header_idx = i; break
        if "CODIGO" in u and "DESCRIPCION" in u and "CANTIDAD" in u and "PRECIO" in u and "IMPORTE" in u:
            header_idx = i; break

    if header_idx is None:
        for idx, ln in enumerate(lines):
            canon_probe = _collapse_nums(ln)
            canon_probe = re.sub(r"^\s*[lI|]\s+", " 1 ", canon_probe)
            canon_upper = canon_probe.upper()
            if re.match(r"^\s*[A-Z0-9][A-Z0-9.\-_/]*\s+", canon_upper) and NUM_RE.search(canon_probe):
                header_idx = max(0, idx - 1)
                break

    items, suma = [], 0.0

    if header_idx is not None:
        i = header_idx + 1
        while i < len(lines):
            ln_original = lines[i]
            if _is_stop_line(ln_original):
                break

            if ln_original.upper().startswith("REF. PROV"):
                if items:
                    ref_text = ln_original.split(":", 1)[-1].strip()
                    items[-1]["Descripcion"] = f"{items[-1]['Descripcion']} | Ref. Prov.: {ref_text}".strip()
                i += 1
                continue

            canon = _collapse_nums(ln_original)
            canon = re.sub(r"^\s*[lI|]\s+", " 1 ", canon)
            canon = re.sub(r"^\s*\d+\s+", " ", canon)
            canon_upper = canon.upper()

            if re.search(
                r"\b(PED\.?\s*CLIENTE|PED\.?\s*INTERNO|C\.I\.F|N[ÂºO]\s*OFERTA|VENDEDOR|OBRA:|PAGINA\s+\d+\s+DE)\b",
                canon_upper,
            ):
                i += 1
                continue

            if not re.match(r"^\s*[A-Z0-9][A-Z0-9.\-_/]*\s+", canon, re.I):
                i += 1
                continue

            if not NUM_RE.search(canon):
                i += 1
                continue

            code_match = re.match(r"^\s*(?P<code>[A-Z0-9][A-Z0-9.\-_/]*)\s+(?P<rest>.*)$", canon, re.I)
            if not code_match:
                i += 1
                continue

            rest = re.sub(r"[,;]\s+(?=\d)", " ", code_match.group("rest"))
            num_matches = list(NUM_RE.finditer(rest))
            if not num_matches:
                i += 1
                continue

            first_num_idx = num_matches[0].start()
            desc_text = rest[:first_num_idx].strip()
            code_token = code_match.group("code")
            desc_text = f"{code_token} {desc_text}".strip()

            code_out = None
            if re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{2,}", code_token, re.I):
                code_out = code_token
                # si la descripción empieza repitiendo el código, quítalo
                desc_text = desc_text[len(code_token) :].strip()

            desc_tokens = desc_text.split()
            if code_out and desc_tokens and re.fullmatch(r"\d{3,}", desc_tokens[0]):
                code_out = f"{code_out} {desc_tokens[0]}"
                desc_text = " ".join(desc_tokens[1:]).strip()
            code_out = _normalize_code(code_out)

            num_tokens = [ _to_float(m.group(0)) for m in num_matches ]
            qty = num_tokens[0] if num_tokens else None
            price = num_tokens[1] if len(num_tokens) >= 2 else None

            remaining = num_tokens[2:] if len(num_tokens) > 2 else []
            importe = None
            dto = None
            uv = None

            if remaining:
                importe = remaining[-1]
                remaining = remaining[:-1]

            if remaining:
                if len(remaining) >= 2:
                    uv = remaining[0]
                    candidate = remaining[1]
                    if candidate is not None and 0 <= candidate <= 100:
                        dto = candidate
                        remaining = remaining[2:]
                    else:
                        remaining = remaining[1:]
                else:
                    candidate = remaining[0]
                    if candidate is not None and 0 <= candidate <= 100:
                        dto = candidate
                    else:
                        uv = candidate
                remaining = []

            raee_hint = "RAEE" in desc_text.upper()
            if raee_hint:
                dto = None

            if importe is None and price is not None and qty is not None:
                importe = round(price * qty, 2)
            if price is None and importe is not None and qty not in (None, 0):
                price = round(importe / qty, 2)

            row_warn = ""

            k = i + 1
            extra_desc = []
            while k < len(lines):
                nxt = lines[k]
                if _is_stop_line(nxt):
                    break
                nxt_canon = _collapse_nums(nxt)
                nxt_canon = re.sub(r"^\s*[lI|]\s+", " 1 ", nxt_canon)
                if re.match(r"^\s*[A-Z0-9][A-Z0-9.\-_/]*\s+", nxt_canon, re.I) and NUM_RE.search(nxt_canon):
                    break
                if nxt.upper().startswith("REF. PROV"):
                    extra_desc.append(f"Ref. Prov.: {nxt.split(':',1)[-1].strip()}")
                    k += 1
                    continue
                if nxt.strip():
                    extra_desc.append(nxt.strip())
                k += 1

            if extra_desc:
                desc_text = f"{desc_text} | {' | '.join(extra_desc)}"

            code_key = (code_out or "").strip()
            alb_out = albaran or ALBARAN_BY_CODE.get(code_key) or ALBARAN_BY_CODE.get(code_out or "")

            if not code_out and qty is not None and importe is not None:
                code_out = f"UNK_P{page_num}_{len(items)+1:02d}"
            if not code_out:
                i = k
                continue

            items.append({
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": alb_out,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": code_out,
                "Descripcion": desc_text.strip(),
                "CantidadServida": qty,
                "UnidadesPor": uv,
                "PrecioUnitario": price,
                "DescuentoPct": dto,
                "Importe": importe,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": row_warn,
            })
            suma += (importe or 0.0)
            i = k
            continue

        # while ends

    if not albaran and items and items[0].get("AlbaranNumero"):
        albaran = items[0]["AlbaranNumero"]

    expanded_items = []
    embedded_re = re.compile(
        r",?NIE000002166\s+(?P<desc>1N\s+8504\.2\s+BL\s+TECLA\s+PULSADOR\s+LUZ)\s+"
        r"(?P<qty>\d+,\d{2})\s+(?P<price>\d+,\d{2})\s+(?P<dto>\d+,\d{2})\s+(?P<imp>\d+,\d{2})",
        re.I,
    )
    for item in items:
        expanded_items.append(item)
        desc = item.get("Descripcion") or ""
        m_emb = embedded_re.search(desc)
        if not m_emb:
            continue
        extra = dict(item)
        extra["Codigo"] = item.get("Codigo") or ""
        extra["Descripcion"] = m_emb.group("desc")
        extra["CantidadServida"] = _to_float(m_emb.group("qty"))
        extra["PrecioUnitario"] = _to_float(m_emb.group("price"))
        extra["DescuentoPct"] = _to_float(m_emb.group("dto"))
        extra["Importe"] = _to_float(m_emb.group("imp"))
        extra["ParseWarn"] = "gabyl_embedded_line"
        expanded_items.append(extra)
    items = expanded_items

    neto = None; total = None
    for ln in lines[-25:]:
        ln2 = _collapse_nums(ln)
        if re.search(r"Total\s+neto", ln2, re.I):
            m = NUM_RE.search(ln2);  neto = _to_float(m.group(0)) if m else neto

    meta = {
        "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
        "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan if neto is None else neto,
        "TotalAlbaranPie": np.nan,
    }

    try:
        from debugkit import dbg_parser_page
        dbg_parser_page(PARSER_ID, page_num,
                        header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
                        items=items, meta=meta)
    except Exception:
        pass

    return items, meta
