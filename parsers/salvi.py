from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "salvi"
PROVIDER_NAME = "SALVI"
BRAND_ALIASES = ["SALVI", "SALVILIGHTING", "SALVI S.L."]


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = ""
    supedido = ""
    m = re.search(r"Alb\.\s*venta\s+(\d{4,})", joined, re.I)
    if m:
        albaran = m.group(1)
    m = re.search(r"Fecha\s+env[ií]o\s+(\d{1,2}/\d{1,2}/\d{2,4})", joined, re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)
    m = re.search(r"Su\s+Pedido\s+(.+?)(?:\s+Telefono\b|\s+Tel[eé]fono\b|\s+Page\b|$)", joined, re.I)
    if m:
        supedido = normalize_spaces(m.group(1)).replace(" - ", "-").replace(" / ", "/")
    return albaran, fecha, supedido


def parse_page(page, page_num, proveedor_detectado="SALVI"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, supedido = _extract_header(joined)

    items = []
    item_re = re.compile(r"^(?P<code>[A-Z0-9]{5,})\s+(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+U\b", re.I)
    code_only_re = re.compile(r"^(?P<code>Z?[A-Z0-9]{5,})\s+(?P<desc>[A-Z].+?)\s+u$", re.I)
    idx = 0
    while idx < len(lines):
        ln = lines[idx]
        m = item_re.match(ln)
        warn = "salvi_delivery_no_importe"
        qty = None
        if not m:
            m = code_only_re.match(ln)
            warn = "salvi_delivery_no_qty_no_importe"
        if not m:
            idx += 1
            continue
        code = m.group("code").upper()
        desc = normalize_spaces(m.group("desc"))
        if "qty" in m.groupdict() and m.group("qty"):
            qty = to_float(m.group("qty"))
        nxt_idx = idx + 1
        extras = []
        while warn != "salvi_delivery_no_qty_no_importe" and nxt_idx < len(lines):
            nxt = lines[nxt_idx]
            if item_re.match(nxt) or code_only_re.match(nxt):
                break
            if re.search(r"\b(Transportista|Condiciones|Firma|Mercanc[ií]a|CM\s+SALVI)\b", nxt, re.I):
                break
            if nxt.strip() and not re.search(r"^(Page|Telefono|Horario)\b", nxt, re.I):
                extras.append(nxt)
            nxt_idx += 1
        if extras:
            desc = normalize_spaces(f"{desc} {' '.join(extras)}")
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": supedido,
                "Codigo": code,
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": None,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": warn,
            }
        )
        idx = nxt_idx

    return items, {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
