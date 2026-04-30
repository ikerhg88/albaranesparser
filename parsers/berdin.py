import os
import re
import subprocess
import tempfile
import unicodedata
from collections import deque

try:
    import cv2
except Exception:
    cv2 = None
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from common import to_float, normalize_spaces, fix_qty_price_import, normalize_supedido_code
from config import OCR_CONFIG
from albaranes_tool.ocr_stage import _resolve_tesseract_path

TEMPLATE = {
    "header": {
        "albaran_patterns": [
            r"ALBAR\S*\s+NUM[ER]O\s*[:\-]?\s*(?P<value>\d{8})",
            r"\b(?P<value>\d{8})\b",
        ],
        "fecha_patterns": [
            r"Fecha\s+Albar\S*\s*[:\-]?\s*(?P<value>\d{1,2}/\d{1,2}/\d{2,4})",
        ],
        "su_pedido_patterns": [
            r"Su\s+Pedido\s+(?P<value>[A-Z0-9./\-]{3,})",
            r"(?P<value>[A-Z0-9]{2,}\.\d{3}/[A-Z0-9/]{1,8})",
            r"(?P<value>\d{2}\.\d{3}/[A-Z0-9/]{1,8})",
        ],
        "su_pedido_markers": [
            "SU PEDIDO",
            "NUESTRO PEDIDO",
            "FECHA DE PEDIDO",
        ],
    },
    "table": {
        "mandatory_columns": [
            "POS",
            "CODIGO",
            "DESCRIPCION",
            "C.PEDIDA",
            "C.SERVIDA",
            "PRECIO",
            "IMPORTE",
        ],
        "stop_patterns": [
            r"\*\*\*QUEDA",
            r"PEDIDA\s+SERVIDA",
            r"Neto\s+Comercial",
            r"Cuota\s+IVA",
            r"Total\s*\(EUR\)",
            r"Total\s+Albar[áa]n",
        ],
        "summary_row_pattern": r"^\d+\s+-?\d+(?:,\d+)?\s+-?\d+(?:,\d+)?$",
        "summary_value_pattern": r"^-?\d+(?:,\d+)?$",
    },
    "normalization": {
        "description_stop_prefixes": [
            "***QUEDA",
            "***QUEDAI",
            "PEDIDA SERVIDA",
            "PEDIDA SERVIDA PEDTE",
            "Neto Comercial",
            "Cuota IVA",
        ],
    },
}

HEADER_PATTERNS = {
    "albaran": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["albaran_patterns"]],
    "fecha": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["fecha_patterns"]],
    "supedido": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["su_pedido_patterns"]],
}

TABLE_HEADER_VARIANTS = [TEMPLATE["table"]["mandatory_columns"]]

STOP_RE = re.compile("|".join(TEMPLATE["table"]["stop_patterns"]), re.I)
SUMMARY_ROW_RE = re.compile(TEMPLATE["table"]["summary_row_pattern"])
SUMMARY_VALUE_RE = re.compile(TEMPLATE["table"]["summary_value_pattern"])
SUPEDIDO_MARKERS = [kw.upper() for kw in TEMPLATE["header"]["su_pedido_markers"]]
SUPEDIDO_HEADER_RE = re.compile(r"S\W*U[L]?\W+PEDIDO.*NUESTRO\W+PEDIDO.*FECHA\W+DE\W+PEDIDO")
SUPEDIDO_FORBIDDEN_SUBSTRINGS = ("ANIVERS", "TELF", "MAIL", "GRUPO", "WWW", "CONTACTO")
DESC_STOP_PREFIXES = tuple(
    TEMPLATE["normalization"].get("description_stop_prefixes", [])
)
FORBIDDEN_PHONE_NUMBERS = ("943557900", "943471119")
FORBIDDEN_DESC_TOKEN_GROUPS = [
    ("OIALUME", "BIDEA"),
    ("OIALUME", "ERROTA"),
    ("OIALUME", "ERRATA"),
    ("LOYOLA", "NORTE"),
    ("MATEO",),
    ("MATEO", "ERROTA"),
    ("MATEO", "ERRATA"),
    ("FACTURAR", "A"),
    ("DELEGACION",),
    ("ASTIGARRAGA",),
    ("MARTUTENE",),
    ("TELF",),
    ("MAIL",),
    ("CIF",),
]
HEADER_KEYWORDS = (
    "POS", "CODIGO", "DESCRIPCION", "DESCRIP", "DESCRI", "CPEDIDA", "CSPEDIDA",
    "CSERVIDA", "CPEDTE", "UDSP", "UDS", "PRECIO", "IMPORTE", "DTO"
)

def _matches_table_header(row: str) -> bool:
    upper = _ascii(row.upper())
    if not upper:
        return False

    variants = {
        "POS": ("POS", "~OS", " OS", "POS."),
        "CODIGO": ("CODIGO",),
        "DESCRIPCION": ("DESCRIPCION", "DESCRIP", "DESCRIP-C", "DESCRIPCI"),
        "C.PEDIDA": ("C.PEDIDA", "CPEDIDA", "E.PEDIDA", ".PEDIDA"),
        "C.SERVIDA": ("C.SERVIDA", "CSERVIDA", ".SERVIDA", "SERVIDA"),
        "PRECIO": ("PRECIO",),
        "IMPORTE": ("IMPORTE", "IMPO", "IMPORT"),
    }

    score = 0
    for key, opts in variants.items():
        if any(opt in upper for opt in opts):
            score += 1

    has_core = ("CODIGO" in upper and "PRECIO" in upper and "IMP" in upper)
    return has_core and score >= 5

def _extract_first(text: str, patterns: list[re.Pattern]) -> str:
    for pat in patterns:
        match = pat.search(text)
        if match:
            groups = match.groupdict()
            if "value" in groups:
                return groups["value"].strip()
            if match.groups():
                return match.group(1).strip()
            return match.group(0).strip()
    return ""


# --- Rescue mode: cola numÃ©rica genÃ©rica si no se han detectado lÃ­neas ---
NUM_RX = r"\d{1,3}(?:\.\d{3})*,\d{2,3}"
TAIL_RX = re.compile(
    rf"\s(?P<cant>{NUM_RX})\s+(?P<precio>{NUM_RX})\s+(?:(?P<dto>\d{{1,3}}(?:,\d{{1,2}})?)%?\s+)?(?P<imp>{NUM_RX})(?:\s*(?:EUR|â‚¬))?\s*$"
)
def _rescue_mode(lines, page_num, header):
    items = []; suma = 0.0
    albaran = header.get("AlbaranNumero",""); fecha = header.get("FechaAlbaran",""); su_pedido = header.get("SuPedidoCodigo","")
    for ln in lines:
        desc_inline, tail_tokens = _extract_inline_tail(ln)
        inline_gd = _tail_tokens_to_gd(tail_tokens)
        if inline_gd and inline_gd.get("precio") and inline_gd.get("imp"):
            if _is_forbidden_description(desc_inline):
                continue
            cant = to_float(inline_gd.get("cservida") or inline_gd.get("cpedida") or inline_gd.get("udsp"))
            precio = to_float(inline_gd.get("precio"))
            dto = to_float(inline_gd.get("dto")) if inline_gd.get("dto") else None
            imp = to_float(inline_gd.get("imp"))
            if cant is None and precio and imp:
                cant = imp / precio
            if cant is None:
                cant = 1.0
            if imp is not None:
                item = {
                    "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
                    "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
                    "Codigo": "",
                    "Descripcion": desc_inline, "CantidadServida": cant, "PrecioUnitario": precio,
                    "DescuentoPct": dto, "Importe": imp, "Pagina": page_num, "Pdf": "", "ParseWarn": "rescue_mode"
                }
                items.append(item)
                suma += imp
                continue
        m = TAIL_RX.search(ln)
        if not m:
            # Intento de capturar linea con POS + CODIGO + DESC pero sin importes (caso p.3 Albaranesfra1510)
            m_orphan = re.match(r"^\s*(?P<pos>\d+)\s+(?P<code>\d{8,})\s+(?P<desc>.+?)\s*$", ln)
            if m_orphan:
                g = m_orphan.groupdict()
                desc_orphan = g["desc"].strip()
                if _is_forbidden_description(desc_orphan) or _contains_forbidden_phone(desc_orphan):
                    continue
                item = {
                    "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
                    "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
                    "Codigo": g["code"],
                    "Descripcion": desc_orphan, 
                    "CantidadServida": None, "PrecioUnitario": None,
                    "DescuentoPct": None, "Importe": 0.0, 
                    "Pagina": page_num, "Pdf": "", "ParseWarn": "rescue_orphan_item"
                }
                items.append(fix_qty_price_import(item))
            continue
        desc = ln[:m.start()].strip()
        if _is_forbidden_description(desc) or _contains_forbidden_phone(desc):
            continue
        cant = to_float(m.group("cant")); precio = to_float(m.group("precio"))
        dto = to_float(m.group("dto")) if m.group("dto") else None
        imp = to_float(m.group("imp"))
        item = {
            "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
            "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
            "Codigo": "",
            "Descripcion": desc, "CantidadServida": cant, "PrecioUnitario": precio,
            "DescuentoPct": dto, "Importe": imp, "Pagina": page_num, "Pdf": "", "ParseWarn": "rescue_mode"
        }
        items.append(item)
        if imp is not None:
            suma += imp
    return items, suma

PARSER_ID = "berdin"
PROVIDER_NAME = "BERDIN"
# ============================
# Utilidades numÃ©ricas
# ============================
NUM_DEC_2_4 = r"\d{1,3}(?:\.\d{3})*,\d{2,4}"
NUM_DEC_2   = r"\d{1,3}(?:\.\d{3})*,\d{2}"
NUM_DEC_2_4_RE = re.compile(NUM_DEC_2_4)
NUM_DEC_2_RE   = re.compile(NUM_DEC_2)

_INLINE_TAIL_RX = re.compile(r"(?P<body>.*?)(?P<tail>(?:\s+\d+(?:,\d+)?){3,})\s*$")

def _fix_mojibake(value: str) -> str:
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except Exception:
        return value

def _extract_inline_tail(text: str) -> tuple[str, list[str]]:
    if not text:
        return "", []
    match = _INLINE_TAIL_RX.search(text)
    if not match:
        return text.strip(), []
    body = match.group("body").rstrip()
    tail_tokens = match.group("tail").strip().split()
    # Evita interpretar colas puramente enteras como asignación de precio/dto/importe;
    # suelen ser ruido OCR o campos compactados que se resuelven por otra heurística.
    if tail_tokens and not any(("," in tok or "." in tok) for tok in tail_tokens):
        return text.strip(), []
    return (body or text).strip(), tail_tokens

def _tail_tokens_to_gd(tokens: list[str]) -> dict[str, str]:
    if not tokens:
        return {}
    mapping: dict[str, str] = {"imp": tokens[-1]}
    if len(tokens) >= 2:
        mapping["dto"] = tokens[-2]
    if len(tokens) >= 3:
        mapping["precio"] = tokens[-3]
    if len(tokens) >= 4:
        mapping["udsp"] = tokens[-4]
    if len(tokens) >= 5:
        mapping["cservida"] = tokens[-5]
    if len(tokens) >= 6:
        mapping["cpedida"] = tokens[-6]
    if len(tokens) >= 7:
        mapping["cpendte"] = tokens[-7]
    return mapping

