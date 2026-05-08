from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "kalon"
PROVIDER_NAME = "KALON"
BRAND_ALIASES = ["KALON", "KALON MANTENIMIENTO INDUSTRIAL", "CITRIKEM"]


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = parse_date_es(joined) or ""
    su_pedido = ""

    m = re.search(r"\b(AVK\d{2}-\d{4,})\b", joined, flags=re.I)
    if m:
        albaran = m.group(1).upper()

    m = re.search(
        r"\b\d{6,}\s*/\s*([A-Z]{2,}\d{5,})\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        joined,
        flags=re.I,
    )
    if m:
        su_pedido = m.group(1).upper()
        fecha = parse_date_es(m.group(2)) or fecha

    return albaran, fecha, su_pedido


def _parse_item(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> tuple[list[dict], float]:
    for idx, line in enumerate(lines):
        m = re.match(
            r"^(?P<code>\d{5,})\s+(?P<desc>.+?)\s+\d+\s*LT\s+\d+\s+EN\s+"
            r"(?P<price>\d+(?:[.,]\d+)?)\s+(?P<base>\d+(?:[.,]\d+)?)\b",
            normalize_spaces(line),
            flags=re.I,
        )
        if not m:
            m = re.match(
                r"^(?P<code>\d{5,})\s+(?P<desc>.+?)\s+\S{1,3}\s*LT\s+\d+\s+EN\s+"
                r"(?P<price>\d+(?:[.,]\d+)?)\s+(?P<base>\d+(?:[.,]\d+)?)\b",
                normalize_spaces(line),
                flags=re.I,
            )
        if not m:
            continue

        qty = None
        for nxt in lines[idx + 1 : idx + 4]:
            q = re.search(r"\b\d+\s+EN\s+(\d+(?:[.,]\d+)?)\b", nxt, flags=re.I)
            if q:
                qty = to_float(q.group(1))
                break

        price = to_float(m.group("price"))
        importe = to_float(m.group("base"))
        if qty is None and price not in (None, 0) and importe is not None:
            qty = round(float(importe) / float(price), 2)

        desc_parts = [normalize_spaces(m.group("desc"))]
        for nxt in lines[idx + 1 : idx + 4]:
            up = nxt.upper()
            if "LOTE" in up or "DESENGRASANTE" in up:
                desc_parts.append(normalize_spaces(nxt))

        item = {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Codigo": m.group("code"),
            "Descripcion": " | ".join(desc_parts),
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": None,
            "Importe": importe,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "",
        }
        return [item], float(importe or 0.0)
    return [], 0.0


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _extract_header(joined)
    items, suma = _parse_item(lines, page_num, albaran, fecha, su_pedido)

    total = np.nan
    m_total = re.search(r"\b\d+(?:[.,]\d+)?\s+21\s+\d+(?:[.,]\d+)?\s+(\d+(?:[.,]\d+)?)\b", joined)
    if m_total:
        total = to_float(m_total.group(1)) or np.nan

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": suma if suma else np.nan,
        "TotalAlbaranPie": total,
    }
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
