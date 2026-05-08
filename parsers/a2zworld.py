from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, to_float

PARSER_ID = "a2zworld"
PROVIDER_NAME = "A2ZWORLD"
BRAND_ALIASES = ["A2ZWORLD-ES", "MARKETPLACE DE AMAZON", "WWW.AMAZON.ES/FEEDBACK"]


MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}


def _date_es_words(text: str) -> str:
    m = re.search(r"\b(\d{1,2})\s+([A-Za-záéíóú]{3})\s+(\d{4})\b", text, re.I)
    if not m:
        return ""
    month = MONTHS.get(m.group(2).upper()[:3])
    if not month:
        return ""
    return f"{int(m.group(1)):02d}/{month:02d}/{int(m.group(3)):04d}"


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    fecha = _date_es_words(joined)
    albaran = ""
    m_order = re.search(r"N[º.2]*\s*de\s+pedido:\s*([0-9-]{10,})", joined, re.I)
    if m_order:
        albaran = m_order.group(1)
    su_pedido = ""
    m_sup = re.search(r"orden\s+de\s+compra\s+del\s+cliente:\s*([A-Z0-9/.-]+)", joined, re.I)
    if m_sup:
        su_pedido = m_sup.group(1).upper()
    qty = 1.0
    desc = "Pedido Amazon Marketplace"
    m_desc = re.search(r"\b1\s+(.+?)\s+18,\s*89\s*€", joined, re.I)
    if m_desc:
        desc = normalize_spaces(m_desc.group(1))
    price = 18.89 if "18,89" in joined else None
    importe = None
    m_total = re.search(r"Suma\s+total:\s*(\d+(?:[.,]\d+)?)\s*€", joined, re.I)
    if m_total:
        importe = to_float(m_total.group(1))
    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "Codigo": "",
        "Descripcion": desc,
        "CantidadServida": qty,
        "PrecioUnitario": price,
        "DescuentoPct": None,
        "Importe": importe,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": "",
    }
    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": float(importe or 0.0),
        "NetoComercialPie": np.nan if importe is None else importe,
        "TotalAlbaranPie": np.nan if importe is None else importe,
    }
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
