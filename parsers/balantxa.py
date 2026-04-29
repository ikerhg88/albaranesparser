from __future__ import annotations

import re

from common import normalize_spaces
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first,
    extract_last_decimal,
    find_header_index,
    normalize_albaran,
    normalize_supedido,
)

PARSER_ID = "balantxa"
PROVIDER_NAME = "BALANTXA"
BRAND_ALIASES = [
    "BALANTXA",
    "CALDERERIA BALANTXA",
    "CALDERERIA-BALANTXA",
    "WWW.BALANTXA.NET",
    "INFO@CALDERERIA-BALANTXA.COM",
    "F-20874624",
]

SUPEDIDO_PATTERNS = [
    re.compile(
        r"\bPEDIDO\s*(?:N(?:[Oº°.]|UM(?:ERO)?)?\.?)?\s*[:#-]?\s*(?P<code>[A-Z]?\d{1,3}(?:[./]\d{2,6})+(?:[/-][A-Z0-9]{1,4})?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\bN(?:[Oº°.]|UM(?:ERO)?)?\s*PEDIDO\s*[:#-]?\s*(?P<code>[A-Z]?\d{1,3}(?:[./]\d{2,6})+(?:[/-][A-Z0-9]{1,4})?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\bPEDIDO\s*(?:N(?:[Oº°.]|UM(?:ERO)?)?\.?)?\s*[:#-]?\s*(?P<code>(?:[AH]\d{6,8}|\d{5,8}(?:/\d{2,3})?))",
        flags=re.IGNORECASE,
    ),
]


def _extract_albaran(joined: str, lines: list[str]) -> str:
    raw = extract_first(
        joined,
        [
            r"NOTA\s+DE\s+ENTREGA\w*[^0-9]{0,16}([0-9]{4,})",
            r"ENTREGA\w*[^0-9]{0,16}([0-9]{4,})",
        ],
    )
    if not raw:
        raw = extract_first(" ".join(lines[:8]), [r"\b([0-9]{4,})\b"])
    return normalize_albaran(raw, compact=True)


def _extract_importe(lines: list[str], joined: str) -> float | None:
    idx = find_header_index(lines, ["FECHA", "CONCEPTO", "IMPORTE"])
    if idx >= 0:
        for line in lines[idx + 1 : idx + 6]:
            val = extract_last_decimal(line)
            if val is not None:
                return val
    for line in reversed(lines[-6:]):
        val = extract_last_decimal(line)
        if val is not None:
            return val
    return extract_last_decimal(joined)


def _extract_desc(lines: list[str]) -> str:
    idx = find_header_index(lines, ["FECHA", "CONCEPTO", "IMPORTE"])
    if idx >= 0:
        block = []
        for line in lines[idx + 1 : idx + 5]:
            if not line.strip():
                continue
            block.append(line)
        if block:
            return normalize_spaces(" | ".join(block))
    return normalize_spaces(" | ".join(lines[:10]))


def _clean_supedido_candidate(raw: str | None) -> str:
    if not raw:
        return ""
    # El regex ya limita el token; aqui solo limpiamos cola de puntuacion OCR.
    token = normalize_spaces(str(raw)).strip(" :;,.")
    token = normalize_supedido(token)
    if not token:
        return ""
    digits = sum(ch.isdigit() for ch in token)
    if digits < 3:
        return ""
    return token


def _extract_supedido(lines: list[str], joined: str) -> str:
    # Priorizamos lineas con "PEDIDO" (normalmente cabecera de concepto).
    candidates: list[str] = []
    for line in lines:
        up = line.upper()
        if "PEDIDO" not in up:
            continue
        candidates.append(line)
    if not candidates:
        candidates = lines[:20]

    for source in candidates + [joined]:
        for pat in SUPEDIDO_PATTERNS:
            m = pat.search(source or "")
            if not m:
                continue
            code = _clean_supedido_candidate(m.group("code"))
            if code:
                return code
    return ""


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = _extract_albaran(joined, lines)
    fecha = default_fecha(lines, joined)
    su_pedido = _extract_supedido(lines, joined)
    importe = _extract_importe(lines, joined)
    desc = _extract_desc(lines)

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha,
        su_pedido=su_pedido,
        descripcion=desc,
        codigo="",
        cantidad=1.0 if importe is not None else None,
        precio=importe if importe is not None else None,
        dto=None,
        importe=importe,
        parse_warn="balantxa_structured",
    )
