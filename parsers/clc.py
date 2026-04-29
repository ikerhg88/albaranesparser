import re
import numpy as np
from common import normalize_spaces, to_float, fix_qty_price_import

try:
    from config import PARSER_HINTS
except Exception:  # pragma: no cover
    PARSER_HINTS = {}

CLC_HINTS = PARSER_HINTS.get("CLC", {})
CLIENT_CODE = CLC_HINTS.get("client_code", "00000136")

PARSER_ID = "clc"
PROVIDER_NAME = "CLC"

NUM_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d{2,4})?")
STRICT_NUM_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2,4}")
COMMA_NUM_ONLY = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2,4}")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
LINE_NUM_RE = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s*$")
LINE_NUM_RE3 = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s*$")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")

TEMPLATE = {
    "header": {
        "serie_albaran_patterns": [
            r"\b(?:(?P<serie>\d{2,10})\s+)?(?P<albaran>\d{6,10})\s+(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<cliente>\d{6,8})\s+(?P<pedido>[A-Z0-9./-]+)",
            r"\b(?:OS\s+)?(?:(?P<serie>\d{2,10})\s+)?(?P<albaran>\d{6,10})\s+(?P<fecha>\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})\s+(?P<cliente>\d{6,8})\s+(?P<pedido>[A-Z0-9./-]+)",
        ],
        "albaran_patterns": [
            r"\bALBAR[ÁA]N\s+NUMERO\s*[:\-]?\s*(?P<value>\d+)",
            r"\bALBAR[ÁA]N\s*#?\s*(?P<value>\d+)",
        ],
        "fecha_patterns": [
            r"Fecha\s+Albar[áa]n\s*[:\-]?\s*(?P<value>\d{1,2}/\d{1,2}/\d{2,4})",
        ],
        "su_pedido_patterns": [
            r"Su\s+Pedido\s+(?P<value>[A-Z0-9./-]{3,})",
        ],
    },
}

HEADER_PATTERNS = {
    "serie": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["serie_albaran_patterns"]],
    "albaran": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["albaran_patterns"]],
    "fecha": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["fecha_patterns"]],
    "supedido": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["su_pedido_patterns"]],
}


def _extract_series_info(lines: list[str], joined: str) -> dict:
    candidates = lines[:10] + lines[-10:]
    for source in (candidates, [joined]):
        for text in source:
            for pattern in HEADER_PATTERNS["serie"]:
                match = pattern.search(text)
                if match:
                    return match.groupdict()
    return {}

def _extract_first(text: str, patterns: list[re.Pattern]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            groups = match.groupdict()
            if "value" in groups:
                return groups["value"].strip()
            if match.groups():
                return match.group(1).strip()
            return match.group(0).strip()
    return ""

def _ascii_upper(s: str) -> str:
    try:
        import unicodedata as _ud

        return "".join(ch for ch in _ud.normalize("NFKD", s or "") if not _ud.combining(ch)).upper()
    except Exception:
        return (s or "").upper()

def _squash_letters(text: str) -> str:
    """Reduce duplicated letters to a single occurrence to catch BRUUTTOO -> BRUTO."""
    return re.sub(r"([A-Z])\1+", r"\1", text)

def _looks_like_date(token: str | None) -> bool:
    if not token:
        return False
    t = token.strip()
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", t))


def _normalize_albaran_value(val: str | None, su_ped: str | None) -> str:
    if not val:
        return ""
    if val.startswith("000") and su_ped and "/" in su_ped:
        stripped = val.lstrip("0")
        return stripped or val
    return val


def _norm_date(token: str | None) -> str:
    if not token:
        return ""
    token = re.sub(r"\s+", "", token)
    parts = token.strip().split("/")
    if len(parts) != 3:
        return ""
    d, m, y = parts
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(m):02d}/{int(y):04d}"


def _find_after_label(lines: list[str], label: str, pattern: re.Pattern) -> str:
    for idx, ln in enumerate(lines):
        if label in _ascii_upper(ln):
            for j in range(idx, min(len(lines), idx + 4)):
                m = pattern.search(lines[j])
                if m:
                    return m.group(1)
    return ""


