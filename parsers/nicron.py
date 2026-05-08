from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es

PARSER_ID = "nicron"
PROVIDER_NAME = "NICRON"
BRAND_ALIASES = ["NICRON", "NICRONSL@GMAIL.COM", "WWW.NICRONSL.COM"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran = ""
    m = re.search(r"NOTA\s+DE\s+ENTREGA\s+N[ºO]?\s*([0-9 ]{4,})", joined, re.I)
    if m:
        albaran = re.sub(r"\D", "", m.group(1))
    if not albaran:
        m = re.search(r"\b([0-9]\s+[0-9]\s+[0-9]{3})\b", joined)
        if m:
            albaran = re.sub(r"\D", "", m.group(1))
    fecha = parse_date_es(joined) or ""
    m_date = re.search(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/u]\s*(?:20)?\s*(\d{2})\b", joined, re.I)
    if m_date and not fecha:
        d, mth, yy = m_date.groups()
        fecha = f"{int(d):02d}/{int(mth):02d}/20{int(yy):02d}"
    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": "",
        "Codigo": "",
        "Descripcion": "Nota de entrega manuscrita Nicron - revisar visualmente",
        "CantidadServida": None,
        "PrecioUnitario": "",
        "DescuentoPct": None,
        "Importe": None,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": "nicron_handwritten_review",
    }
    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": "",
        "SumaImportesLineas": 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
