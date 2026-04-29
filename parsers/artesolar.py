from __future__ import annotations

import re

from common import normalize_spaces
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first,
    extract_first_item_row,
    normalize_albaran,
    normalize_supedido,
)

PARSER_ID = "artesolar"
PROVIDER_NAME = "ARTESOLAR"
BRAND_ALIASES = [
    "ARTESOLAR",
    "ALBARAN DE VENTA",
    "WWW.ARTESOLAR.COM",
    "A45708617",
]


_NOISE_TOKENS = (
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


def _extract_albaran(lines: list[str], joined: str) -> str:
    raw = extract_first(
        joined,
        [
            r"\b(AALV\s*[-./]?\s*\d{2}\s*[-./]?\s*\d{2,6})\b",
            r"N[\u00BAO]\s*ALBAR[\u00C1A]N[^A-Z0-9]{0,10}([A-Z0-9./-]{4,})",
        ],
    )
    return normalize_albaran(raw, compact=True)


def _extract_supedido(lines: list[str], joined: str, fecha: str) -> str:
    day_match = re.search(r"\b(\d{2})[/-]\d{2}[/-]\d{2,4}\b", fecha or "")
    day_prefix = day_match.group(1) if day_match else ""

    def _repair_prefix(prefix: str) -> str:
        if not day_prefix or prefix == day_prefix:
            return prefix
        if len(prefix) != 2 or len(day_prefix) != 2:
            return prefix
        pairs = [(a, b) for a, b in zip(prefix, day_prefix) if a != b]
        confusable = {("0", "5"), ("5", "0"), ("1", "7"), ("7", "1"), ("8", "3"), ("3", "8")}
        if len(pairs) == 1 and pairs[0] in confusable:
            return day_prefix
        return prefix

    def _normalize_pedido(raw: str) -> str:
        value = normalize_spaces(raw or "").upper()
        if not value:
            return ""
        if value.startswith("AALV"):
            return ""
        m = re.search(r"(?:[A-Z]-)?(\d{2})[./](\d{3})[./]\d{3}", value)
        if m:
            return f"{_repair_prefix(m.group(1))}{m.group(2)}"
        m2 = re.search(r"(?<!\d)(\d{2})[./-](\d{3})(?!\d)", value)
        if m2:
            return f"{_repair_prefix(m2.group(1))}{m2.group(2)}"
        only_digits = re.sub(r"\D", "", value)
        if len(only_digits) >= 5:
            return only_digits[:5]
        return normalize_supedido(value)

    raw = extract_first(
        joined,
        [
            r"N[\u00BAO2]\s*P(?:EDIDO)?\s*CLIENTE[^A-Z0-9]{0,24}([A-Z0-9./-]{4,})",
            r"\bPEDIDO\b[^A-Z0-9]{0,16}([A-Z0-9./-]{4,})",
            r"\b([A-Z]-\d{2}\.\d{3}\.\d{3})\b",
            r"\bCONCEPTO\s*[:#-]?\s*([A-Z0-9./-]{4,})",
        ],
    )
    if raw:
        normalized = _normalize_pedido(raw)
        if normalized:
            return normalize_supedido(normalized)

    for idx, line in enumerate(lines[:48]):
        up = line.upper()
        if "PEDIDO" not in up:
            continue
        window = " ".join(lines[idx : idx + 5])
        token = extract_first(
            window,
            [
                r"\b([A-Z]-\d{2}\.\d{3}\.\d{3})\b",
                r"(?<!\d)(\d{2}[./-]\d{3}(?:[./-]\d{3})?)(?!\d)",
                r"(?<!\d)(\d{5,})(?!\d)",
            ],
        )
        normalized = _normalize_pedido(token)
        if normalized:
            return normalize_supedido(normalized)

    for line in lines[:28]:
        up = line.upper()
        if "PEDIDO" not in up and ("CLIENTE" not in up or "P." not in up):
            continue
        if "PEDIDO" not in up and any(tok in up for tok in _NOISE_TOKENS):
            continue
        vals = re.findall(r"\b\d{5,}\b", line)
        for v in vals:
            # Descarta identificadores largos (normalmente telefonos/fiscales).
            if len(v) > 8:
                continue
            normalized = _normalize_pedido(v)
            if normalized:
                return normalize_supedido(normalized)
    return ""


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = _extract_albaran(lines, joined)
    fecha = default_fecha(lines, joined)
    su_pedido = _extract_supedido(lines, joined, fecha)

    code, desc, qty = extract_first_item_row(
        lines,
        header_markers=["REFERENCIA", "CONCEPTOS", "CANTIDAD"],
        stop_markers=["NO SE ADMITIRAN", "FORMA DE PAGO", "TOTAL"],
    )
    if not desc:
        desc = " | ".join(lines[:12])

    # El total de la pagina no es legible de forma estable; se mantiene 0.0.
    importe = 0.0

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha,
        su_pedido=su_pedido,
        descripcion=desc,
        codigo=code,
        cantidad=qty,
        precio=None,
        dto=None,
        importe=importe,
        parse_warn="artesolar_structured",
    )
