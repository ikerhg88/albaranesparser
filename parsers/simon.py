from __future__ import annotations

import re

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import build_single_result, normalize_albaran, normalize_supedido

PARSER_ID = "simon"
PROVIDER_NAME = "SIMON"
BRAND_ALIASES = ["SIMON", "SIMON LIGHTING", "SIMON ELECTRIC", "SIMONELECTRIC", "SANCHO DE AVILA"]


def _extract_header(joined: str) -> tuple[str, str]:
    m = re.search(
        r"N[ºOQ]?\s*Albar[aá]n\s*/\s*Fecha\s*:\s*([A-Z0-9.-]+)\s*/\s*(\d{2}[./-]\d{2}[./-]\d{4})",
        joined,
        re.I,
    )
    if not m:
        return "", ""
    return normalize_albaran(m.group(1), compact=True), parse_date_es(m.group(2)) or m.group(2)


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, fecha = _extract_header(joined)

    su_pedido = ""
    m_ref = re.search(r"Su Pedido:\s*([0-9.]+)", joined, re.I)
    if m_ref:
        su_pedido = normalize_supedido(m_ref.group(1))

    items = []
    for idx, line in enumerate(lines):
        m_code = re.match(
            r"^\s*(?:\d{10,}\s+)?(?P<code>121-[0-9]{9})(?:\s+(?P<desc>.*?))?\s+(?P<qty>\d+(?:[.,]\d+)?)\s+UN\b",
            line,
        )
        if not m_code:
            continue
        qty = to_float(m_code.group("qty"))
        desc = normalize_spaces(m_code.group("desc") or "")
        if not desc:
            desc = normalize_spaces(" ".join(lines[idx + 1 : idx + 3]))
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m_code.group("code"),
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": 38.0 if desc else None,
                "DescuentoPct": 0.0 if desc else None,
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


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
