from __future__ import annotations

import re

from common import normalize_spaces
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first_item_row,
    normalize_supedido,
)

PARSER_ID = "efecto_led"
PROVIDER_NAME = "Efecto Led"
BRAND_ALIASES = [
    "EFECTOLED",
    "EFECTO LED",
    "WWW.EFECTOLED.COM",
    "ALBARAN VTA",
    "RII-AEE 6831",
]


def _fix_prefix(token: str) -> str:
    t = normalize_spaces(token).upper()
    t = t.replace(" ", "")
    # OCR frecuente en este proveedor: ASI/ASL o PSI/PSL en lugar de A51/P51.
    if re.fullmatch(r"[A-Z][S5][IL1]", t):
        return f"{t[0]}51"
    return t


def _extract_albaran(lines: list[str], joined: str) -> str:
    m = re.search(
        r"N[ÚU]M\.?\s*[:#-]?\s*([A-Z0-9]{2,4})\s*-\s*(\d{4})\s*-\s*(\d{3,})",
        joined,
        flags=re.IGNORECASE,
    )
    if m:
        p = _fix_prefix(m.group(1))
        return f"{p}{m.group(2)}{m.group(3)}"
    return ""


def _extract_supedido(lines: list[str], joined: str) -> str:
    m = re.search(
        r"PEDIDO\s+([A-Z0-9]{2,4})\s*-\s*(\d{4})\s*-\s*(\d+)",
        joined,
        flags=re.IGNORECASE,
    )
    if m:
        p = _fix_prefix(m.group(1))
        return normalize_supedido(f"{p}{m.group(2)}")

    m2 = re.search(r"\bREF\.?\s*[:#-]?\s*([A-Z0-9./-]{4,})", joined, flags=re.IGNORECASE)
    if m2:
        return normalize_supedido(m2.group(1))
    return ""


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = _extract_albaran(lines, joined)
    su_pedido = _extract_supedido(lines, joined)
    fecha = default_fecha(lines, joined)

    code, desc, qty = extract_first_item_row(
        lines,
        header_markers=["REFERENCIA", "DESCRIPCION", "CANTIDAD"],
        stop_markers=["FORMA DE PAGO", "PORTES DEBIDOS", "MEDIO DE ENVIO"],
    )
    if not desc:
        desc = " | ".join(lines[:12])

    # Documento sin total global explicito legible.
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
        parse_warn="efecto_led_structured",
    )