def _apply_inline_tail(g: dict) -> dict:
    desc_raw = g.get("desc", "")
    desc_clean, tail_tokens = _extract_inline_tail(desc_raw)
    if tail_tokens:
        tail_map = _tail_tokens_to_gd(tail_tokens)
        for key, val in tail_map.items():
            if key == "desc":
                continue
            current = g.get(key)
            if not current:
                g[key] = val
        g["desc"] = desc_clean
    else:
        g["desc"] = desc_raw.strip()
    return g

def _collapse_nums(s: str) -> str:
    # Normaliza '1,00 -' -> '-1,00' y limpia espacios SOLO alrededor de separadores decimales
    s = re.sub(rf"({NUM_DEC_2_4})\s*-(?!\d)", r"-\1", s)
    s = re.sub(r"(?<=\d)\s+(?=[.,])", "", s)
    s = re.sub(r"(?<=[.,])\s+(?=\d)", "", s)
    # Glifos frecuentes en numerales: ':' por coma/punto
    s = s.replace(":", ",")
    return s

def _normalize_code(raw: str | None) -> str:
    if not raw:
        return ""
    code = re.sub(r"^[!¡]+", "", raw.strip())
    code = re.sub(r"[^0-9A-Za-z.\-]+", "", code)
    # Caso OCR con '1' espuria delante de código numérico de 8 dígitos (ej. 190190959 -> 90190959),
    # pero conserva prefijos dobles (ej. 110116576).
    if len(code) == 9 and code.startswith("1") and code[1:].isdigit() and code[1] != "1":
        code = code[1:]
    # Si tiene más de 9 dígitos y empieza por '1' repetido, permite quitar solo uno si el resto es numérico.
    if len(code) > 9 and code.startswith("1") and code[1:].isdigit():
        code = code[1:]
    return code.upper()

FOOTER_PAGE_KEYWORDS = ("NETO COMERCIAL", "TOTAL (EUR)", "TOTAL ALBARAN", "MUY IMPORTANTE", "HOJA")
TABLE_HINT_KEYWORDS = ("POS", "CODIGO", "DESCRIP", "C.PEDIDA", "C.SERVIDA", "IMPORTE")

def _is_footer_summary_page(lines: list[str]) -> bool:
    if not lines:
        return False
    normalized = []
    for ln in lines:
        clean = normalize_spaces(_ascii(ln.upper()))
        if clean:
            normalized.append(clean)
    if not normalized:
        return False
    joined = " ".join(normalized)
    if any(hint in joined for hint in TABLE_HINT_KEYWORDS):
        return False
    footer_hits = sum(1 for kw in FOOTER_PAGE_KEYWORDS if kw in joined)
    return footer_hits >= 2

_OCR_NUM_TRANSLATION = str.maketrans({
    "O": "0", "o": "0", "º": "0", "°": "0",
    "S": "5", "s": "5",
    "B": "8", "b": "6",
    "I": "1", "l": "1", "|": "1", "¡": "1",
    "'": "", "`": "", "´": "", "“": "", "”": "", "‘": "", "’": "",
})

def _clean_num_token(token: str) -> str:
    if not token:
        return ""
    token = token.replace("W", "00").replace("w", "00")
    token = token.replace("n", "7").replace("N", "7")
    t = token.translate(_OCR_NUM_TRANSLATION)
    t = re.sub(r"[^0-9,.-]", "", t)
    if not t:
        return ""
    t = re.sub(r"[.,]+$", "", t)
    if not t:
        return ""
    t = re.sub(r"(?<!^)-.*", "", t)
    if "," in t and "." in t:
        t = t.replace(".", "")
    if t.count(",") > 1:
        parts = t.split(",")
        if parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) >= 2:
            t = "".join(parts[:-1]).replace(".", "") + "," + parts[-1]
        elif parts:
            t = parts[0]
        else:
            return ""
    if t.count(".") > 1 and "," not in t:
        parts = t.split(".")
        t = "".join(parts[:-1]) + "." + parts[-1]
    if "," in t:
        int_part, dec_part = t.split(",", 1)
        if not dec_part:
            dec_part = "00"
        elif len(dec_part) == 1:
            dec_part = f"{dec_part}0"
        t = f"{int_part},{dec_part}"
    elif "." in t:
        int_part, dec_part = t.split(".", 1)
        if not dec_part:
            dec_part = "00"
        elif len(dec_part) == 1:
            dec_part = f"{dec_part}0"
        t = f"{int_part}.{dec_part}"
    return t.strip(",.")

def _fuzzy_decimal_tokens(line: str):
    out = []
    for m in re.finditer(r"[0-9A-Za-z.,'`º°¡-]+", line):
        raw = m.group(0)
        cleaned = _clean_num_token(raw)
        if cleaned and ("," in cleaned or "." in cleaned):
            if "," in cleaned:
                dec_part = cleaned.split(",")[-1]
            else:
                dec_part = cleaned.split(".")[-1]
            if len(dec_part) >= 2:
                out.append((m.start(), cleaned))
    return out


def _digits_from_token(token: str | None) -> str:
    if not token:
        return ""
    t = str(token).translate(_OCR_NUM_TRANSLATION)
    return re.sub(r"\D", "", t)


def _format_comma_number(value: float, ndigits: int) -> str:
    return f"{value:.{ndigits}f}".replace(".", ",")


def _recover_compact_price_dto(line: str, g: dict) -> dict[str, str]:
    """
    Recupera precio/dto/importe cuando OCR concatena precio+dto en un token compacto:
      ... 8 8 1 310705020 12378  -> precio 31,070 dto 50,20 importe 123,78
    """
    if not isinstance(g, dict):
        return {}

    precio_raw = (g.get("precio") or "").strip()
    imp_raw = (g.get("imp") or "").strip()
    dto_raw = (g.get("dto") or "").strip()

    compact_digits = ""
    imp_digits = ""

    if precio_raw and not re.search(r"[.,]", precio_raw):
        dig = _digits_from_token(precio_raw)
        if len(dig) >= 7:
            compact_digits = dig

    if imp_raw:
        if re.search(r"[.,]", imp_raw):
            imp_val = _to_float_safe(imp_raw)
            imp_digits = "" if imp_val is None else f"{int(round(imp_val * 100)):d}"
        else:
            imp_digits = _digits_from_token(imp_raw)

    if not compact_digits:
        m = re.search(r"\b(\d{7,12})\s+(\d{4,7})\s*$", line)
        if m:
            compact_digits = _digits_from_token(m.group(1))
            if not imp_digits:
                imp_digits = _digits_from_token(m.group(2))

    if not compact_digits or not imp_digits:
        return {}

    try:
        imp_val = int(imp_digits) / 100.0
    except Exception:
        return {}

    qty_hint = _to_float_safe(g.get("cservida")) or _to_float_safe(g.get("cpedida")) or 1.0
    udsp_hint = _to_float_safe(g.get("udsp")) or 1.0
    if qty_hint <= 0:
        qty_hint = 1.0
    if udsp_hint <= 0:
        udsp_hint = 1.0

    best = None
    for split in range(3, len(compact_digits) - 2):
        p_digits = compact_digits[:split]
        d_digits = compact_digits[split:]
        if len(d_digits) < 3:
            continue
        dto_val = int(d_digits) / 100.0
        if not (0 <= dto_val < 100):
            continue
        for p_dec in (3, 4):
            price_val = int(p_digits) / (10 ** p_dec)
            if not (0 < price_val < 200000):
                continue
            calc = round((qty_hint / udsp_hint) * price_val * (1.0 - dto_val / 100.0), 2)
            err = abs(calc - imp_val)
            # Penaliza precios irrealmente bajos cuando hay cantidad > 1.
            if qty_hint > 1 and price_val < 1:
                err += 1.0
            candidate = (err, -p_dec, price_val, dto_val)
            if best is None or candidate < best:
                best = candidate

    if best is None:
        return {}
    err, neg_dec, price_val, dto_val = best
    if err > max(0.25, imp_val * 0.03):
        return {}

    p_dec = -neg_dec
    return {
        "precio": _format_comma_number(price_val, p_dec),
        "dto": _format_comma_number(dto_val, 2),
        "imp": _format_comma_number(imp_val, 2),
    }

def _append_warn(current: str, tag: str) -> str:
    if not tag:
        return current or ""
    if not current:
        return tag
    tokens = set(tok for tok in current.split(";") if tok)
    if tag in tokens:
        return current
    return f"{current};{tag}"

def _to_float_safe(token: str | None):
    if not token:
        return None
    token = _collapse_nums(token)
    # Corrige glifos comunes en colas numéricas (S->5, O->0, l/I->1)
    token = token.translate(str.maketrans({"S": "5", "s": "5", "O": "0", "o": "0", "I": "1", "l": "1", "B": "8", "b": "8"}))
    return to_float(token)

def _to_int_safe(token: str | None):
    val = _to_float_safe(token)
    if val is None:
        return None
    return int(round(val))

def _ascii(u: str) -> str:
    if not isinstance(u, str):
        return u
    u = _fix_mojibake(u)
    try:
        normalized = unicodedata.normalize("NFKD", u)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))
    except Exception:
        return u

def _contains_forbidden_phone(text: str | None) -> bool:
    if not text:
        return False
    digits = re.sub(r"\D", "", text)
    if not digits:
        return False
    return any(phone in digits for phone in FORBIDDEN_PHONE_NUMBERS)

def _parse_qty_block(raw: str) -> tuple[int | None, int | None, int | None, int | None]:
    if not raw:
        return None, None, None, None
    parts = re.findall(r"\d+", raw)
    if not parts:
        return None, None, None, None
    normalized: list[int] = []
    for part in parts:
        if len(part) > 1 and len(set(part)) == 1 and len(part) <= 4:
            normalized.extend(int(part[0]) for _ in range(len(part)))
        else:
            try:
                normalized.append(int(part))
            except Exception:
                continue
    if not normalized:
        return None, None, None, None
    cpedida = normalized[0]
    cservida = normalized[1] if len(normalized) >= 2 else None
    cpendte = None
    udsp = None
    if len(normalized) >= 4:
        c3, c4 = normalized[2], normalized[3]
        if c3 == c4:
            udsp = c4
        else:
            cpendte = c3
            udsp = c4
    elif len(normalized) == 3:
        udsp = normalized[2]
    return cpedida, cservida, cpendte, udsp

def _is_header_fragment(text: str | None) -> bool:
    if not text:
        return False
    upper = _ascii(text.upper())
    letters = re.sub(r"[^A-Z]", "", upper)
    if not letters:
        return False
    if len(letters) <= 4 and letters in {"POS", "DTO"}:
        return True
    for kw in HEADER_KEYWORDS:
        if kw in letters:
            if len(letters) <= 20 or letters.startswith(kw):
                return True
    return False

def _is_forbidden_description(desc: str | None) -> bool:
    if not desc:
        return False
    if _contains_forbidden_phone(desc):
        return True
    upper = _ascii(desc.upper())
    if not upper:
        return False
    if _is_header_fragment(upper):
        return True
    for tokens in FORBIDDEN_DESC_TOKEN_GROUPS:
        if all(token in upper for token in tokens):
            return True
    if re.search(r"\b20\d{3}\b", upper) and ("ASTIGARRAGA" in upper or "MARTUTENE" in upper):
        return True
    return False