def _find_albaran(lines: list[str], joined: str) -> str:
    for pattern in HEADER_PATTERNS["serie"]:
        m = pattern.search(joined)
        if m and m.groupdict().get("albaran"):
            return m.group("albaran")
    direct = _extract_first(joined, HEADER_PATTERNS["albaran"])
    if direct:
        return direct
    m = re.search(r"\b(\d{6,})\b", joined)
    if not m:
        return ""
    num = m.group(1)
    if len(num) % 6 != 0:
        return num
    chunks = [num[i : i + 6] for i in range(0, len(num), 6)]
    return next((chunk for chunk in chunks if not re.fullmatch(r"1{6}", chunk)), num)


def _find_fecha(lines: list[str], joined: str) -> str:
    direct = _extract_first(joined, HEADER_PATTERNS["fecha"])
    token = direct if direct else _find_after_label(lines, "FECHA", DATE_RE)
    if not token:
        m = DATE_RE.search(joined)
        token = m.group(1) if m else ""
    return _norm_date(token)


def _find_supedido(lines: list[str], joined: str) -> str:
    for pattern in HEADER_PATTERNS["serie"]:
        m = pattern.search(joined)
        if m:
            data = m.groupdict()
            if data.get("pedido"):
                cliente = data.get("cliente")
                if not cliente or cliente == CLIENT_CODE:
                    return data["pedido"].strip()
    direct = _extract_first(joined, HEADER_PATTERNS["supedido"])
    if direct:
        cleaned = direct.strip()
        if cleaned.upper().startswith("OBRA"):
            cleaned = ""
        if cleaned:
            return cleaned
    for idx, ln in enumerate(lines):
        if "SU PEDIDO" in _ascii_upper(ln):
            for j in range(idx + 1, min(len(lines), idx + 4)):
                tokens = lines[j].split()
                if len(tokens) >= 4:
                    candidate = tokens[3]
                    if not _looks_like_date(candidate):
                        return candidate
    m = re.search(r"SU\s+PEDIDO\s+([A-Z0-9./-]+)", joined, re.I)
    if m and not _looks_like_date(m.group(1)):
        return m.group(1)
    # Fallback: scan for typical pedido codes (A260126, H200126/L)
    tokens = re.findall(r"[A-Z]\d{6}(?:/[A-Z0-9])?", _ascii_upper(joined))
    for tok in tokens:
        if tok == "A20074738":  # CIF, not pedido
            continue
        if _looks_like_date(tok):
            continue
        if 7 <= len(tok) <= 9:
            return tok
    return ""


def _is_number_token(token: str | None) -> bool:
    if not token:
        return False
    token = token.replace(".", "").replace(" ", "")
    return bool(re.fullmatch(r"-?\d+(?:,\d+)?", token))


HEADER_JUNK_RE = re.compile(
    r"^(DENOMIN(?:ACION)?|CANTIDAD|PRECIO|%?DTO|IMPORTE|BRUTO|RETIRA|FIRMADO|TOTAL(?:\s+DOCUMENTO)?|BASE|SU\s+PEDIDO|OBRA/REFERENCIA)\b[:\s\-]*",
    re.I,
)


def _strip_header_tokens(text: str) -> str:
    if not text:
        return ""
    txt = text.strip(" :;,.-|/")
    prev = None
    while txt and txt != prev:
        prev = txt
        txt = HEADER_JUNK_RE.sub("", txt).strip(" :;,.-|/")
    return txt


GLYPH_FIX_MAP = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "B": "8",
    "b": "6",
    "S": "5",
    "s": "5",
    "Z": "2",
    "z": "2",
    "G": "6",
    "g": "6",
    "D": "0",
    "a": "3",
})
GLITCH_TOKEN_RE = re.compile(r"(?=[^ ]*[.,])(?=[^ ]*[A-Za-z])[A-Za-z0-9.,/-]+")


def _fix_numeric_glitches(text: str) -> str:
    def repl(match: re.Match) -> str:
        token = match.group(0)
        fixed = token.translate(GLYPH_FIX_MAP)
        if "." in fixed and "," not in fixed and fixed.count(".") == 1:
            fixed = fixed.replace(".", ",")
        return fixed

    return GLITCH_TOKEN_RE.sub(repl, text)


STOP_RE = re.compile(r"(BRUTO|TOTAL\s+DOCUMENTO|BASE\s+IMP)", re.I)
HEADER_ROW_PATTERNS = [
    re.compile(r"(?:(?P<serie>\d{2,10})\s+)?(?P<albaran>\d{6,10})\s+(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<cliente>\d{6,8})\s+(?P<pedido>[A-Z0-9./-]+)"),
    re.compile(r"(?:(?P<serie>[A-Z]{1,4})\s+)?(?P<albaran>\d{6,})\s+(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<cliente>\d+)(?:\s+(?P<pedido>[A-Z0-9./-]+))?"),
    re.compile(r"(?:OS\s+)?(?:(?P<serie>\d{2,10})\s+)?(?P<albaran>\d{6,10})\s+(?P<fecha>\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4})\s+(?P<cliente>\d{6,8})\s+(?P<pedido>[A-Z0-9./-]+)"),
]

