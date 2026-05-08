from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import fold_upper, normalize_supedido

PARSER_ID = "vascoplast"
PROVIDER_NAME = "VASCOPLAST"
BRAND_ALIASES = ["VASCOPLAST", "B75174250", "VASCOPLAST@VASCOPLAST.COM", "WWW.VASCOPLAST.COM"]

NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d{2,4})|\d+(?:,\d{2,4})"


def _header(lines: list[str], joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = parse_date_es(joined) or ""
    su_pedido = ""

    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if "N" in up and "DOCUMENTO" in up and "FECHA" in up:
            for nxt in lines[idx + 1 : idx + 4]:
                m = re.search(r"\b(\d{5,})\s+(\d{1,2}/\d{1,2}/\d{2,4})\b", nxt)
                if m:
                    albaran = m.group(1)
                    fecha = parse_date_es(m.group(2)) or fecha
                    break
            break

    for idx, line in enumerate(lines):
        if "REFERENCIA CLIENTE" in fold_upper(line):
            for nxt in lines[idx + 1 : idx + 3]:
                m = re.search(r"\b([A-Z]/\d{5,8})\b", nxt, flags=re.I)
                if m:
                    su_pedido = normalize_supedido(m.group(1))
                    break
            break

    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> tuple[list[dict], float]:
    start = -1
    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if "DESCRIPCION" in up and "CANTIDAD" in up and "PRECIO" in up and "TOTAL" in up:
            start = idx + 1
            break
    if start < 0:
        return [], 0.0

    items: list[dict] = []
    suma = 0.0
    row_re = re.compile(
        rf"^(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s*ud\.?\s+"
        rf"(?P<price>{NUM})\s+(?P<imp>{NUM})\s*$",
        flags=re.I,
    )
    for line in lines[start:]:
        up = fold_upper(line)
        if "NO SE ADMITIRAN" in up or "DETALLE DE IMPUESTOS" in up:
            break
        cleaned = normalize_spaces(line)
        m = row_re.match(cleaned)
        if not m:
            continue
        qty = to_float(m.group("qty"))
        price = to_float(m.group("price"))
        importe = to_float(m.group("imp"))
        desc = normalize_spaces(m.group("desc"))
        items.append(
            {
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
        )
        suma += float(importe or 0.0)
    return items, suma


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _header(lines, joined)
    items, suma = _parse_items(lines, page_num, albaran, fecha, su_pedido)

    total = np.nan
    for line in lines[-20:]:
        if "SUBTOTAL" in fold_upper(line):
            m = re.search(NUM, line)
            if m:
                total = to_float(m.group(0)) or np.nan
                break

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