def _is_supedido_header_text(text: str) -> bool:
    if not text:
        return False
    upper = _ascii(text.upper())
    sanitized = re.sub(r"[^A-Z0-9]+", " ", upper)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if all(marker in sanitized for marker in SUPEDIDO_MARKERS):
        return True
    return bool(SUPEDIDO_HEADER_RE.search(upper))

DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _find_albaran(joined: str) -> str:
    joined = _fix_mojibake(joined)
    if not joined:
        return ""
    joined_ascii = _ascii(joined.upper())

    # Prioridad alta: patrón explícito de cabecera "Albarán número"
    m = re.search(r"ALBAR\w*\s+N\w*MERO\s*[:\-]?\s*(\d{8,9})", joined_ascii)
    if m:
        return m.group(1)

    for pat in HEADER_PATTERNS["albaran"]:
        for match in pat.finditer(joined):
            if not match:
                continue
            groups = match.groupdict()
            value = ""
            if "value" in groups:
                value = groups["value"]
            elif match.groups():
                value = match.group(1)
            value = (value or "").strip()
            if not value:
                continue
            # Generic 8-digit fallback: requiere proximidad a la etiqueta 'Albaran'
            if pat.pattern == r"\b(?P<value>\d{8})\b":
                start, end = match.start(), match.end()
                window = joined_ascii[max(0, start - 120): min(len(joined_ascii), end + 120)]
                if "ALBAR" not in window:
                    continue
            return value

    # Último fallback seguro: 8/9 dígitos cerca de "ALBAR"
    m = re.search(r"ALBAR\w*[^0-9]{0,40}(\d{8,9})", joined_ascii)
    if m:
        return m.group(1)
    return ""

def _find_fecha(joined: str) -> str:
    joined = _fix_mojibake(joined)
    return _extract_first(joined, HEADER_PATTERNS["fecha"]) or ""

# ============================
# Su Pedido (cÃ³digo cliente)
# ============================
_OCR_DIGIT_MAP = {
    "O": "0", "Q": "0", "D": "0", "P": "0",
    "I": "1", "L": "1", "J": "1", "T": "1",
    "S": "5", "B": "8", "G": "6", "Z": "2",
}


def _win_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    kwargs: dict = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startup
    return kwargs


def _digits_from_ocr_token(token: str) -> str:
    if not token:
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", _ascii(token.upper()))
    if not compact:
        return ""
    out: list[str] = []
    for ch in compact:
        if ch.isdigit():
            out.append(ch)
            continue
        mapped = _OCR_DIGIT_MAP.get(ch)
        if mapped is None:
            return ""
        out.append(mapped)
    return "".join(out)


def _looks_like_internal_order_token(token: str) -> bool:
    if DATE_RE.fullmatch((token or "").strip()):
        return False
    digits = _digits_from_ocr_token(token)
    return len(digits) in (6, 7, 8)


def _coerce_ah_prefix_supedido(token: str) -> str:
    """
    Corrige OCR en formatos A/H + fecha + sufijo (ej. A260129/IA1).
    Aplica sólo si el token ya parece de ese tipo para evitar sobreajuste.
    """
    if not token:
        return ""
    t = re.sub(r"\s+", "", token.upper())
    t = t.replace("\\", "/").replace("~", "/").replace("`", "/").replace("´", "/")
    t = t.replace("]", "J").replace("[", "I").replace("?", "")
    m = re.match(r"^([AH])[-/]?([A-Z0-9]{4,10})[-/]?([A-Z0-9]{1,6})$", t)
    if not m:
        return t
    pref, raw_digits, raw_suf = m.groups()
    # T en bloque de fecha suele venir por 6 en OCR de Berdin (A2T?P129 -> A260129)
    raw_digits = raw_digits.replace("T", "6")
    digits = _digits_from_ocr_token(raw_digits)
    if len(digits) < 6:
        return t
    if len(digits) > 7:
        digits = digits[:7]
    suf = raw_suf.replace("I", "I").replace("L", "L")
    suf = re.sub(r"^1A", "IA", suf)
    suf = re.sub(r"^IA[IL]$", "IA1", suf)
    suf = re.sub(r"^IA[IL](\d)$", r"IA1\1", suf)
    if re.fullmatch(r"1\d{2}", suf):
        suf = f"IA{suf[1:]}"
    return f"{pref}{digits}/{suf}"


def _normalize_supedido(value: str, albaran: str | None = None) -> str:
    if not value:
        return ""
    s = normalize_spaces(value)
    s = s.strip(" -:/")
    s = s.replace(" ", "").upper()
    s = s.replace("\\", "/").replace("~", "/").replace("`", "/").replace("´", "/")
    s = s.replace("Â·", ".").replace("·", ".").replace("•", ".")
    s = s.replace("]", "J").replace("[", "I")
    s = re.sub(r"/!A[L1I]\b", "/IA1OCR", s)
    s = s.replace("!", "I")
    s = s.replace("?", "")
    # Normaliza separador OCR intermedio: 25.625·01/E -> 25.625-01/E
    s = re.sub(r"^(\d{2}\.\d{3})[.](\d{2}/[A-Z0-9]{1,4})$", r"\1-\2", s)
    s = _coerce_ah_prefix_supedido(s)
    s = _strip_trailing_internal_order(s)
    # Correcciones OCR recurrentes en sufijos IAxx
    s = re.sub(r"/!A(?=\d|[A-Z])", "/IA", s)
    s = re.sub(r"/1A(?=\d|[A-Z])", "/IA", s)
    s = re.sub(r"/IAL(?=\d|$)", "/IA1", s)
    s = re.sub(r"/IAI(?=\d|$)", "/IA1", s)
    s = re.sub(r"/1A1\b", "/IA1", s)
    if re.fullmatch(r"[AH]\d{6}/IA1(?:OCR)?", s):
        return s
    s = normalize_supedido_code(s)
    s = re.sub(r"/IAL(?=\d|$)", "/IA1", s)
    s = re.sub(r"/IAI(?=\d|$)", "/IA1", s)
    # Caso OCR frecuente en Berdin: /1422 -> /IA22
    s = re.sub(r"^(\d{2}\.\d{3}/\d{2})/1(\d{2})$", r"\1/IA\2", s)
    s = _strip_trailing_internal_order(s)
    if not re.fullmatch(r"[A-Z0-9./-]{3,24}", s):
        return ""
    # Evita usar el número de albarán como su pedido
    if albaran:
        da = re.sub(r"\D", "", albaran)
        ds = re.sub(r"\D", "", s)
        if da and ds == da:
            return ""
    return s


def _strip_trailing_internal_order(value: str) -> str:
    """
    En algunas cabeceras OCR el SuPedido se concatena con "Nuestro pedido"
    (id interno de 6-8 dígitos). Recorta ese sufijo solo cuando el prefijo
    ya encaja con patrones esperados de SuPedido.
    """
    if not value:
        return ""
    s = str(value).strip().upper()
    s = re.sub(r"\s+", "", s)
    strict_prefix = (
        r"[AH]-?\d{6}(?:[-/](?:IA\d{1,2}|[A-Z]{1,3}\d{0,2}))?",
        r"\d{2}\.\d{3}(?:[-/]\d{1,3})?(?:[-/](?:IA\d{1,2}|[A-Z]{1,3}\d{0,2}))?",
        r"\d{4,6}/\d{2}(?:/(?:IA\d{1,2}|[A-Z]{1,3}\d{0,2}))?",
    )
    # Caso OCR: código + pedido interno + restos alfabéticos (p.ej. LOE)
    m_noise = re.match(r"^(.*?)(\d{6,8})([A-Z]{2,6})$", s)
    if m_noise:
        prefix = m_noise.group(1).strip(" -:/")
        for rx in strict_prefix:
            if re.fullmatch(rx, prefix):
                return prefix
    for tail_len in (8, 7, 6):
        if len(s) <= tail_len + 3:
            continue
        tail = s[-tail_len:]
        if not tail.isdigit():
            continue
        prefix = s[:-tail_len].strip(" -:/")
        if not prefix:
            continue
        for rx in strict_prefix:
            if re.fullmatch(rx, prefix):
                return prefix
    return s


def _score_supedido(value: str) -> int:
    """Heurística de calidad para priorizar candidatos de SuPedido."""
    if not value:
        return -100
    v = normalize_supedido_code(value)
    if not v:
        return -100
    score = 0

    if re.fullmatch(r"[AH]-?\d{5,8}(?:[-/][A-Z0-9]{1,4})+", v):
        score += 6
    elif re.fullmatch(r"\d{2}\.\d{3}(?:[-/]\d{1,3})?(?:[-/][A-Z0-9]{1,4})+", v):
        score += 6
    elif re.fullmatch(r"\d{4,6}/\d{2}(?:/[A-Z0-9]{1,4})+", v):
        score += 5
    elif re.fullmatch(r"\d{2}\.\d{3}(?:[-/]\d{1,3})?", v):
        score += 2
    else:
        score += 1

    if re.search(r"/-|-/|//|\.\.|--|^\W|\W$", v):
        score -= 4
    if re.match(r"^\d(?:[/.-]|$)", v):
        score -= 2

    digits = sum(ch.isdigit() for ch in v)
    if digits < 4:
        score -= 3
    if len(v) > 26:
        score -= 2
    return score


def _is_plausible_supedido(value: str, min_score: int = 1) -> bool:
    return _score_supedido(value) >= min_score

def _extract_supedido_after_header(lines: list[str], header_idx: int | None) -> str:
    """
    Si encontramos la fila de cabecera (Su Pedido | Nuestro pedido | Fecha de pedido),
    tomamos la(s) siguiente(s) línea(s) y usamos el primer token antes de 'Nuestro' o de la fecha.
    """
    if header_idx is None:
        return ""
    limit = min(len(lines), header_idx + 4)
    for idx in range(header_idx + 1, limit):
        row = normalize_spaces(lines[idx])
        if not row:
            continue
        # dividir en columnas por espacios múltiples
        cols = [c for c in re.split(r"\s{2,}", row) if c.strip()]
        if cols:
            cand = cols[0].strip()
            return cand
        tokens = row.split()
        if tokens:
            return tokens[0].strip()
    return ""

def _expand_compact_supedido(token: str) -> str:
    """
    Intenta expandir un código cliente comprimido sin separadores,
    p.ej. '26501001H' -> '26.501/001/H' o '21023FJ' -> '21.023-FJ'.
    """
    if not token:
        return ""
    m = re.match(r"^(\d{2})(\d{3})(\d{3})([A-Z]?)$", token)
    if m:
        base = f"{m.group(1)}.{m.group(2)}/{m.group(3)}"
        return f"{base}/{m.group(4)}" if m.group(4) else base
    m = re.match(r"^(\d{2})(\d{3})([A-Z]{2})$", token)
    if m:
        return f"{m.group(1)}.{m.group(2)}-{m.group(3)}"
    return ""


