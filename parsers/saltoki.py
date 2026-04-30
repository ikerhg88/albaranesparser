# -*- coding: utf-8 -*-
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import numpy as np
from common import normalize_spaces, to_float, fix_qty_price_import, normalize_supedido_code
from albaranes_tool.ocr_stage import _resolve_tesseract_path
from config import OCR_CONFIG

PARSER_ID = "saltoki"
PROVIDER_NAME = "SALTOKI"

NUM = r"\d{1,3}(?:\.\d{3})*,\d{2,3}"
NUM_RE = re.compile(NUM)
DTO_RE = r"(?P<dto>\d{1,3}(?:,\d{1,2})?)%?"

TAIL_RE = re.compile(
    rf"^\s*(?P<cant>{NUM})\s+(?P<precio>{NUM})\s+(?:{DTO_RE}\s+)?(?P<imp>{NUM})(?:\s*(?:EUR|€))?\s*$",
    re.X | re.I,
)

STOP_RE = re.compile(r"(TOTAL\s*:|NETO\s*:|TOTAL:\s*EUR|TOTAL\s+EUR|TODAS LAS MERCANCÍAS|ALBARÁN\s*$)", re.I)
IGNORED_RE = re.compile(r"^(Entrega en:|Contacto:|Servido por:|Agencia:|Ruta:|Paquetes:|FP:|POR SALTOKI|EL CLIENTE|C/|AV |ASTIGARRAGA|GIPUZKOA|TLF|Pag:)", re.I)
ABONO_HEADER_RE = re.compile(r"CODIGO\s+CANTIDAD\s+CONCEPTO\s+PRECIO", re.I)
ALNUM_CODE_RE = re.compile(r"(?P<code>[A-Z0-9]{7,})\s+(?P<rest>.+)", re.I)

def _collapse_nums(s: str) -> str:
    s = re.sub(rf"({NUM})\s*-(?!\d)", r"-\1", s)
    s = re.sub(r"(?<=\d)\s+(?=[\d,./])", "", s)
    s = re.sub(r"(?<=,)\s+(?=\d)", "", s)
    return s

def _to_float(s):
    return to_float(_collapse_nums(s)) if s else None

def _norm_date(s: str) -> str:
    if not s:
        return ""
    s = s.replace("-", "/")
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m: return ""
    d,mn,y = m.groups()
    if len(y)==2: y="20"+y
    return f"{int(d):02d}/{int(mn):02d}/{int(y):04d}"

def _normalize_albaran(num_str: str) -> str:
    if not num_str:
        return ""
    # Preserva formato NNN.NNN si es recuperable; si solo hay 6 dígitos los formatea.
    candidate = num_str.replace("~", "7").replace("'", "1")
    candidate = re.sub(r"[^0-9.]", "", candidate)
    if re.fullmatch(r"\d{3}\.\d{3}", candidate):
        return candidate
    digits = re.sub(r"\D", "", candidate)
    if len(digits) == 6:
        return f"{digits[:3]}.{digits[3:]}"
    return digits

def _normalize_code(code: str) -> str:
    if not code:
        return ""
    return re.sub(r"[^A-Z0-9]", "", _ascii(code)).strip()

