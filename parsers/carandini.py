from __future__ import annotations

import re

from common import normalize_spaces, parse_date_es
from ._vendor_simple import build_single_result, normalize_albaran, normalize_supedido

PARSER_ID = "carandini"
PROVIDER_NAME = "CARANDINI"
BRAND_ALIASES = ["CARANDINI", "C Y G CARANDINI", "A08015166", "933174008"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = ""
    fecha = ""
    m_any = re.search(r"\b(V?AP\d{2}-\d{5})\b", joined, re.I)
    if m_any:
        raw_albaran = m_any.group(1).upper()
        if raw_albaran.startswith("AP"):
            raw_albaran = "V" + raw_albaran
        albaran = normalize_albaran(raw_albaran, compact=False).upper()
    for idx, line in enumerate(lines):
        if "ALBARAN" in line.upper() or "ALBARÁN" in line.upper():
            window = " ".join(lines[idx : idx + 5])
            m_date = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", window)
            if m_date:
                fecha = parse_date_es(m_date.group(1)) or m_date.group(1)
            break

    su_pedido = ""
    m_sup = re.search(r"Pedido cliente\s+([0-9. /_A-Z-]{4,}?)(?:\s+Pedido\b|\s+Incoterm\b|$)", joined, re.I)
    if m_sup:
        raw_sup = m_sup.group(1).replace("_", "/").replace(".", "").upper()
        m_code = re.search(r"1?(\d{2})(\d{3})/(\d)/?(\d)", raw_sup)
        if m_code:
            su_pedido = f"{m_code.group(1)}{m_code.group(2)}/{m_code.group(3)}{m_code.group(4)}"
        else:
            su_pedido = normalize_supedido(raw_sup)

    code = ""
    desc = ""
    for idx, line in enumerate(lines):
        m_line = re.match(r"^(\d{6})\s+(.+?)(?:\s+\d+\s+Unidad)?$", line.strip(), re.I)
        if m_line:
            code = m_line.group(1)
            desc = normalize_spaces(m_line.group(2))
            break

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha,
        su_pedido=su_pedido,
        descripcion=desc or " | ".join(lines[:12]),
        codigo=code,
        importe=0.0,
        parse_warn="carandini_structured",
    )