def _extract_supedido_from_header_row(lines: list[str], albaran: str | None = None) -> str:
    """
    Extrae SuPedido desde la fila inmediatamente inferior a la cabecera:
    'Su Pedido | Nuestro pedido | Fecha de pedido'.
    Prioriza siempre la primera columna (Su Pedido).
    """
    if not lines:
        return ""
    for idx, row in enumerate(lines[:60]):
        upper = _ascii((row or "").upper())
        has_nuestro = ("NUESTRO" in upper and "PEDIDO" in upper)
        has_fecha = ("FECHA" in upper and "PEDIDO" in upper)
        has_su = ("SU" in upper and "PEDIDO" in upper)
        if not ((has_su and has_nuestro) or (has_nuestro and has_fecha) or has_fecha):
            continue
        limit = min(len(lines), idx + 4)
        for j in range(idx + 1, limit):
            below = normalize_spaces(lines[j])
            if not below:
                continue
            upper_below = _ascii(below.upper())
            if _matches_table_header(upper_below):
                break

            # Normaliza separadores OCR antes de tokenizar
            row_clean = upper_below
            row_clean = row_clean.replace("~", "/").replace("`", "/").replace("´", "/").replace("\\", "/")
            row_clean = row_clean.replace("Â·", ".").replace("·", ".").replace("•", ".")
            row_clean = row_clean.replace("]", "J").replace("[", "I")
            tokens = [tok for tok in row_clean.split() if tok.strip()]

            # Detecta índice de fecha e índice de pedido interno (6-8 dígitos OCR-normalizados)
            date_idx = None
            for t_idx, tok in enumerate(tokens):
                if DATE_RE.fullmatch(tok):
                    date_idx = t_idx
                    break
            internal_idx = None
            scan_limit = date_idx if date_idx is not None else len(tokens)
            for t_idx, tok in enumerate(tokens[:scan_limit]):
                if _looks_like_internal_order_token(tok):
                    internal_idx = t_idx
                    break

            end_idx = internal_idx if internal_idx is not None else (date_idx if date_idx is not None else len(tokens))
            cand_tokens = tokens[:end_idx]
            # Limpia tokens de cabecera residuales
            cand_tokens = [
                t for t in cand_tokens
                if t not in {"SU", "NUESTRO", "PEDIDO", "FECHA", "DE", "NORMAL", "PO", "POS"}
            ]
            if cand_tokens:
                # IA separado por espacio: ".../IA1 7 519467 ..." -> ".../IA17"
                if len(cand_tokens) >= 2 and re.fullmatch(r"\d{1,2}", cand_tokens[-1]):
                    head = "".join(cand_tokens[:-1])
                    if re.search(r"/IA[0-9A-Z]*$", head):
                        cand_tokens = [head + cand_tokens[-1]]
                cand = "".join(cand_tokens).strip(" -:/")
                cand = _strip_trailing_internal_order(cand)
                norm = _normalize_supedido(cand, albaran)
                if norm and _is_plausible_supedido(norm):
                    return norm

            # Caso ideal: token + numero interno (6-8) + fecha
            ascii_row = row_clean
            m = re.search(
                r"^\s*([A-Z0-9./\-]{4,36})\s+\d{6,8}\s+\d{1,2}/\d{1,2}/\d{2,4}\b",
                ascii_row,
            )
            if m:
                cand = _strip_trailing_internal_order(m.group(1))
                norm = _normalize_supedido(cand, albaran)
                if norm and _is_plausible_supedido(norm):
                    return norm

            # OCR sin columnas: compacta y corta por fecha de pedido
            compact = re.sub(r"\s+", "", ascii_row)
            compact = compact.replace("~", "/").replace("`", "/").replace("´", "/")
            compact_left = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}$", "", compact).strip()
            compact_left = _strip_trailing_internal_order(compact_left)
            if compact_left:
                norm = _normalize_supedido(compact_left, albaran)
                if norm and _is_plausible_supedido(norm):
                    return norm

            # Fallback: primera columna real, recortando fecha e id interno
            left = re.split(r"\d{1,2}/\d{1,2}/\d{2,4}", below)[0].strip()
            left = re.sub(r"\d{6,8}$", "", re.sub(r"\s+", "", _ascii(left.upper())))
            if left:
                left = _strip_trailing_internal_order(left)
                norm = _normalize_supedido(left, albaran)
                if norm and _is_plausible_supedido(norm):
                    return norm
    return ""

def _locate_supedido_bbox(page) -> tuple[float, float, float, float] | None:
    if page is None:
        return None
    try:
        words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    except Exception:
        return None
    if not words:
        return None
    best = None
    for idx, word in enumerate(words):
        txt = normalize_spaces(word.get("text", "") or "").upper()
        if "PEDIDO" in txt:
            best = word
            break
        if txt == "SU" and idx + 1 < len(words):
            nxt = normalize_spaces(words[idx + 1].get("text", "") or "").upper()
            if "PEDIDO" in nxt:
                x0 = min(word["x0"], words[idx + 1]["x0"])
                x1 = max(word["x1"], words[idx + 1]["x1"])
                top = min(word["top"], words[idx + 1]["top"])
                bottom = max(word["bottom"], words[idx + 1]["bottom"])
                best = {"x0": x0, "x1": x1, "top": top, "bottom": bottom}
                break
    if not best:
        return None
    padding_x = 10.0
    label_width = float(best["x1"]) - float(best["x0"])
    target_width = max(140.0, label_width + 80.0)
    x0 = max(0.0, float(best["x0"]) - padding_x)
    x1 = min(float(page.width), x0 + target_width)
    y0 = max(0.0, float(best["top"]) - 5.0)
    y1 = min(float(page.height), y0 + 70.0)
    if (x1 - x0) < 20 or (y1 - y0) < 10:
        return None
    return (x0, y0, x1, y1)


def _preprocess_supedido_image(pil_img: Image.Image) -> Image.Image:
    gray = pil_img.convert("L")
    if cv2 is None:
        enhanced = ImageOps.autocontrast(gray)
        enhancer = ImageEnhance.Contrast(enhanced)
        enhanced = enhancer.enhance(2.5)
        arr = np.array(enhanced)
        thresh = np.percentile(arr, 55)
        binary = (arr < thresh).astype(np.uint8) * 255
        return ImageOps.invert(Image.fromarray(binary))
    arr = np.array(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    arr = clahe.apply(arr)
    arr = cv2.medianBlur(arr, 3)
    bg = cv2.medianBlur(arr, 41)
    normalized = cv2.absdiff(arr, bg)
    th = cv2.adaptiveThreshold(
        normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 6
    )
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 4))
    hor_lines = cv2.morphologyEx(th, cv2.MORPH_OPEN, horiz_kernel)
    ver_lines = cv2.morphologyEx(th, cv2.MORPH_OPEN, vert_kernel)
    cleaned = cv2.subtract(th, hor_lines)
    cleaned = cv2.subtract(cleaned, ver_lines)
    kernel = np.ones((1, 2), np.uint8)
    opened = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
    return ImageOps.invert(Image.fromarray(opened))


def _run_tesseract_roi(pil_img: Image.Image) -> str:
    tess_cfg = (OCR_CONFIG or {}).get("tesseract", {})
    lang = tess_cfg.get("language", "spa+eng")
    oem = tess_cfg.get("oem", 1)
    cmd = tess_cfg.get("cmd")
    try:
        tess_path = _resolve_tesseract_path(cmd or None)
    except Exception:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
        pil_img.save(tmp_path, format="PNG")
    try:
        proc = subprocess.run(
            [
                tess_path,
                tmp_path,
                "stdout",
                "-l",
                lang,
                "--oem",
                str(oem),
                "--psm",
                "8",
                "-c",
                "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-",
                "-c",
                "preserve_interword_spaces=1",
            ],
            capture_output=True,
            text=False,
            check=False,
            **_win_subprocess_kwargs(),
        )
        text = proc.stdout.decode("utf-8", "ignore") if proc.stdout else ""
        return text.strip().splitlines()[0] if text else ""
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _ocr_supedido_roi(page) -> str:
    bbox = _locate_supedido_bbox(page)
    if not bbox:
        return ""
    try:
        with page.within_bbox(bbox) as cropped:
            pil_img = cropped.to_image(resolution=500).original.convert("L")
    except Exception:
        return ""
    width = max(pil_img.width * 2, 1)
    height = max(pil_img.height * 2, 1)
    pil_img = pil_img.resize((width, height), Image.BICUBIC)
    processed = _preprocess_supedido_image(pil_img)
    raw_text = _run_tesseract_roi(processed)
    candidate = normalize_spaces(raw_text).strip()
    return _normalize_supedido(candidate)


