from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es

PARSER_ID = "plataformas_donosti"
PROVIDER_NAME = "PLATAFORMAS DONOSTI"
BRAND_ALIASES = ["PLATAFORMAS DONOSTI", "B-20691226", "B20691226"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    fecha = parse_date_es(joined) or ""
    albaran = ""
    m = re.search(r"Contrato\s+N[ºO]\s*:\s*([0-9]{5,})", joined, re.I)
    if m:
        albaran = m.group(1)
    su_pedido = albaran
    desc = "Albaran de entrega plataforma"
    m_machine = re.search(r"Máquina Arrendada:\s*[0-9]+\s+(.+?)\s+Matricula", joined, re.I)
    if not m_machine:
        m_machine = re.search(r"Maquina Arrendada:\s*[0-9]+\s+(.+?)\s+Matricula", joined, re.I)
    if m_machine:
        desc = normalize_spaces(m_machine.group(1))
    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "Codigo": "",
        "Descripcion": desc,
        "CantidadServida": 1.0,
        "PrecioUnitario": "",
        "DescuentoPct": None,
        "Importe": None,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": "plataformas_no_importe_visible",
    }
    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