def _clean_description(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("|", " ")
    cleaned = re.sub(r"[^\w\s./,+-]", " ", cleaned)
    return normalize_spaces(cleaned).strip(":- ")

def _ascii(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

def _normalize_code(code: str) -> str:
    if not code:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", code)

def _clean_num_token(token: str) -> str:
    if token is None:
        return ""
    cleaned = token.replace(";", ",")
    cleaned = cleaned.replace(" ", "").replace("\u00a0", "")
    cleaned = re.sub(r"[A-Za-z]", "", cleaned)
    cleaned = re.sub(r"[^\d,.\-]", "", cleaned)
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "")
    if cleaned.endswith("-") and len(cleaned) > 1:
        cleaned = "-" + cleaned[:-1]
    # Normaliza múltiples comas/puntos dejando solo el último separador decimal
    if cleaned.count(",") > 1:
        head, tail = cleaned.rsplit(",", 1)
        head = re.sub(r"[,.]", "", head)
        cleaned = head + "," + tail
    if cleaned.count(".") > 1 and "," not in cleaned:
        head, tail = cleaned.rsplit(".", 1)
        head = head.replace(".", "")
        cleaned = head + "." + tail
    # Si más de dos decimales, recorta a dos (caso 310,0001 -> 310,00)
    m = re.match(r"(-?\d+(?:[.,]\d+))", cleaned)
    if m:
        cleaned = m.group(1)
    if re.match(r"-?\d+[.,]\d{3,}$", cleaned):
        cleaned = re.sub(r"([.,]\d{2})\d+$", r"\1", cleaned)
    if cleaned.endswith(","):
        cleaned = cleaned + "00"
    return cleaned

def _strip_noise_prefix(text: str) -> str:
    return re.sub(r"^\s*[^0-9A-Za-z]{0,10}", "", text)

def _is_abono_layout(lines: list[str]) -> bool:
    for ln in lines:
        ascii_ln = _ascii(ln)
        if "**ABONO**" in ascii_ln:
            return True
        if ABONO_HEADER_RE.search(ascii_ln):
            return True
    return False

def _parse_standard_items(lines, page_num, albaran, fecha, su_pedido):
    items, suma = [], 0.0
    start = None
    for idx, ln in enumerate(lines):
        ln_probe = _strip_noise_prefix(ln)
        m_start = ALNUM_CODE_RE.search(ln_probe)
        if m_start and any(ch.isdigit() for ch in m_start.group("code")) and re.search(r"\d+,\d+", m_start.group("rest")):
            start = idx
            break
    if start is None:
        return items, suma

    i = start
    while i < len(lines):
        raw = lines[i]
        normalized = _strip_noise_prefix(raw)
        if STOP_RE.search(raw):
            break

        m_code = ALNUM_CODE_RE.search(normalized)
        if m_code and not any(ch.isdigit() for ch in m_code.group("code")):
            m_code = None
        if not m_code:
            i += 1
            continue
        tokens = m_code.group("rest").split()
        if not tokens:
            i += 1
            continue

        comma_num_positions = [
            idx for idx, tok in enumerate(tokens)
            if re.fullmatch(r"-?\d+(?:\.\d{3})*,\d+", _clean_num_token(tok) or "")
        ]
        if len(comma_num_positions) == 1:
            qty_idx = comma_num_positions[0]
            qty = _to_float(_clean_num_token(tokens[qty_idx]))
            desc_text = _clean_description(" ".join(tokens[:qty_idx]))
            extras = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                nxt_probe = _strip_noise_prefix(nxt)
                if STOP_RE.search(nxt):
                    break
                nxt_code = ALNUM_CODE_RE.search(nxt_probe)
                if nxt_code and any(ch.isdigit() for ch in nxt_code.group("code")) and re.search(r"\d+,\d+", nxt_code.group("rest")):
                    break
                if IGNORED_RE.match(nxt):
                    break
                if nxt.strip():
                    extras.append(_clean_description(nxt))
                j += 1
            if extras:
                desc_text = f"{desc_text} | {' | '.join(extras)}" if desc_text else " | ".join(extras)
            items.append({
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": _normalize_code(m_code.group("code")),
                "Descripcion": f"{m_code.group('code')} {desc_text}".strip(),
                "CantidadServida": qty,
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": None,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "saltoki_qty_only",
            })
            i = j
            continue

        nums_rev, desc_rev = [], []
        for tok in reversed(tokens):
            if tok == "/":
                break
            tok_clean = _clean_num_token(tok)
            if len(nums_rev) < 4 and (_to_float(tok_clean) is not None):
                nums_rev.append(tok_clean)
            else:
                desc_rev.append(tok)

        if len(nums_rev) < 2:
            i += 1
            continue

        numbers = list(reversed(nums_rev))
        desc_tokens = list(reversed(desc_rev))
        if desc_tokens and desc_tokens[0] == m_code.group("code"):
            desc_tokens = desc_tokens[1:]
        desc_text = _clean_description(" ".join(desc_tokens))

        qty_token = numbers[0]
        price_token = numbers[1] if len(numbers) >= 2 else None
        dto_token = None
        imp_token = None

        if len(numbers) >= 4:
            dto_token = numbers[-2]
            imp_token = numbers[-1]
        elif len(numbers) == 3:
            candidate = numbers[-2]
            imp_token = numbers[-1]
            if re.fullmatch(r"-?\d{1,3}(?:,\d{1,2})?", candidate):
                dto_token = candidate
            else:
                desc_text = _clean_description(f"{desc_text} {candidate}".strip())
        else:
            imp_token = numbers[-1]

        qty = _to_float(qty_token)
        price = _to_float(price_token) if price_token else None
        dto = _to_float(dto_token) if dto_token else None
        imp = _to_float(imp_token) if imp_token else None

        # Caso OCR degradado: el "precio" viene de un código embebido (valor enorme)
        # y el "importe" capturado es en realidad un token suelto de cantidad.
        if (
            len(numbers) <= 3
            and price is not None and price > 10000
            and imp is not None and abs(imp) < 10
            and qty is not None and qty <= 2
            and dto is None
        ):
            qty = 0.0
            imp = 0.0

        # Evita tomar el precio como dto cuando coinciden
        if dto is not None and price is not None and abs(dto - price) < 1e-6:
            dto = None

        # Corrección DTO desproporcionado (p.ej. '571' -> 57,1)
        if dto is not None and dto > 100:
            dto = round(dto / 10.0, 2)
        # Si el importe falta pero tenemos qty y precio, calcular aplicando dto
        if imp is None and qty is not None and price is not None:
            factor = 1.0
            if dto is not None and 0 <= dto < 100:
                factor = (100 - dto) / 100
            imp = round(qty * price * factor, 2)

        j = i + 1
        extras = []
        while j < len(lines):
            nxt = lines[j]
            nxt_probe = _strip_noise_prefix(nxt)
            if STOP_RE.search(nxt):
                break
            nxt_code = ALNUM_CODE_RE.search(nxt_probe)
            if nxt_code and any(ch.isdigit() for ch in nxt_code.group("code")) and re.search(r"\d+,\d+", nxt_code.group("rest")):
                break
            if IGNORED_RE.match(nxt):
                break
            if nxt.upper().startswith("REF. PROV"):
                extras.append(_clean_description(nxt))
            elif nxt.strip():
                extras.append(_clean_description(nxt))
            j += 1

        if extras:
            desc_text = f"{desc_text} | {' | '.join(extras)}" if desc_text else " | ".join(extras)
        desc_text = _clean_description(desc_text)

        items.append(fix_qty_price_import({
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Codigo": _normalize_code(m_code.group("code")),
            "Descripcion": f"{m_code.group('code')} {desc_text}".strip(),
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": dto,
            "Importe": imp,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "",
        }))
        suma += (imp or 0.0)
        i = j
    if len(items) == 1 and items[0].get("Importe") is None and items[0].get("PrecioUnitario") in (None, ""):
        qty_only = items[0].get("CantidadServida")
        if qty_only is not None:
            items[0]["Importe"] = qty_only
            items[0]["ParseWarn"] = "saltoki_qty_only_as_importe"
            suma = float(qty_only)
    return items, suma

def _parse_abono_items(lines, page_num, albaran, fecha, su_pedido):
    items, suma = [], 0.0
    header_idx = None
    for idx, ln in enumerate(lines):
        if ABONO_HEADER_RE.search(_ascii(ln)):
            header_idx = idx
            break
    if header_idx is None:
        start_idx = 0
        for idx, ln in enumerate(lines):
            if "S/REF" in _ascii(ln):
                start_idx = idx + 1
                break
    else:
        start_idx = header_idx + 1

    item_re = re.compile(
        r"^(?P<code>\d{6,})\s+(?P<qty>-?[0-9.,-]+)\s+(?P<desc>.+?)\s+(?P<price>-?[0-9.,-]+)\s+(?P<dto>-?[0-9.,-]+)\s+(?P<imp>-?[0-9.,-]+)$"
    )

    i = start_idx
    while i < len(lines):
        raw = lines[i]
        ascii_raw = _ascii(raw)
        if not raw.strip():
            i += 1
            continue
        if STOP_RE.search(ascii_raw) or "BASE IMPONIBLE" in ascii_raw.upper() or ascii_raw.upper().startswith("REFERENCIA PROPUESTA"):
            break

        cleaned_line = raw.replace(", ", ",").replace(" ,", ",")
        candidate = _strip_noise_prefix(cleaned_line)
        match = item_re.match(candidate)
        if not match:
            i += 1
            continue

        code = match.group("code")
        qty_token = _clean_num_token(match.group("qty"))
        desc_text = _clean_description(match.group("desc"))
        price_token = _clean_num_token(match.group("price"))
        dto_token = _clean_num_token(match.group("dto"))
        imp_token = _clean_num_token(match.group("imp"))

        qty = _to_float(qty_token)
        price = _to_float(price_token)
        dto = _to_float(dto_token)
        imp = _to_float(imp_token)

        items.append(fix_qty_price_import({
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Codigo": _normalize_code(code),
            "Descripcion": f"{code} {desc_text}".strip(),
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": dto,
            "Importe": imp,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "",
        }))
        suma += (imp or 0.0)
        i += 1

    return items, suma

def _find_albaran(lines, joined):
    def _clean_date_spacing(text: str) -> str:
        return text.replace(" /", "/").replace("/ ", "/")

    for i, ln in enumerate(lines):
        if re.search(r"\bCLIENTE\b.*\bALBAR[ÁA]N\b.*\bFECHA\b", ln, re.I):
            for j in (1,2):
                if i+j < len(lines):
                    row = lines[i+j]
                    row_clean = _clean_date_spacing(row)
                    m = re.search(r"\b(\d{4,})\s+(?:\d+\s+)?([0-9.]{5,})\s+(?:\d+\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", row_clean)
                    if m:
                        return _normalize_albaran(m.group(2))
                    row_ascii = _ascii(row)
                    m_alt = re.search(r"\bALBAR[ÁA]N\b\s+([0-9][0-9.~]*)", row_ascii, re.I)
                    if m_alt:
                        return _normalize_albaran(m_alt.group(1))
        # Variante OCR donde FECHA va en la línea siguiente: CLIENTE ALBARÁN | FECHA ...
        if re.search(r"\bCLIENTE\b.*\bALBAR[ÁA]N\b", ln, re.I):
            window = _clean_date_spacing(" ".join(lines[i : min(len(lines), i + 4)]))
            m2 = re.search(
                r"\b\d{4,}\s+([0-9]{3}\.[0-9]{3})\s+\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b",
                window,
                re.I,
            )
            if m2:
                return _normalize_albaran(m2.group(1))
    m = re.search(
        r"\bCLIENTE\b\s+\d{4,}\s+(?:\d+\s+)?\bALBAR[ÁA]N\b\s+([0-9]{3}\.[0-9]{3})\b",
        joined,
        re.I,
    )
    if m:
        return _normalize_albaran(m.group(1))
    m = re.search(
        r"\bCLIENTE\b\s+\bALBAR[ÁA]N\b\s+\d{4,}\s+([0-9]{3}\.[0-9]{3})\b",
        joined,
        re.I,
    )
    if m:
        return _normalize_albaran(m.group(1))
    m = re.search(r"\bALBAR[ÁA]N\b[^\d]{0,12}(\d[\d.]+)", joined, re.I)
    if m:
        return _normalize_albaran(m.group(1))
    joined_upper = joined.upper()
    m = re.search(r"\bA[L1][A-Z]{0,3}ARAN\b[^\d]{0,15}([0-9][0-9.]+)", joined_upper)
    if m:
        return _normalize_albaran(m.group(1))
    joined_clean = _clean_date_spacing(joined)
    m = re.search(
        r"\b\d{5,}\s+([0-9]{3}\.[0-9]{3})\s+\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}",
        joined_clean,
    )
    return _normalize_albaran(m.group(1)) if m else ""


def _ocr_footer_albaran(page) -> str:
    if page is None:
        return ""
    try:
        tess_cfg = ((OCR_CONFIG or {}).get("tesseract") or {}).get("cmd")
        tess_cmd = _resolve_tesseract_path(tess_cfg)
    except Exception:
        return ""
    try:
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return ""
        words = page.extract_words(x_tolerance=2, y_tolerance=3) or []
        footer_words = [
            word for word in words
            if _ascii(word.get("text", "")).upper() == "CLIENTE"
            and float(word.get("top", 0) or 0) > height * 0.45
        ]
        if not footer_words:
            return ""
        anchor = sorted(footer_words, key=lambda w: (float(w.get("top", 0) or 0), float(w.get("x0", 0) or 0)))[0]
        x0 = max(0.0, float(anchor.get("x0", 0) or 0) - 30.0)
        top = max(0.0, float(anchor.get("top", 0) or 0) - 45.0)
        right = min(width, x0 + max(width * 0.45, 260.0))
        bottom = min(height, float(anchor.get("bottom", 0) or 0) + 55.0)
        bbox = (x0, top, right, bottom)
        pil = page.crop(bbox).to_image(resolution=500).original.convert("L")
    except Exception:
        return ""

    with tempfile.TemporaryDirectory(prefix="saltoki_footer_") as tmp:
        tmp_dir = Path(tmp)
        img_path = tmp_dir / "footer.png"
        out_base = tmp_dir / "ocr_footer"
        try:
            pil.save(img_path)
            subprocess.run(
                [
                    str(tess_cmd),
                    str(img_path),
                    str(out_base),
                    "-l",
                    "spa+eng",
                    "--psm",
                    "6",
                    "--oem",
                    "1",
                    "-c",
                    "preserve_interword_spaces=1",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            txt_path = out_base.with_suffix(".txt")
            if not txt_path.exists():
                return ""
            ocr_text = txt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    probe = _ascii(ocr_text).upper().replace(",", ".")
    m = re.search(r"\b\d{5,6}\s+(\d{3}\.\d{3})\s+\d{1,2}/\d{1,2}/\d{2,4}\b", probe)
    if m:
        return _normalize_albaran(m.group(1))
    m = re.search(r"\bALBAR\S*\s+FECHA\s+\d{5,6}\s+(\d{3}\.\d{3})", probe)
    if m:
        return _normalize_albaran(m.group(1))
    return ""

def _find_fecha(lines, joined):
    for i, ln in enumerate(lines):
        if re.search(r"\bCLIENTE\b.*\bALBAR[ÁA]N\b.*\bFECHA\b", ln, re.I):
            for j in (1,2):
                if i+j < len(lines):
                    row = lines[i+j]
                    row_clean = row.replace(" /", "/").replace("/ ", "/")
                    m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", row_clean)
                    if m: return _norm_date(m.group(1))
    joined_clean = joined.replace(" /", "/").replace("/ ", "/")
    m = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", joined_clean)
    return _norm_date(m.group(1)) if m else ""

def _find_supedido(lines: list[str], joined: str) -> str:
    for ln in lines:
        m = re.search(r"[S5]/?REF[:.]?\s*(.+)$", ln, re.I)
        if m:
            raw = m.group(1).strip()
            raw = raw.replace("\\/", "/")
            raw = re.sub(r"\s+", "", raw)
            raw = raw.strip("/-;:")
            if raw:
                return raw.upper()
    m = re.search(r"[S5]/?REF[:.]?\s*([A-Za-z0-9./\-]+)", joined, re.I)
    val = (m.group(1).replace("\\/", "/") if m else "").strip()
    val = val.strip("/-;:")
    return val.upper()

def _normalize_supedido(val: str) -> str:
    if not val:
        return ""
    raw = normalize_spaces(val.replace("\\/", "/")).strip().strip("/-;:")
    if not raw:
        return ""
    compact_raw = re.sub(r"\s+", "", raw).upper()
    compact_raw = compact_raw.replace("A.", "A")
    if compact_raw.startswith("26.790/"):
        return "26090/" + compact_raw.split("/", 1)[1].split("/", 1)[0]
    m_vsep = re.fullmatch(r"(\d{2})[. ]?(\d{3})V(\d{2})(?:V[A-Z0-9]{1,3})?", compact_raw)
    if m_vsep:
        return f"{m_vsep.group(1)}{m_vsep.group(2)}/{m_vsep.group(3)}"
    # OCR frecuente en algunas cabeceras SALTOKI (semana 09):
    # A240226VL / A260226VH / A.260226VY -> A240226 / A260226
    if re.fullmatch(r"A2\d{5}V[A-Z]{1,2}", compact_raw):
        return compact_raw[:7]
    # En Saltoki hay referencias tipo A060226VL sin separadores; conservar formato leído.
    if re.fullmatch(r"[AH]\d{6}[A-Z0-9]{1,4}", compact_raw):
        return compact_raw

    # Preserva prefijos textuales útiles en Saltoki (ej. "LOVATO2 25.002/39/Y").
    m = re.match(r"^([A-Z0-9]{2,20})\s+(\d{2}\.\d{3}/\d{2}(?:/[A-Z0-9]{1,4})?)$", raw, re.I)
    if m:
        code = normalize_supedido_code(m.group(2)) or m.group(2).upper()
        return f"{m.group(1).upper()} {code}"

    norm = normalize_supedido_code(raw)
    if norm:
        if norm.upper().startswith("26790/"):
            return "26090/" + norm.split("/", 1)[1]
        return norm.upper()

    compact = compact_raw.strip("/-;:")
    compact = re.sub(r"(?<=\d)[O](?=\d)", "0", compact)
    compact = re.sub(r"(?<=\d)[IL](?=\d)", "1", compact)
    return compact

def parse_page(page, page_num, proveedor_detectado=None):
    text = page.extract_text() or ""
    raw_lines = [ln for ln in text.splitlines() if ln.strip()]
    lines = [normalize_spaces(re.sub(r"^\s*\d{3}:\s*", "", ln)) for ln in raw_lines]
    joined = " ".join(lines)

    albaran = _find_albaran(lines, joined)
    if not albaran:
        albaran = _ocr_footer_albaran(page)
    fecha = _find_fecha(lines, joined)
    su_pedido = _normalize_supedido(_find_supedido(lines, joined))

    if _is_abono_layout(lines):
        items, suma = _parse_abono_items(lines, page_num, albaran, fecha, su_pedido)
    else:
        items, suma = _parse_standard_items(lines, page_num, albaran, fecha, su_pedido)
    # Totales pie (si existen)
    neto = total = None
    for ln in lines[-30:]:
        ln2 = _collapse_nums(ln)
        if re.search(r"\bNETO\b", ln2, re.I):
            m = NUM_RE.search(ln2);  neto = _to_float(m.group(0)) if m else neto
        if re.search(r"\bTOTAL\b.*?(EUR)?", ln2, re.I):
            m = NUM_RE.search(ln2);  total = _to_float(m.group(0)) if m else total

    # Propagar cabecera de forma genérica (sin overrides por albarán).
    for item in items:
        if not item.get("AlbaranNumero"):
            item["AlbaranNumero"] = albaran
        elif albaran and item.get("AlbaranNumero") != albaran:
            if item.get("AlbaranNumero", "").replace(".", "") == albaran:
                item["AlbaranNumero"] = albaran
        if not item.get("SuPedidoCodigo"):
            item["SuPedidoCodigo"] = su_pedido

    meta = {"Proveedor":PROVIDER_NAME,"Parser":PARSER_ID,
            "AlbaranNumero":albaran,"FechaAlbaran":fecha,"SuPedidoCodigo":su_pedido,
            "SumaImportesLineas":suma,
            "NetoComercialPie": np.nan if neto is None else neto,
            "TotalAlbaranPie": np.nan if total is None else total}

    try:
        from debugkit import dbg_parser_page
        dbg_parser_page(PARSER_ID, page_num,
                        header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
                        items=items, meta=meta)
    except Exception:
        pass

    return items, meta
