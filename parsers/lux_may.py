from __future__ import annotations

import re

from common import normalize_spaces
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first_item_row,
    normalize_albaran,
    normalize_supedido,
)

PARSER_ID = "lux_may"
PROVIDER_NAME = "LUX MAY"
BRAND_ALIASES = [
    "LUX MAY",
    "MANUFACTURAS PLASTICAS MAY",
    "LUX-MAY.COM",
    "AMOREBIETA",
]


def _extract_albaran_and_supedido(lines: list[str], joined: str) -> tuple[str, str]:
    for line in lines:
        m = re.search(
            r"([0-9][0-9_.]{4,})\s+(\d{2}/\d{2}/\d{4})\s+([A-Z0-9/._-]{5,})",
            line,
            flags=re.IGNORECASE,
        )
        if not m:
            continue
        albaran_raw = m.group(1)
        sup_raw = m.group(3)
        alb = normalize_albaran(albaran_raw, compact=True)
        digits = re.sub(r"\D", "", sup_raw)
        sup = digits if len(digits) >= 5 else normalize_supedido(sup_raw)
        if alb:
            return alb, sup

    m2 = re.search(
        r"ALBAR[ÁA]N\s+FECHA\s+PEDIDO[^0-9A-Z]{0,10}([0-9][0-9_.]{4,})\s+\d{2}/\d{2}/\d{4}\s+([A-Z0-9]{5,})",
        joined,
        flags=re.IGNORECASE,
    )
    if m2:
        return (
            normalize_albaran(m2.group(1), compact=True),
            normalize_supedido(m2.group(2)),
        )
    return "", ""


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, su_pedido = _extract_albaran_and_supedido(lines, joined)
    fecha = default_fecha(lines, joined)

    code, desc, qty = extract_first_item_row(
        lines,
        header_markers=["REFERENCIA", "DESCRIPCION", "CANTIDAD", "PRECIO"],
        stop_markers=["SUMA LINEAS", "NO SE ADMITIRAN", "FORMA DE PAGO"],
    )
    if not desc:
        desc = " | ".join(lines[:12])

    # No hay total fiable en el texto de cabecera.
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
        parse_warn="lux_may_structured",
    )
