from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "itevelesa"
PROVIDER_NAME = "ITEVELESA"
BRAND_ALIASES = ["ITEVELESA", "RED ITV ITEVELESA", "ITV2001@ITEVELESA.COM", "GRUPO ITEVELESA"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    fecha = parse_date_es(joined) or ""
    albaran = ""
    m = re.search(r"\bP\s*1\s*([0-9]{5,})\b", joined, re.I)
    if m:
        albaran = f"P1{m.group(1)}"
    su_pedido = ""
    m_info = re.search(r"N[ºO]\s*INFORME\s*([0-9]{5,})", joined, re.I)
    if m_info:
        su_pedido = m_info.group(1)
    if not su_pedido:
        m_mat = re.search(r"\b([0-9]{4}-[A-Z]{3})\b", joined, re.I)
        if m_mat:
            su_pedido = m_mat.group(1).upper()
    importe = None
    m_imp = re.search(r"ZENBATEKOA\s*/\s*IMPORTE\s*(\d+(?:[.,]\d+)?)", joined, re.I)
    if m_imp:
        importe = to_float(m_imp.group(1))
    total = None
    m_total = re.search(r"TOTAL\s*\(EUROS\)\s*(\d+(?:[.,]\d+)?)", joined, re.I)
    if m_total:
        total = to_float(m_total.group(1))
    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "Codigo": "",
        "Descripcion": "Inspeccion ITV periodica",
        "CantidadServida": 1.0,
        "PrecioUnitario": importe,
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
        "TotalAlbaranPie": np.nan if total is None else total,
    }
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
