from __future__ import annotations

import re

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import build_single_result, normalize_albaran, normalize_supedido

PARSER_ID = "urkunde"
PROVIDER_NAME = "URKUNDE"
BRAND_ALIASES = ["URKUNDE", "URKUND", "URKUNDE S.A.", "URKUNDE.ES"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    m_alb = re.search(r"Albar[aá]n\s+([A-Z]{1,3}\d{6,})", joined, re.I)
    albaran = normalize_albaran(m_alb.group(1) if m_alb else "", compact=True)
    m_fecha = re.search(r"Fecha:\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", joined, re.I)
    fecha = parse_date_es(m_fecha.group(1)) if m_fecha else ""
    m_sup = re.search(r"\b(\d{2})[. ]?(\d{3})/(\d{2})(?:/[A-Z])?\b", joined, re.I)
    su_pedido = f"{m_sup.group(1)}{m_sup.group(2)}/{m_sup.group(3)}" if m_sup else ""

    code = ""
    desc = ""
    qty = None
    for idx, line in enumerate(lines):
        m_line = re.search(r"\b(\d{5,})\s+(.+?)\s+M\s+\w+\s+\d+\s+(\d+(?:[.,]\d+)?)\b", line)
        if m_line:
            code = m_line.group(1)
            prefix = lines[idx - 1] if idx > 0 else ""
            desc = normalize_spaces(f"{prefix} {m_line.group(2)}")
            qty = to_float(m_line.group(3))
            break

    return build_single_result(
        provider_name=PROVIDER_NAME,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha=fecha or "",
        su_pedido=su_pedido,
        descripcion=desc or " | ".join(lines[:12]),
        codigo=code,
        cantidad=qty,
        dto=0.0,
        importe=0.0,
        parse_warn="urkunde_structured",
    )