def _find_supedido(lines: list[str], page=None) -> str:
    lines = [_fix_mojibake(ln) for ln in lines]
    """
    Berdin muestra el bloque:
        'Su Pedido  Nuestro pedido  Fecha de pedido'
        '<C�DIGO>   <n� interno>    <dd/mm/aaaa>'
    """

    def _clean_candidate(row: str) -> str:
        row = normalize_spaces(row)
        tokens = row.split()
        if len(tokens) >= 5 and tokens[0].isdigit() and tokens[1].isdigit():
            tokens = tokens[1:]
        if not tokens:
            return ""
        trimmed: list[str] = []
        for tok in tokens:
            if DATE_RE.fullmatch(tok):
                break
            trimmed.append(tok)
        if not trimmed:
            return ""
        cut_idx = len(trimmed)
        for idx, tok in enumerate(trimmed[1:], start=1):
            tok_clean = re.sub(r"[^0-9]", "", tok)
            if tok_clean.isdigit() and len(tok_clean) >= 4:
                cut_idx = idx
                break
        trimmed = trimmed[:cut_idx]
        candidate = " ".join(trimmed).strip(" -:/")
        return candidate

    def _is_valid_candidate(value: str, strict: bool) -> bool:
        if not value:
            return False
        digits_only = "".join(ch for ch in value if ch.isdigit())
        if not digits_only:
            return False
        if len(digits_only) >= 5 and len(set(digits_only)) == 1:
            return False
        letters_only = "".join(ch for ch in value if ch.isalpha())
        if letters_only and len(letters_only) >= 5 and len(set(letters_only)) == 1 and not any(ch in "/.-" for ch in value):
            return False
        has_punct = any(ch in "/.-" for ch in value)
        if len(digits_only) >= 10 and not has_punct and not any(ch.isalpha() for ch in value):
            return False
        compact = value.replace(" ", "")
        if compact.isdigit():
            if len(compact) < 3:
                return False
            if strict and len(compact) < 5:
                return False
        if has_punct and len(digits_only) < 3:
            return False
        if not has_punct and not any(ch.isalpha() for ch in value) and len(digits_only) < 4:
            return False
        if value.count(" ") > 1 and not has_punct:
            return False
        if len(value.strip()) > 30 and not has_punct:
            return False
        if value.strip().upper().startswith("NUESTRO"):
            return False
        if _contains_forbidden_phone(value):
            return False
        compact = value.replace(" ", "")
        # Si no hay separadores, sólo admitimos formatos A/H de pedido; evita capturar códigos de artículo.
        if not any(ch in "/.-" for ch in compact):
            if not re.fullmatch(r"[AH]-?\d{5,8}(?:[-/][A-Z0-9]{1,4})*", compact):
                return False
        if not _is_plausible_supedido(value, min_score=2 if strict else 1):
            return False
        return True

    def _candidate(row: str, strict: bool) -> str:
        cand = _clean_candidate(row)
        if _is_valid_candidate(cand, strict):
            return cand
        return ""

    def _has_forbidden_keywords(text: str) -> bool:
        u = _ascii(text.upper())
        forbidden = (
            "PRECIO", "IMPORTE", "POS", "CODIGO", "DESCRIP", "PEDIDA", "SERVIDA", "NETO",
            "DTO", "UDS", "ANIVERS", "TELF", "MAIL", "GRUPO", "CIF", "WWW", "CONTACTO"
        )
        return any(word in u for word in forbidden)

    def _is_nuestro_token(token: str) -> bool:
        if not token:
            return False
        compact = re.sub(r"[^\d]", "", token)
        if not compact.isdigit():
            return False
        return len(compact) in (6, 8)

    def _candidate_from_block(header_idx: int) -> str:
        tokens: list[str] = []
        limit = min(len(lines), header_idx + 6)
        for idx in range(header_idx + 1, limit):
            row = normalize_spaces(lines[idx])
            if not row:
                continue
            upper_row = _ascii(row.upper())
            if _matches_table_header(row) or ("POS" in upper_row and "CODIGO" in upper_row):
                break
            tokens.extend(row.split())
            if len(tokens) >= 4:
                break
        if not tokens:
            return ""
        candidate_tokens: list[str] = []
        for tok in tokens:
            stripped = tok.strip(":-")
            if not stripped:
                continue
            if DATE_RE.fullmatch(stripped):
                break
            if _is_nuestro_token(stripped):
                break
            candidate_tokens.append(stripped)
        if not candidate_tokens:
            return ""
        return normalize_spaces(" ".join(candidate_tokens)).strip(" -:/")

    def _candidate_after_header(start_idx: int) -> str:
        acc: list[str] = []
        stop = min(len(lines), start_idx + 8)
        for idx in range(start_idx, stop):
            row = normalize_spaces(lines[idx])
            if not row:
                continue
            u = _ascii(row.upper())
            if (
                _is_supedido_header_text(row)
                or ("NUESTRO" in u)
                or ("FECHA" in u)
                or ("POS" in u)
                or ("CODIGO" in u)
                or ("DESCRIP" in u)
            ):
                continue
            acc.append(row)
            cand_row = _candidate(row, strict=False)
            if cand_row and not _has_forbidden_keywords(cand_row):
                return cand_row
            if len(acc) <= 2:
                cand_acc = _candidate(" ".join(acc), strict=False)
                if cand_acc and not _has_forbidden_keywords(cand_acc):
                    return cand_acc
            if DATE_RE.search(row) or len(acc) >= 2:
                break
        return ""

    def _is_supedido_header_text(row: str) -> bool:
        row_upper = _ascii(row.upper())
        return (
            ("SU" in row_upper and "PEDIDO" in row_upper and "NUESTRO" in row_upper)
            or ("NUESTRO" in row_upper and "PEDIDO" in row_upper and "FECHA" in row_upper)
            or ("FECHA" in row_upper and "PEDIDO" in row_upper)
        )

    header_idxs: list[int] = []
    for idx, ln in enumerate(lines[:30]):
        if _is_supedido_header_text(ln):
            header_idxs.append(idx)
    for idx in header_idxs:
        # intento directo: primera línea debajo de la cabecera (columna Su Pedido)
        if idx + 1 < len(lines):
            row = normalize_spaces(lines[idx + 1])
            if row:
                # separa por 2+ espacios (suele dividir SuPedido / Nuestro / Fecha)
                cols = [c for c in re.split(r"\s{2,}", row) if c.strip()]
                tok_full = cols[0] if cols else row
                # corta antes de una fecha dd/mm/yy
                tok_full = re.split(r"\d{1,2}/\d{1,2}/\d{2,4}", tok_full)[0].strip()
                # toma el primer token no vacío
                tok = tok_full.split()[0].strip(":-") if tok_full else ""
                if tok:
                    normalized = _normalize_supedido(tok)
                    if _is_valid_candidate(normalized, strict=False):
                        return normalized
        block_candidate = _candidate_from_block(idx)
        if block_candidate:
            normalized = _normalize_supedido(block_candidate)
            if _is_valid_candidate(normalized, strict=False):
                return normalized
        cand = _candidate_after_header(idx + 1)
        if cand:
            normalized = _normalize_supedido(cand)
            if _is_valid_candidate(normalized, strict=False):
                return normalized

    for ln in lines[:200]:
        token = _candidate(ln, strict=True)
        if token and not _has_forbidden_keywords(token):
            normalized = _normalize_supedido(token)
            if _is_valid_candidate(normalized, strict=True):
                return normalized
        m_combined = re.search(r"Su\s+Pedido.*?([A-Za-z0-9./\-\s]{4,})", ln, re.I)
        if m_combined:
            token = _candidate(m_combined.group(1), strict=False)
            if token and not _has_forbidden_keywords(token):
                normalized = _normalize_supedido(token)
                if _is_valid_candidate(normalized, strict=False):
                    return normalized
    joined = " ".join(lines[:200])
    pats = [
        r"\bA[-/]?\d{5,8}(?:/[A-Z0-9]+)?\b",
        r"\b\d{2}\.\d{3}/\d{1,6}(?:/[A-Z]{1,3})?\b",
        r"\b[A-Z0-9]{2,}\.\d{3}/\d{1,6}(?:/[A-Z]{1,3})?\b",
    ]
    for rx in pats:
        m = re.search(rx, joined)
        if m:
            candidate = m.group(0)
            normalized = _normalize_supedido(candidate)
            if _is_valid_candidate(normalized, strict=False) and not _has_forbidden_keywords(normalized):
                return normalized
    inline_candidate = _extract_first(joined, HEADER_PATTERNS["supedido"])
    if inline_candidate:
        normalized = _normalize_supedido(_clean_candidate(inline_candidate))
        if _is_valid_candidate(normalized, strict=False):
            return normalized
    if page is not None:
        ocr_candidate = _ocr_supedido_roi(page)
        if ocr_candidate:
            return ocr_candidate
    return ""
