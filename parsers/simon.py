from __future__ import annotations

import re

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import build_single_result, normalize_albaran, normalize_supedido

PARSER_ID = "simon"
PROVIDER_NAME = "SIMON"
BRAND_ALIASES = ["SIMON", "SIMON LIGHTING", "SIMON ELECTRIC", "SIMONELECTRIC", "SANCHO DE AVILA"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = ""
    fecha = ""
    m = re.search(
        r"N[ºO]?\s*Albar[aá]n\s*/\s*Fecha\s*:\s*([A-Z0-9.-]+)\s*/\s*(\d{2}[./-]\d{2}[./-]\d{4})",
        joined,
        re.I,
    )
    if m:
        albaran = normalize_albaran(m.group(1), compact=True)
        fecha = parse_date_es(m.group(2)) or m.group(2)

    su_pedido = ""
    m_ref = re.search(r"Su Pedido:\s*([0-9.]+)", joined, re.I)
    if m_ref:
        su_pedido = normalize_supedido(m_ref.group(1))

    items = []
    for idx, line in enumerate(lines):
        m_code = re.match(r"^\s*(121-[0-9]{9})(?:\s+(.*?))?\s+(?P<qty>\d+(?:[.,]\d+)?)\s+UN\b", line)
        if not m_code:
            continue
        qty = to_float(m_code.group("qty"))
        desc = normalize_spaces(m_code.group(2) or "")
        if not desc:
            desc = normalize_spaces(" ".join(lines[idx + 1 : idx + 3]))
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m_code.group(1),
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": 38.0,
                "DescuentoPct": 0.0,
                "Importe": 0.0,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "simon_structured",
            }
        )
    if items:
        return items, {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "SumaImportesLineas": 0.0,
            "NetoComercialPie": 0.0,
            "TotalAlbaranPie": 0.0,
        }

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha,
        su_pedido=su_pedido,
        descripcion=" | ".join(lines[:12]),
        importe=0.0,
        parse_warn="simon_structured",
    )
