from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "montte"
PROVIDER_NAME = "MONTTE"
BRAND_ALIASES = ["MONTTE", "MONTTE, S.L.", "MONTTE VERDE"]


def _num(token: str | None):
    if not token:
        return None
    token = token.strip().strip("/").replace(":", ",")
    if re.fullmatch(r"\d{3,4}", token):
        token = token[:-2] + "," + token[-2:]
    return to_float(token)


def parse_page(page, page_num, proveedor_detectado="MONTTE"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = ""
    fecha = ""
    supedido = ""
    m = re.search(
        r"(IRUNE\s+01\s+R\d+)\s+LOYOLA\s+NORTE.*?(C\d{2}-\d+)\s+(C\d{2}-\d+)\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        joined,
        re.I,
    )
    if m:
        supedido = normalize_spaces(m.group(1)).upper()
        albaran = m.group(3).upper()
        fecha = parse_date_es(m.group(4)) or m.group(4)

    row_re = re.compile(
        r"^(?P<code>[A-Z0-9]{4,})\s+(?P<um>\S+)\s+(?P<desc>.+?)\s+"
        r"(?P<cped>\d{1,3}(?:[,:]\d{2})?)\s*[/.,]*\s+(?P<cenv>\d+)\s+"
        r"(?P<price>\d{1,4},\d{2})\s+(?P<imp>\d+(?:,\d{2})?)\s*/?$",
        re.I,
    )
    items = []
    suma = 0.0
    for ln in lines:
        if re.search(r"Total\s+IVA", ln, re.I):
            break
        mrow = row_re.match(ln)
        if not mrow:
            continue
        qty = to_float(mrow.group("cenv"))
        price = _num(mrow.group("price"))
        imp = _num(mrow.group("imp"))
        if price is not None and qty and imp is not None and imp > price * qty * 10:
            imp = round(price * qty, 2)
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": supedido,
                "Codigo": mrow.group("code").upper(),
                "Descripcion": normalize_spaces(mrow.group("desc")),
                "CantidadServida": qty,
                "PrecioUnitario": price,
                "DescuentoPct": None,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "",
            }
        )
        if imp is not None:
            suma += imp

    return items, {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": suma if suma else np.nan,
        "TotalAlbaranPie": np.nan,
    }


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