def parse_page(page, page_num):
    text = page.extract_text() or ""
    raw_lines: list[str] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = _fix_mojibake(ln)
        ln = re.sub(r"^\d{1,3}:\s*", "", ln)
        ln = re.sub(r"[:;]", " ", ln)
        raw_lines.append(normalize_spaces(ln))
    NOISE_PATTERNS = [
        r"\b943\s*557\s*900\b",
        r"\b943\s*471\s*119\b",
        r"WWW\.BERDIN\.COM",
        r"@BERDIN\.COM",
        r"\bA20074738\b",
    ]
    noise_re = re.compile("|".join(NOISE_PATTERNS), re.I)
    def _keep_line(ln: str) -> bool:
        if re.search(r"\b(SU\s+PEDIDO|ALBAR[ÁA]N|POS|CODIGO|DESCRIP|PEDIDA|SERVIDA|IMPORTE)\b", ln, re.I):
            return True
        if re.search(r"\b\d{8,9}\b", ln):
            return True
        return not noise_re.search(ln)
    raw_lines = [ln for ln in raw_lines if _keep_line(ln)]
    lines = raw_lines[:]

    def _prefer_latest_block(rows: list[str]) -> list[str]:
        markers: list[int] = []
        for idx, row in enumerate(rows):
            if _matches_table_header(row):
                markers.append(idx)
        if len(markers) >= 2:
            starts: list[int] = []
            for mk in markers:
                start = mk
                for back in range(mk - 1, max(-1, mk - 80), -1):
                    if back < 0:
                        break
                    ua = _ascii(rows[back].upper())
                    if _is_supedido_header_text(rows[back]) or "ALBAR" in ua:
                        start = back
                        break
                starts.append(start)

            unique_starts = sorted(set(starts))
            ranges: list[tuple[int, int]] = []
            for idx, start in enumerate(unique_starts):
                end = unique_starts[idx + 1] if idx + 1 < len(unique_starts) else len(rows)
                ranges.append((start, end))

            # Evalúa cada bloque duplicado y elige el más consistente en cabecera.
            best_rows = rows[ranges[-1][0]:ranges[-1][1]]
            best_score = -999
            for start, end in ranges:
                sub = rows[start:end]
                sub_joined = _fix_mojibake(" ".join(sub))
                alb_sub = _find_albaran(sub_joined)
                sup_sub = _extract_supedido_from_header_row(sub, alb_sub)
                score = 0
                if alb_sub:
                    score += 2
                if sup_sub:
                    score += _score_supedido(sup_sub)
                if any(_matches_table_header(r) for r in sub[:40]):
                    score += 1
                if sum(1 for r in sub if STOP_RE.search(r)) == 0:
                    score -= 1
                # Con empate, preferimos el bloque más temprano (texto embebido suele ser más limpio).
                if score > best_score:
                    best_score = score
                    best_rows = sub
            return best_rows
        return rows

    full_lines = lines[:]
    full_joined = _fix_mojibake(" ".join(full_lines))

    lines = _prefer_latest_block(lines)
    joined = _fix_mojibake(" ".join(lines))

    # Cabecera: prioriza bloque recortado, pero nunca pierde valor del bloque completo
    albaran_full = _find_albaran(full_joined)
    fecha_full = _find_fecha(full_joined)
    full_has_sup_header = any(_is_supedido_header_text(ln) for ln in full_lines[:60])
    su_pedido_full_header = _extract_supedido_from_header_row(full_lines, albaran_full)
    if su_pedido_full_header:
        su_pedido_full = su_pedido_full_header
    elif full_has_sup_header:
        # Si la cabecera existe pero OCR de esa zona falla, evita patrón global agresivo.
        su_pedido_full = ""
    else:
        su_pedido_full = _find_supedido(full_lines, page)

    albaran = _find_albaran(joined) or albaran_full
    fecha = _find_fecha(joined) or fecha_full
    has_sup_header = any(_is_supedido_header_text(ln) for ln in lines[:60])
    su_pedido_header = _extract_supedido_from_header_row(lines, albaran)
    if su_pedido_header:
        su_pedido = su_pedido_header
    elif has_sup_header:
        su_pedido = su_pedido_full or _find_supedido(lines, page)
    else:
        su_pedido = _find_supedido(lines, page) or su_pedido_full

    def _looks_valid_supedido(val: str) -> bool:
        if not val:
            return False
        v = _strip_trailing_internal_order(normalize_supedido_code(val))
        if not v:
            return False
        if re.search(r"\d{6,8}$", v) and not any(sep in v for sep in "/-."):
            return False
        return _is_plausible_supedido(v)

    if su_pedido:
        su_pedido = _strip_trailing_internal_order(su_pedido)
        sup_ascii = _ascii(su_pedido.upper())
        digits_count = sum(ch.isdigit() for ch in sup_ascii)
        if any(bad in sup_ascii for bad in SUPEDIDO_FORBIDDEN_SUBSTRINGS):
            su_pedido = ""
        elif digits_count >= 10 and all(sep not in sup_ascii for sep in "/-") and not any(ch.isalpha() for ch in sup_ascii):
            su_pedido = ""
    def _fallback_supedido_from_text(txt: str) -> str:
        joined_ascii = _ascii(txt.upper())
        joined_ascii = re.sub(r"[~´`]", "/", joined_ascii)
        m = re.search(r"\b\d{2}\.\d{3}[./-][A-Z0-9/]{2,12}\b", joined_ascii)
        if m:
            return m.group(0)
        m = re.search(r"\b[A-Z]?\d{6}/\d{2,3}(?:/[A-Z]{1,3})?\b", joined_ascii)
        if m:
            return m.group(0)
        return ""

    if su_pedido:
        su_pedido = _strip_trailing_internal_order(su_pedido)
        su_pedido = su_pedido.replace("·", ".")
        su_pedido = re.sub(r"^[^0-9A-Z]+", "", su_pedido)
        su_pedido = normalize_supedido_code(su_pedido)
    if not _looks_valid_supedido(su_pedido):
        su_pedido = _fallback_supedido_from_text(joined)
    if su_pedido:
        su_pedido = _strip_trailing_internal_order(su_pedido)
        su_pedido = su_pedido.replace("·", ".")
        su_pedido = re.sub(r"^[^0-9A-Z]+", "", su_pedido)
        su_pedido = normalize_supedido_code(su_pedido)
    if not _looks_valid_supedido(su_pedido):
        for idx, ln in enumerate(full_lines[:80]):
            if not _is_supedido_header_text(ln):
                continue
            for cand_ln in full_lines[idx + 1 : idx + 4]:
                parts = re.split(r"\s{2,}", normalize_spaces(cand_ln))
                first_col = (parts[0] if parts else "").strip("[]()!¡.:; ")
                token = (first_col.split()[0] if first_col.split() else "").strip("[]()!¡.:; ")
                if re.fullmatch(r"[A-Za-z]{3,12}", token):
                    su_pedido = token
                    break
            if su_pedido:
                break
    if not _looks_valid_supedido(su_pedido) and not re.fullmatch(r"[A-Za-z]{3,12}", su_pedido or ""):
        flat = re.sub(r"[^A-Z0-9]", " ", _ascii(joined.upper()))
        compact_candidates = re.findall(r"\b\d{8,9}[A-Z]?\b", flat)
        for cand in compact_candidates:
            expanded = _expand_compact_supedido(cand)
            if expanded:
                su_pedido = expanded
                break
        if not su_pedido:
            fj_match = re.search(r"\b(\d{2})(\d{3})FJ\b", flat)
            if fj_match:
                su_pedido = f"{fj_match.group(1)}.{fj_match.group(2)}-FJ"
        if not _looks_valid_supedido(su_pedido):
            for idx, ln in enumerate(full_lines[:80]):
                if not _is_supedido_header_text(ln):
                    continue
                for cand_ln in full_lines[idx + 1 : idx + 4]:
                    parts = re.split(r"\s{2,}", normalize_spaces(cand_ln))
                    first_col = (parts[0] if parts else "").strip("[]()!¡.:; ")
                    token = (first_col.split()[0] if first_col.split() else "").strip("[]()!¡.:; ")
                    if re.fullmatch(r"[A-Za-z]{3,12}", token):
                        su_pedido = token
                        break
                if su_pedido:
                    break
    su_pedido = _strip_trailing_internal_order(
        normalize_supedido_code(_normalize_supedido(su_pedido, albaran))
    )

    def _build_numeric_summary(rows: list[str]) -> deque[dict[str, str]]:
        summary: deque[dict[str, str]] = deque()
        collecting = False
        for row in rows:
            if not collecting and _matches_table_header(row):
                collecting = True
                continue
            if not collecting:
                continue
            if STOP_RE.search(row):
                break
            clean = _ascii(_collapse_nums(row)).strip()
            clean = re.sub(r"^\d+:\s*", "", clean)
            if not clean:
                continue
            m_row = SUMMARY_ROW_RE.match(clean)
            if m_row:
                tokens = clean.split()
                if len(tokens) >= 3:
                    summary.append(
                        {
                            "qty": tokens[0],
                            "precio": tokens[1],
                            "dto": tokens[2],
                            "imp": None,
                        }
                    )
                continue
            if summary:
                if SUMMARY_VALUE_RE.match(clean):
                    for entry in summary:
                        if entry.get("imp") is None:
                            entry["imp"] = clean
                            break
                    if all(entry.get("imp") for entry in summary):
                        break
        return summary

    summary_queue = _build_numeric_summary(lines)

    # ---- Cabecera TOLERANTE (no requiere 'POS'): CODIGO + UDS/P + PRECIO + (DTO|NETO|OTO) + IMPORTE
    def _window_slice(start: int, width: int) -> tuple[str, str]:
        segment = lines[start:start + width]
        joined = " ".join(segment)
        upper = " ".join(_ascii(line.upper()) for line in segment)
        return joined, upper


    header_candidates: list[tuple[int, int, int]] = []
    for idx in range(len(lines)):
        for span in (1, 2, 3):
            joined, upper = _window_slice(idx, span)
            if _matches_table_header(joined):
                punct = sum(1 for ch in joined if not ch.isalnum() and not ch.isspace())
                header_candidates.append((punct, idx, span))
                break
    header_idx = None
    header_span = 1
    if header_candidates:
        _, header_idx, header_span = min(header_candidates, key=lambda x: (x[0], x[1]))
    # Fallback: versión clásica con POS
    if not header_candidates:
        fallback_candidates: list[tuple[int, int, int]] = []
        for idx in range(len(lines)):
            for span in (1, 2, 3):
                joined, upper = _window_slice(idx, span)
                if _matches_table_header(joined):
                    punct = sum(1 for ch in joined if not ch.isalnum() and not ch.isspace())
                    fallback_candidates.append((punct, idx, span))
                    break
        if fallback_candidates and header_idx is None:
            _, header_idx, header_span = min(fallback_candidates, key=lambda x: (x[0], x[1]))

    if header_idx is None:
        for idx, ln in enumerate(lines):
            ln_check = _collapse_nums(ln)
            ln_check = re.sub(r"^\s*(\d+)\s*[^0-9A-Z]{0,3}([0-9A-Za-z][0-9A-Za-z.\-]*)", r"\1 \2", ln_check, count=1)
            if STOP_RE.search(ln):
                break
            if re.match(r"^\s*\d+\s+[0-9A-Za-z][0-9A-Za-z.\-]*\s+\S", ln_check):
                header_idx = idx - 1
                break

    items, page_line_sum = [], 0.0

    if header_idx is not None:
        i = header_idx + header_span
        first_pos_found = False
        last_pos = 0
        while i < len(lines):
            ln_raw = lines[i]
            # Corrige separadores dobles entre digitos que juntan dos cantidades (p.ej. "1 ., 1" -> "1 1")
            had_double_sep = bool(re.search(r"(\d)\s*[.,]\s*[.,]\s*(\d)", ln_raw))
            ln_raw = re.sub(r"(\d)\s*[.,]\s*[.,]\s*(\d)", r"\1 \2", ln_raw)
            ln = _ascii(_collapse_nums(ln_raw))
            ln = re.sub(r"(?<=\d)[!Â¡](?=\s|$)", "", ln)
            ln = re.sub(r"(?<=\d)[iIl](?=\s|$)", "", ln)
            ln = re.sub(r"(?<=\d,\d{4})(?=\d)", " ", ln)
            ln = re.sub(r",\s*,+\s*(?=\d)", " ", ln)
            ln = ln.replace("NetoÂ¡", "Neto").replace("Neto!", "Neto").replace("NETOÂ¡", "NETO").replace("NETO!", "NETO")
            ln = re.sub(r"(?i)Neto[1l](?=\s|$)", "Neto", ln)
            ln = re.sub(r"(?i)(Neto)(?=\d)", lambda m: m.group(1) + " ", ln)
            ln = re.sub(r"\bL(\d{3},\d{2,3})", r"1\1", ln)
            ln = re.sub(rf"({NUM_DEC_2_4})[,.;:'\)\]\\/]+(?=\s|$)", r"\1", ln)
            ln = re.sub(
                rf"({NUM_DEC_2_4})(?=(?:\d{{1,3}}(?:\.\d{{3}})*)?,\d{{2,4}})",
                lambda m: m.group(1) + " ",
                ln,
            )
            if ln.strip().startswith("***"):
                break
            ln_upper = ln.upper()
            if re.match(r"^\s*[0-9]*[A-Za-z]+[0-9]+\s", ln):
                ln = re.sub(r"^\s*[0-9A-Za-z]*?([0-9]{1,3})\s+", r"\1 ", ln, count=1)
            row_warn = ""

            # Corrige ruido OCR entre POS y cÃ³digo (p.ej. '2 !10080455' -> '2 10080455')
            ln = re.sub(r"^\s*(\d+)\s*[^0-9A-Z]{0,3}([0-9A-Za-z][0-9A-Za-z.\-]*)", r"\1 \2", ln, count=1)
            ln = re.sub(r"^\s*[^0-9A-Z]+(?=\d+\s)", "", ln, count=1)
            # Si la lÃ­nea arranca directamente con un cÃ³digo largo, crea un POS sintÃ©tico 0 para procesarla
            if not re.match(r"^\s*\d+\s+[0-9A-Za-z][0-9A-Za-z.\-]*\s+\S", ln):
                m_code = re.match(r"^\s*(\d{8,})\b(.*)", ln)
                if m_code:
                    synthetic_pos = last_pos + 1 if last_pos > 0 else 0
                    ln = f"{synthetic_pos} {m_code.group(1)} {m_code.group(2).lstrip()}"

            if STOP_RE.search(ln):
                break

            if re.match(r"^\s*\d+\s+[0-9A-Za-z][0-9A-Za-z.\-]*\s+\S", ln):
                pat_common_left = (
                    r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<desc>.*?)\s+"
                    r"(?P<cpedida>\d+)(?:[^\dA-Z\s]{0,2})?\s+(?P<cservida>\d+)(?:[^\dA-Z\s]{0,2})?"
                    r"(?:\s+(?P<cpendte>\d+)(?:[^\dA-Z\s]{0,2})?)?\s+"
                    r"(?P<udsp>\d+(?:[.,]\d{1,4})?)(?:[^\dA-Z\s]{0,2})?\s+"
                    r"(?P<precio>" + NUM_DEC_2_4 + r")\s+"
                )
                pat_dto_num  = re.compile(pat_common_left + r"(?P<dto>" + NUM_DEC_2 + r")\s+(?P<imp>" + NUM_DEC_2 + r")\s*$")
                pat_dto_neto = re.compile(pat_common_left + r"(?:NETO|Neto)[^0-9A-Z]{0,2}\s+(?P<imp>" + NUM_DEC_2 + r")\s*$")

                m = pat_dto_num.match(ln) or pat_dto_neto.match(ln)

                if not m:
                    pat_common_left_no_udsp = (
                        r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<desc>.*?)\s+"
                        r"(?P<cpedida>\d+)(?:[^\dA-Z\s]{0,2})?\s+(?P<cservida>\d+)(?:[^\dA-Z\s]{0,2})?"
                        r"(?:\s+(?P<cpendte>\d+)(?:[^\dA-Z\s]{0,2})?)?\s+"
                    )
                    pat_dto_num_no_udsp = re.compile(
                        pat_common_left_no_udsp
                        + r"(?P<precio>" + NUM_DEC_2_4 + r")\s+(?P<dto>" + NUM_DEC_2 + r")\s+(?P<imp>" + NUM_DEC_2 + r")\s*$"
                    )
                    pat_dto_neto_no_udsp = re.compile(
                        pat_common_left_no_udsp
                        + r"(?P<precio>" + NUM_DEC_2_4 + r")\s+(?:NETO|Neto)[^0-9A-Z]{0,2}\s+(?P<imp>" + NUM_DEC_2 + r")\s*$"
                    )
                    m_no_udsp = pat_dto_num_no_udsp.match(ln) or pat_dto_neto_no_udsp.match(ln)
                    if m_no_udsp:
                        gd = m_no_udsp.groupdict()
                        gd.setdefault("udsp", None)
                        m = type("M", (), {"groupdict": lambda self, data=gd: data})()

                if not m:
                    m_imp = list(NUM_DEC_2_RE.finditer(ln))
                    if m_imp:
                        imp_tok = m_imp[-1].group(0)
                        left = ln[:m_imp[-1].start()].rstrip()

                        if re.search(r"(?:NETO|Neto)[^0-9A-Z]{0,2}\s*$", left):
                            dto_tok = None
                            m_prec = list(NUM_DEC_2_4_RE.finditer(left))
                            precio_tok = m_prec[-1].group(0) if m_prec else None
                            left2 = left[: m_prec[-1].start()].rstrip() if m_prec else left
                        else:
                            m_dto = list(NUM_DEC_2_RE.finditer(left))
                            dto_tok = m_dto[-1].group(0) if m_dto else None
                            left2 = left[: m_dto[-1].start()].rstrip() if m_dto else left
                            m_prec = list(NUM_DEC_2_4_RE.finditer(left2))
                            precio_tok = m_prec[-1].group(0) if m_prec else None
                            left2 = left2[: m_prec[-1].start()].rstrip() if m_prec else left2

                        # Aceptar barras residuales de OCR tras cantidades (p.ej. "5/")
                        m_left = re.match(
                            r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<desc>.*?)\s+"
                            r"(?P<cpedida>\d+)(?:[^\dA-Z\s]{0,2})?\s+(?P<cservida>\d+)(?:[^\dA-Z\s]{0,2})?"
                            r"(?:\s+(?P<cpendte>\d+)(?:[^\dA-Z\s]{0,2})?)?\s+"
                            r"(?P<udsp>\d+(?:[.,]\d{1,4})?)(?:[^\dA-Z\s]{0,2})?\s*$",
                            left2,
                        )
                        if m_left and precio_tok and imp_tok:
                            gd = m_left.groupdict()
                            gd.update({"precio": precio_tok, "dto": dto_tok, "imp": imp_tok})
                            m = type("M", (), {"groupdict": lambda self=gd: gd})()

                if not m:
                    # Captura bloque precio-dto-importe aunque haya texto a la derecha
                    match_pdi = re.search(rf"({NUM_DEC_2_4})\s+({NUM_DEC_2})\s+({NUM_DEC_2})", ln)
                    if match_pdi:
                        precio_tok, dto_tok, imp_tok = match_pdi.groups()
                        head = re.match(r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<body>.*)$", ln[:match_pdi.start()])
                        pos = head.group("pos") if head else "0"
                        code = head.group("code") if head else ""
                        desc = re.sub(r"^\s*\d+\s+[0-9A-Za-z.\-]+\s+", "", ln[:match_pdi.start()]).strip()
                        gd = {
                            "pos": pos,
                            "code": code,
                            "desc": desc,
                            "cpedida": None,
                            "cservida": None,
                            "cpendte": None,
                            "udsp": None,
                            "precio": precio_tok,
                            "dto": dto_tok,
                            "imp": imp_tok,
                        }
                        m = type("M", (), {"groupdict": lambda self=gd: gd})()
                        row_warn = _append_warn(row_warn, "fuzzy_numeric")

                if not m:
                    match_compact = re.search(r"\b(?P<compact>\d{7,12})\s+(?P<imp>\d{4,7})\s*$", ln)
                    if match_compact:
                        left = ln[: match_compact.start()].rstrip()
                        head = re.match(r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<body>.+)$", left)
                        if head:
                            body_tokens = head.group("body").split()
                            qty_tail_rev: list[str] = []
                            for tok in reversed(body_tokens):
                                if not re.fullmatch(r"\d{1,4}", tok):
                                    break
                                qty_tail_rev.append(tok)
                                if len(qty_tail_rev) >= 4:
                                    break
                            qty_tail = list(reversed(qty_tail_rev))
                            desc_tokens = body_tokens[: len(body_tokens) - len(qty_tail)] if qty_tail else body_tokens
                            qty_block = " ".join(qty_tail)
                            q_cped, q_cserv, q_cpend, q_udsp = _parse_qty_block(qty_block)
                            gd = {
                                "pos": head.group("pos"),
                                "code": head.group("code"),
                                "desc": " ".join(desc_tokens).strip(),
                                "cpedida": str(q_cped) if q_cped is not None else None,
                                "cservida": str(q_cserv) if q_cserv is not None else None,
                                "cpendte": str(q_cpend) if q_cpend is not None else None,
                                "udsp": str(q_udsp) if q_udsp is not None else None,
                                "precio": match_compact.group("compact"),
                                "dto": None,
                                "imp": match_compact.group("imp"),
                            }
                            m = type("M", (), {"groupdict": lambda self=gd: gd})()
                            row_warn = _append_warn(row_warn, "compact_pdi_raw")

                if not m:
                    fuzzy_tokens = _fuzzy_decimal_tokens(ln)
                    if fuzzy_tokens:
                        if len(fuzzy_tokens) > 3:
                            trimmed = []
                            skip_quota = len(fuzzy_tokens) - 3
                            for pos_tok in fuzzy_tokens:
                                pos_val, tok_val = pos_tok
                                int_part = tok_val.split(",")[0] if "," in tok_val else tok_val.split(".")[0]
                                if skip_quota > 0 and int_part.isdigit() and len(int_part) == 1:
                                    skip_quota -= 1
                                    continue
                                trimmed.append(pos_tok)
                            if trimmed:
                                fuzzy_tokens = trimmed
                        decimals = [tok for _, tok in fuzzy_tokens]
                        precio_tok = None
                        dto_tok = None
                        imp_tok = None
                        if len(decimals) >= 3:
                            precio_tok = decimals[-3]
                            dto_tok = decimals[-2]
                            imp_tok = decimals[-1]
                        elif len(decimals) == 2:
                            precio_tok = decimals[0]
                            dto_tok = decimals[1]
                        elif len(decimals) == 1:
                            precio_tok = decimals[0]

                        head = re.match(r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<body>.*)$", ln)
                        pos = head.group("pos") if head else "0"
                        code = head.group("code") if head else ""
                        desc_section = ln[:fuzzy_tokens[0][0]].strip()
                        desc = re.sub(r"^\s*\d+\s+[0-9A-Za-z.\-]+\s+", "", desc_section).strip()
                        if not desc and head:
                            desc = head.group("body")

                        gd = {
                            "pos": pos,
                            "code": code,
                            "desc": desc,
                            "cpedida": None,
                            "cservida": None,
                            "cpendte": None,
                            "udsp": None,
                            "precio": precio_tok,
                            "dto": dto_tok,
                            "imp": imp_tok,
                        }
                        m = type("M", (), {"groupdict": lambda self=gd: gd})()
                        row_warn = "fuzzy_numeric"
                    else:
                        m_qty = re.match(
                            r"^\s*(?P<pos>\d+)\s+(?P<code>[0-9A-Za-z.\-]+)\s+(?P<desc>.*?)\s+"
                            r"(?P<cpedida>\d+)\s+(?P<cservida>\d+)\s*$",
                            ln,
                        )
                        if m_qty:
                            gd = m_qty.groupdict()
                            gd.update(
                                {
                                    "cpendte": None,
                                    "udsp": None,
                                    "precio": None,
                                    "dto": None,
                                    "imp": None,
                                }
                            )
                            m = type("M", (), {"groupdict": lambda self=gd: gd})()
                            row_warn = _append_warn(row_warn, "missing_precio")
                            row_warn = _append_warn(row_warn, "missing_importe")
                        else:
                            i += 1
                            continue


                g = m.groupdict()
                codigo_val = _normalize_code(g.get('code'))
                tokens = ln.split()
                qty_block_raw = ""
                precio_marker = g.get("precio")
                if tokens and precio_marker:
                    precio_idx = None
                    for idx_tok, tok in enumerate(tokens):
                        tok_clean = tok.strip("';")
                        if NUM_DEC_2_4_RE.match(tok_clean):
                            precio_idx = idx_tok
                            break
                    if precio_idx is not None:
                        qty_tokens: list[str] = []
                        for idx_rev in range(precio_idx - 1, -1, -1):
                            tok = tokens[idx_rev]
                            digits_only = re.sub(r"\D", "", tok)
                            if not digits_only:
                                break
                            letters_only = re.sub(r"[^A-Za-z]", "", tok)
                            if letters_only and len(letters_only) > 1:
                                break
                            qty_tokens.append(tok)
                        qty_tokens.reverse()
                        qty_block_raw = " ".join(qty_tokens)
                g = _apply_inline_tail(g)
                compact_fix = _recover_compact_price_dto(ln, g)
                if compact_fix:
                    for kk in ("precio", "dto", "imp"):
                        current = (g.get(kk) or "").strip() if g.get(kk) is not None else ""
                        if not current or (not re.search(r"[.,]", current) and compact_fix.get(kk)):
                            g[kk] = compact_fix.get(kk)
                    row_warn = _append_warn(row_warn, "compact_pdi")
                desc = g.get("desc", "").strip()
                q_cpedida, q_cservida, q_cpendte, q_udsp = _parse_qty_block(qty_block_raw)
                if q_cpedida is not None and _to_int_safe(g.get("cpedida")) is None:
                    g["cpedida"] = str(q_cpedida)
                if q_cservida is not None and _to_int_safe(g.get("cservida")) is None:
                    g["cservida"] = str(q_cservida)
                if q_cpendte is not None and _to_int_safe(g.get("cpendte")) is None:
                    g["cpendte"] = str(q_cpendte)
                if q_udsp is not None and _to_float_safe(g.get("udsp")) is None:
                    g["udsp"] = str(q_udsp)
                if any(val is not None for val in (q_cpedida, q_cservida, q_udsp)) and (row_warn or "").find("qty_block") < 0:
                    row_warn = _append_warn(row_warn, "qty_block")
                k = i + 1

                if _is_forbidden_description(desc) or _contains_forbidden_phone(desc):
                    i = k
                    continue

                pos_raw = g.get("pos")
                try:
                    pos_int = int(pos_raw) if pos_raw is not None else None
                except Exception:
                    pos_int = None
                if pos_int is None:
                    i = k
                    continue
                if pos_int <= 0:
                    i = k
                    continue
                if not first_pos_found:
                    if pos_int != 1:
                        row_warn = _append_warn(row_warn, "pos_first_not_one")
                    first_pos_found = True
                else:
                    if pos_int <= last_pos:
                        row_warn = _append_warn(row_warn, "pos_out_of_order")
                last_pos = pos_int

                while k < len(lines):
                    ln2 = lines[k]
                    ln2_check = _ascii(_collapse_nums(ln2))
                    ln2_check = re.sub(r"^\s*(\d+)\s*[^0-9A-Z]{0,3}([0-9A-Za-z][0-9A-Za-z.\-]*)", r"\1 \2", ln2_check, count=1)
                    if STOP_RE.search(ln2) or re.match(r"^\s*\d+\s+[0-9A-Za-z][0-9A-Za-z.\-]*\s+\S", ln2_check) or re.match(r"^\s*[^0-9A-Za-z]{0,2}\s*\d+\s+[0-9A-Za-z][0-9A-Za-z.\-]*\s+\S", ln2_check) or re.match(r"^\s*[^0-9A-Za-z]{0,2}\s*\d{6,}\s+\S", ln2_check):
                        break
                    ln2_stripped = ln2.strip()
                    if ln2_stripped.startswith('***'):
                        break
                    if any(ln2_stripped.startswith(prefix) for prefix in DESC_STOP_PREFIXES):
                        break
                    if re.match(r"^[0-9A-Za-z.\-]{3,}$", ln2_stripped):
                        desc = f"{desc} {ln2_stripped}"
                    elif ln2_stripped:
                        desc = f"{desc} {ln2_stripped}"
                    k += 1

                if _is_forbidden_description(desc) or _contains_forbidden_phone(g.get("code")):
                    i = k
                    continue

                line_has_decimal = bool(NUM_DEC_2_4_RE.search(ln))
                code_has_digit = bool(re.search(r"\d", codigo_val or ""))
                # Evita pseudo-lineas de resumen tipo "11 Equipo ... 1 1" sin importes en la fila.
                if not code_has_digit and not line_has_decimal:
                    i = k
                    continue

                precio_raw  = g.get("precio")
                importe_f   = _to_float_safe(g.get("imp"))
                precio_f    = _to_float_safe(precio_raw)
                cservida_f  = _to_int_safe(g.get("cservida"))
                cpedida_f   = _to_int_safe(g.get("cpedida"))
                cpendte_f   = _to_int_safe(g.get("cpendte"))
                udsp_f      = _to_float_safe(g.get("udsp"))
                dto_f       = _to_float_safe(g.get("dto"))

                # No hardcoded overrides: rely on parsed values and generic heuristics.
                if precio_f is not None:
                    dec_len = 0
                    if isinstance(precio_raw, str):
                        if "," in precio_raw:
                            dec_len = len(precio_raw.split(",", 1)[1])
                        elif "." in precio_raw:
                            dec_len = len(precio_raw.split(".", 1)[1])
                    if had_double_sep and dec_len > 3:
                        precio_f = round(precio_f, 3)
                    else:
                        precio_f = round(precio_f, 4)
                if udsp_f is not None:
                    udsp_f = round(udsp_f, 3)
                if dto_f is not None:
                    dto_f = round(dto_f, 2)
                    if dto_f < 0:
                        row_warn = _append_warn(row_warn, "dto_negative")
                        dto_f = 0.0
                    elif dto_f >= 100:
                        row_warn = _append_warn(row_warn, "dto_overflow")
                        dto_f = min(dto_f, 99.99)
                if importe_f is not None:
                    importe_f = round(importe_f, 2)
                    if importe_f < 0:
                        row_warn = _append_warn(row_warn, "importe_negativo")
                if "NETO" in ln_upper:
                    if dto_f is None or dto_f >= 99.9:
                        dto_f = 0.0
                        row_warn = ";".join(tok for tok in (row_warn or "").split(";") if tok and tok != "dto_overflow")
                    if importe_f is None:
                        toks = _fuzzy_decimal_tokens(ln)
                        if toks:
                            importe_f = _to_float_safe(toks[-1][1])
                    if importe_f and precio_f and (cservida_f is None or cservida_f <= 1):
                        try:
                            qty_est = int(round(importe_f / precio_f))
                            if qty_est > 1:
                                cservida_f = qty_est
                                cpedida_f = qty_est if cpedida_f is None or cpedida_f <= 1 else cpedida_f
                                row_warn = _append_warn(row_warn, "qty_block")
                        except Exception:
                            pass

                allow_summary_hint = True
                if "missing_precio" in (row_warn or "") and "missing_importe" in (row_warn or "") and not line_has_decimal:
                    allow_summary_hint = False
                summary_hint = summary_queue.popleft() if (allow_summary_hint and summary_queue) else None
                if summary_hint:
                    qty_hint = _to_int_safe(summary_hint.get("qty"))
                    if (cservida_f is None or cservida_f == 0) and qty_hint is not None:
                        cservida_f = qty_hint
                    precio_hint = _to_float_safe(summary_hint.get("precio"))
                    if precio_hint is not None:
                        precio_hint = round(precio_hint, 4)
                        if precio_f is None or precio_f > 1_000_000 or row_warn == "fuzzy_numeric":
                            precio_f = precio_hint
                    dto_hint = _to_float_safe(summary_hint.get("dto"))
                    if dto_hint is not None:
                        dto_hint = round(dto_hint, 2)
                        if dto_f is None or dto_f >= 100 or dto_f < 0:
                            dto_f = min(max(dto_hint, 0.0), 99.99)
                    imp_hint = _to_float_safe(summary_hint.get("imp"))
                    if imp_hint is not None:
                        imp_hint = round(imp_hint, 2)
                        if importe_f is None or importe_f < 0 or importe_f > 1_000_000:
                            importe_f = imp_hint
                            if row_warn == "fuzzy_numeric":
                                row_warn = _append_warn(row_warn, "summary_hint")

                # Lookahead: si seguimos sin precio/dto/importe, intenta recoger 3 numeros con coma en lineas siguientes
                if (precio_f is None or dto_f is None or importe_f is None):
                    look_nums = []
                    for ln_ahead in raw_lines[k: min(k + 6, len(raw_lines))]:
                        ln_a = _collapse_nums(_ascii(ln_ahead))
                        look_nums += [to_float(m.group(0)) for m in NUM_DEC_2_4_RE.finditer(ln_a)]
                    if len(look_nums) >= 3 and precio_f is None and dto_f is None and importe_f is None:
                        precio_f, dto_f, importe_f = look_nums[-3:]

                qty_for_calc = cservida_f if cservida_f is not None else (cpedida_f if cpedida_f is not None else 1)
                # Si no hay qty pero hay precio e importe, deriva qty
                u_factor = udsp_f if udsp_f else 1
                if (cservida_f is None or cservida_f == 0) and precio_f is not None and importe_f is not None:
                    derived_qty = (importe_f / precio_f) * u_factor if precio_f else None
                    if derived_qty and derived_qty > 0:
                        check_imp = round((derived_qty / u_factor) * precio_f * (1 - (dto_f or 0) / 100), 2)
                        if abs(check_imp - importe_f) <= max(0.05, 0.05 * abs(importe_f)):
                            cservida_f = round(derived_qty, 2)
                            qty_for_calc = cservida_f
                calc_importe = None
                if precio_f is not None and qty_for_calc is not None:
                    disc_factor = 1.0
                    if dto_f is not None and 0 <= dto_f < 100:
                        disc_factor = (100 - dto_f) / 100
                    calc_importe = round((qty_for_calc / (u_factor or 1)) * precio_f * disc_factor, 2)
                if calc_importe is not None:
                    if importe_f is None or importe_f < 0:
                        importe_f = calc_importe
                        row_warn = _append_warn(row_warn, "importe_from_precio")
                    elif abs(calc_importe - importe_f) > 0.05 and (row_warn == "fuzzy_numeric" or had_double_sep):
                        importe_f = calc_importe
                        row_warn = _append_warn(row_warn, "importe_from_precio")

                if importe_f is None:
                    i = k
                    continue

                page_line_sum += (importe_f or 0.0)

                if (precio_f is None and importe_f is None) and (cservida_f is None and cpedida_f is None):
                    i = k
                    continue
                if precio_f is None and importe_f is None:
                    row_warn = _append_warn(row_warn, "missing_precio")
                    row_warn = _append_warn(row_warn, "missing_importe")

                item = {
                    "Proveedor": PROVIDER_NAME,
                    "Parser": PARSER_ID,
                    "AlbaranNumero": albaran or "",
                    "FechaAlbaran": fecha or "",
                    "SuPedidoCodigo": su_pedido or "",
                    "Codigo": codigo_val,
                    "Descripcion": desc,
                    "CantidadPedida": cpedida_f,
                    "CantidadServida": cservida_f,
                    "CantidadPendiente": cpendte_f,
                    "UnidadesPor": udsp_f,
                    "PrecioUnitario": precio_f,
                    "DescuentoPct": dto_f,
                    "Importe": importe_f,
                    "Pagina": page_num,
                    "Pdf": "",
                    "ParseWarn": row_warn
                }
                items.append(fix_qty_price_import(item))
                i = k
                continue

            i += 1

    # Totales del pie
    neto_comercial = None
    total_albaran = None
    search_lines = raw_lines if raw_lines else lines
    for ln in search_lines[-30:]:
        ln2 = _collapse_nums(ln)
        upper_ln = _ascii(ln2.upper())
        if re.search(r"NETO", upper_ln):
            m = NUM_DEC_2_RE.search(ln2)
            if m:
                neto_comercial = _to_float_safe(m.group(0))
        if re.search(r"TOTAL", upper_ln):
            m = NUM_DEC_2_RE.search(ln2)
            if m:
                total_albaran = _to_float_safe(m.group(0))
    if neto_comercial is None:
        m = re.search(r"NETO[^0-9]{0,30}(\d{1,3}(?:\.\d{3})*,\d{2})", _collapse_nums(text), re.I)
        if m:
            neto_comercial = _to_float_safe(m.group(1))
    if total_albaran is None:
        m = re.search(r"TOTAL[^0-9]{0,30}(\d{1,3}(?:\.\d{3})*,\d{2})", _collapse_nums(text), re.I)
        if m:
            total_albaran = _to_float_safe(m.group(1))

    supedido_bang_ia1 = bool(re.fullmatch(r"[AH]\d{6,8}/IA1OCR", su_pedido or ""))
    if supedido_bang_ia1:
        su_pedido = su_pedido[:-3]
        for item in items:
            item["SuPedidoCodigo"] = su_pedido
            item["ParseWarn"] = _append_warn(item.get("ParseWarn", ""), "berdin_bang_ia1")

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran or "",
        "FechaAlbaran": fecha or "",
        "SuPedidoCodigo": su_pedido or "",
        "SumaImportesLineas": page_line_sum,
        "NetoComercialPie": np.nan if neto_comercial is None else neto_comercial,
        "TotalAlbaranPie": np.nan if total_albaran is None else total_albaran,
    }

    # --- DEBUG unificado ---
    try:
        from debugkit import dbg_parser_page
        dbg_parser_page(PARSER_ID, page_num,
                        header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
                        items=items, meta=meta)
    except Exception:
        pass

    if not items:
        if not _is_footer_summary_page(raw_lines):
            header = {
                "AlbaranNumero": meta.get("AlbaranNumero", ""),
                "FechaAlbaran": meta.get("FechaAlbaran", ""),
                "SuPedidoCodigo": meta.get("SuPedidoCodigo", ""),
            }
            _resc, _sum = _rescue_mode(lines, page_num, header)
            if _resc:
                items.extend(_resc)
                try:
                    meta["SumaImportesLineas"] = (meta.get("SumaImportesLineas") or 0) + _sum
                except Exception:
                    pass

    # Si sólo hay una línea y tenemos Neto Comercial en el pie, úsalo si falta el importe.
    if items and len(items) == 1:
        neto_pie = meta.get("NetoComercialPie")
        if neto_pie and not np.isnan(neto_pie):
            imp_line = items[0].get("Importe")
            if imp_line is None or imp_line < 0.01:
                items[0]["Importe"] = neto_pie
                items[0]["ParseWarn"] = _append_warn(items[0].get("ParseWarn", ""), "importe_from_summary")
                try:
                    meta["SumaImportesLineas"] = neto_pie
                except Exception:
                    pass

    # Normaliza valores numéricos finales
    items = [fix_qty_price_import(it) for it in items]

    return items, meta




















