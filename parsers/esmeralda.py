from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "esmeralda"
PROVIDER_NAME = "ESMERALDA"
BRAND_ALIASES = ["ESMERALDA", "SUMINISTROS ESMERALDA", "ESME111LDN", "ESMERNLDN", "B20544367"]


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = parse_date_es(joined) or ""
    m = re.search(r"NUM\.?\s*:\s*([0-9]{2}\s*/\s*[0-9]{5,})", joined, flags=re.I)
    if m:
        albaran = normalize_spaces(m.group(1))
    m = re.search(r"FECHA\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})", joined, flags=re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)
    return albaran, fecha, ""


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    items: list[dict] = []
    in_table = False
    for line in lines:
        up = line.upper()
        if "COD." in up and "DESCRIPCION" in up and "CANTIDAD" in up:
            in_table = True
            continue
        if not in_table:
            continue
        if "IMPORTE BASE" in up or "PEDIDOS INFERIORES" in up:
            break
        m = re.match(
            r"^(?P<code>\d{3,})\s+(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<price>\d+(?:[.,]\d{2,4}))\s+(?P<imp>\d+(?:[.,]\d{2}))$",
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
                "PrecioUnitario": to_float(m.group("price")),
                "DescuentoPct": None,
                "Importe": to_float(m.group("imp")),
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "esmeralda_structured",
            }
        )
    return items


def parse_page(page, page_num, proveedor_detectado="ESMERALDA"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _extract_header(joined)
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
        "TotalAlbaranPie": np.nan if not items else suma,
    }
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