def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        ln = normalize_spaces(ln)
        ln = re.sub(r"(?<=\d)\s*/\s*(?=\d)", "/", ln)
        ln = re.sub(r"\s{2,}", " ", ln)
        lines.append(ln)
    joined = " ".join(lines)

    serie_info = _extract_series_info(lines, joined)
    albaran = _find_albaran(lines, joined)
    fecha = _find_fecha(lines, joined)
    su_pedido = _find_supedido(lines, joined)
    if serie_info:
        if serie_info.get("albaran"):
            albaran = serie_info["albaran"]
        if serie_info.get("fecha"):
            fecha = _norm_date(serie_info["fecha"])
        if serie_info.get("pedido") and (serie_info.get("cliente") in (CLIENT_CODE,)):
            su_pedido = serie_info["pedido"]
    albaran = _normalize_albaran_value(albaran, su_pedido)

    header_idx = None
    for idx, ln in enumerate(lines):
        u = _ascii_upper(ln)
        if "DENOMIN" in u and "CANTIDAD" in u and ("IMPORTE" in u or "MPOR" in u):
            header_idx = idx
            break

    items = []
    suma = 0.0

    def _append_item(desc, qty_tok, price_tok, imp_tok, dto_tok=None, warn=""):
        nonlocal suma
        desc = _strip_header_tokens(desc).strip()
        if not desc or not any(ch.isalpha() for ch in desc):
            return False
        qty = to_float(qty_tok)
        price = to_float(price_tok)
        imp = to_float(imp_tok)
        dto = to_float(dto_tok) if dto_tok else None
        if imp is None:
            return False
        item = {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Descripcion": desc,
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": dto,
            "Importe": imp,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": warn,
        }
        items.append(fix_qty_price_import(item))
        suma += imp
        return True

    if header_idx is not None:
        start = max(0, header_idx - 6)
        end = min(len(lines), header_idx + 6)
        for j in range(start, end):
            for pattern in HEADER_ROW_PATTERNS:
                m = pattern.search(lines[j])
                if not m:
                    continue
                data = m.groupdict()
                if data.get("albaran"):
                    albaran = _normalize_albaran_value(data["albaran"], su_pedido)
                if data.get("fecha"):
                    fecha = _norm_date(data["fecha"])
                if data.get("pedido") and not su_pedido:
                    cliente = data.get("cliente")
                    if not cliente or cliente == CLIENT_CODE:
                        su_pedido = data["pedido"]
                break

    # Extraccion principal: descripcion + cola numerica en la misma linea
    if header_idx is not None:
        i = header_idx + 1
        last_item = None
        guard = 0
        while i < len(lines):
            guard += 1
            if guard > len(lines) * 4:
                break
            ln = lines[i]
            upper_norm = _squash_letters(_ascii_upper(ln))
            if STOP_RE.search(upper_norm) or "RETIRA" in upper_norm or "FIRMADO" in upper_norm:
                break

            clean_ln = re.sub(r"[\"'|]", " ", ln)
            match_line = _fix_numeric_glitches(clean_ln)

            m4 = LINE_NUM_RE.search(match_line)
            if m4:
                qty_tok, price_tok, dto_tok, imp_tok = m4.groups()
                if _append_item(ln[:m4.start()].strip(), qty_tok, price_tok, imp_tok, dto_tok):
                    last_item = items[-1]
                i += 1
                continue

            m3 = LINE_NUM_RE3.search(match_line)
            if m3:
                qty_tok, price_tok, imp_tok = m3.groups()
                if _append_item(ln[:m3.start()].strip(), qty_tok, price_tok, imp_tok, None):
                    last_item = items[-1]
                i += 1
                continue

            nums_iter = [m for m in COMMA_NUM_ONLY.finditer(clean_ln) if not re.search(r"[A-Za-z]", m.group(0))]
            if len(nums_iter) >= 3:
                if len(nums_iter) >= 4:
                    q_m = nums_iter[-4]
                    p_m = nums_iter[-3]
                    d_m = nums_iter[-2]
                    imp_m = nums_iter[-1]
                    dto_tok = d_m.group(0)
                else:
                    q_m = nums_iter[-3]
                    p_m = nums_iter[-2]
                    imp_m = nums_iter[-1]
                    dto_tok = None
                if _append_item(ln[:q_m.start()].strip(), q_m.group(0), p_m.group(0), imp_m.group(0), dto_tok):
                    last_item = items[-1]
                    i += 1
                    continue

            if last_item and any(ch.isalpha() for ch in ln):
                last_item["Descripcion"] = f"{last_item['Descripcion']} {ln.strip()}".strip()
            i += 1

    # Fallback estructural: bloque de descripciones + bloque de numeros (mismo orden)
    if len(items) == 0 and header_idx is not None:
        stop_idx = len(lines)
        for j in range(header_idx + 1, len(lines)):
            if STOP_RE.search(_squash_letters(_ascii_upper(lines[j]))):
                stop_idx = j
                break
        block = lines[header_idx + 1:stop_idx]
        qty_header_idx = None
        for j, ln in enumerate(block):
            u = _ascii_upper(ln)
            if "CANTIDAD" in u and "PRECIO" in u and ("IMPORTE" in u or "MPORTE" in u):
                qty_header_idx = j
                break
        if qty_header_idx is not None:
            desc_lines = []
            for ln in block[:qty_header_idx]:
                txt = _strip_header_tokens(ln).strip(" /.-,:;")
                if txt and any(ch.isalpha() for ch in txt):
                    desc_lines.append(txt)
            num_rows = []
            for ln in block[qty_header_idx + 1:]:
                nums = [m.group(0) for m in COMMA_NUM_ONLY.finditer(_fix_numeric_glitches(ln))]
                if len(nums) >= 3:
                    num_rows.append(nums)
            for idx in range(min(len(desc_lines), len(num_rows))):
                nums = num_rows[idx]
                if len(nums) >= 4:
                    qty_tok, price_tok, dto_tok, imp_tok = nums[0], nums[1], nums[2], nums[-1]
                else:
                    qty_tok, price_tok, imp_tok = nums[0], nums[1], nums[-1]
                    dto_tok = None
                _append_item(desc_lines[idx], qty_tok, price_tok, imp_tok, dto_tok, "fallback_block")

    base = None
    total = None
    for ln in lines:
        u = _ascii_upper(ln)
        if "BASE" in u:
            m = NUM_RE.search(ln)
            if m:
                base = to_float(m.group(0).replace(" ", ""))
        if "EUR" in u:
            m = NUM_RE.search(ln)
            if m:
                total = to_float(m.group(0).replace(" ", ""))

    # Deduplicado conservador por descripcion exacta normalizada + importe
    dedup = {}
    for it in items:
        imp = to_float(it.get("Importe"))
        key = (it.get("AlbaranNumero", ""), re.sub(r"\s+", " ", (it.get("Descripcion") or "").strip().upper()), imp)
        if key not in dedup:
            dedup[key] = it
        else:
            old = dedup[key]
            if len((it.get("Descripcion") or "")) > len((old.get("Descripcion") or "")):
                dedup[key] = it
    items = list(dedup.values())

    # Ultimo fallback: solo si no salio ninguna linea
    if len(items) == 0:
        generic_pat = re.compile(
            r"^(?P<desc>.+?)\s+"
            r"(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+"
            r"(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+"
            r"(?:(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s+)?"
            r"(-?\d{1,3}(?:\.\d{3})*,\d{2,4})\s*$"
        )
        for ln in lines:
            if STOP_RE.search(_squash_letters(_ascii_upper(ln))):
                break
            m = generic_pat.match(ln.strip())
            if not m:
                continue
            desc = _strip_header_tokens(m.group("desc")).strip()
            nums = [g for g in m.groups()[1:] if g is not None]
            if len(nums) == 3:
                qty_tok, price_tok, imp_tok = nums
                dto_tok = None
            elif len(nums) == 4:
                qty_tok, price_tok, dto_tok, imp_tok = nums
            else:
                continue
            _append_item(desc, qty_tok, price_tok, imp_tok, dto_tok, "fallback_page")

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan if base is None else base,
        "TotalAlbaranPie": np.nan if total is None else total,
    }

    try:
        from debugkit import dbg_parser_page

        dbg_parser_page(
            PARSER_ID,
            page_num,
            header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
            items=items,
            meta=meta,
        )
    except Exception:
        pass

    return items, meta

