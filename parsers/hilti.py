from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "hilti"
PROVIDER_NAME = "HILTI"
BRAND_ALIASES = ["HILTI", "HILTI ESPANOLA", "HILTI ESPAÑOLA", "ON!TRACK", "A-28226090"]


def _extract_header(lines: list[str], joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = parse_date_es(joined) or ""
    su_pedido = ""

    m = re.search(r"\bAlbar[aá]n\s+([0-9]{6,})\b", joined, flags=re.I)
    if m:
        albaran = m.group(1)

    m = re.search(r"Fecha\s+del\s+Albar[aá]n\s+(\d{1,2}/\d{1,2}/\d{2,4})", joined, flags=re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)

    m = re.search(r"pedido\s+cliente\s+([A-Z0-9./-]{2,})", joined, flags=re.I)
    if m:
        su_pedido = normalize_spaces(m.group(1)).upper()
    elif lines:
        for line in lines:
            m = re.search(r"Persona\s+de\s+Contacto\s+([A-Z0-9./-]{2,})", line, flags=re.I)
            if m:
                su_pedido = normalize_spaces(m.group(1)).upper()
                break

    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    items: list[dict] = []
    started = False
    for line in lines:
        up = line.upper()
        if "MATERIAL" in up and "DESCRIP" in up and "CANTIDAD" in up:
            started = True
            continue
        if not started:
            continue
        if "NUMERO DE BULTOS" in up or "DECLARACION" in up or "HILTI ESP" in up:
            break
        m = re.match(
            r"^(?P<code>\d{5,})\s+(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<unit>[A-Z]{2,5})\b",
            line,
            flags=re.I,
        )
        if not m:
            continue
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m.group("code"),
                "Descripcion": normalize_spaces(m.group("desc")),
                "CantidadServida": to_float(m.group("qty")),
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": 0.0,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "hilti_structured",
            }
        )
    return items


def parse_page(page, page_num, proveedor_detectado="HILTI"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, fecha, su_pedido = _extract_header(lines, joined)
    items = _parse_items(lines, page_num, albaran, fecha, su_pedido)
    suma = sum(float(item.get("Importe") or 0.0) for item in items)

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
