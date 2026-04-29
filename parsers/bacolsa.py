from __future__ import annotations

import re

from common import normalize_spaces
from ._vendor_simple import (
    build_single_result,
    default_fecha,
    extract_first,
    extract_first_from_lines,
    extract_first_item_row,
    normalize_albaran,
    normalize_supedido,
)

PARSER_ID = "bacolsa"
PROVIDER_NAME = "BACOLSA"
BRAND_ALIASES = [
    "BACOLSA",
    "BACULOS Y COLUMNAS",
    "BACULOS Y COLUMNAS, S.L.",
    "POLIGONO INDUSTRIAL DE VALDEMUEL",
    "976603369",
]


def _extract_albaran(lines: list[str], joined: str) -> str:
    raw = ""
    for idx, line in enumerate(lines):
        up = line.upper()
        if "ALBARAN" in up and "PORTES" in up:
            for cand in lines[idx + 1 : idx + 4]:
                m = re.search(r"\b([AN][A-Z]?\d{2,4}[./]\d{2,6})\b", cand, flags=re.IGNORECASE)
                if m:
                    raw = m.group(1)
                    break
            if raw:
                break
    if not raw:
        raw = extract_first(
            joined,
            [
                r"\b([AN][A-Z]?\d{2,4}[./]\d{2,6})\b",
                r"N[ºO]?\s*ALBAR[ÁA]N[^A-Z0-9]{0,10}([A-Z0-9./-]{4,})",
            ],
        )
    if raw and len(raw) >= 2 and raw[0].upper() in {"A", "N"} and not raw[1].isdigit():
        raw = raw[0] + raw[2:]
    return normalize_albaran(raw, compact=True, n_prefix_to_a=True)


def _extract_supedido(lines: list[str], joined: str) -> str:
    raw = extract_first_from_lines(lines, [r"PEDIDO\s*:\s*([A-Z0-9./-]{4,})"])
    if not raw:
        raw = extract_first(joined, [r"PEDIDO\s*:\s*([A-Z0-9./-]{4,})"])
    if not raw:
        raw = extract_first_from_lines(lines, [r"S/?PED\.?\s*:\s*([A-Z0-9./-]{4,})"])
    return normalize_supedido(raw)


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
        stop_markers=["DOMICILIO FISCAL", "FIRMA", "NO SE ADMITIRAN"],
    )
    if not desc:
        desc = " | ".join(lines[:10])

    # En este formato no viene total monetario en la pagina de lineas.
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
        parse_warn="bacolsa_structured",
    )
