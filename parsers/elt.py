from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import fold_upper, normalize_supedido

PARSER_ID = "elt"
PROVIDER_NAME = "ELT"
BRAND_ALIASES = [
    "WWW.ELT.ES",
    "ESPECIALIDADES LUMINOTECNICAS",
    "ESPECIALIDADES LUMINOTÉCNICAS",
    "A50032572",
    "ELT@ELT.ES",
]


def _header(lines: list[str], joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = parse_date_es(joined) or ""
    su_pedido = ""

    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if "N" in up and "ALBARAN" in up and "FECHA" in up and "CODIGO CLIENTE" in up:
            for nxt in lines[idx + 1 : idx + 4]:
                nums = re.findall(r"\b\d{6,}\b", nxt)
                if nums:
                    albaran = nums[0]
                    fecha = parse_date_es(nxt) or fecha
                    break
            break

    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if "REFERENCIA PEDIDO" in up and "N/REFERENCIA" in up:
            for nxt in lines[idx + 1 : idx + 3]:
                nums = re.findall(r"\b\d{5,}\b", nxt)
                if nums:
                    su_pedido = normalize_supedido(nums[0])
                    break
            break

    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> tuple[list[dict], float]:
    start = -1
    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if "CODIGO" in up and "DESCRIP" in up and "CANTIDAD" in up:
            start = idx + 1
            break
    if start < 0:
        return [], 0.0

    items: list[dict] = []
    for line in lines[start:]:
        up = fold_upper(line)
        if "BULTOS" in up and "PESO" in up:
            break
        if "PRODUCTOR ADHERIDO" in up:
            break

        cleaned = normalize_spaces(line)
        m = re.match(r"^(?P<code>\d{5,})\s+(?P<rest>.+)$", cleaned)
        if not m:
            continue

        rest = normalize_spaces(m.group("rest"))
        qty = None
        desc = rest
        qty_match = re.search(r"\s(?P<qty>\d+(?:[.,]\d{1,3}))(?=\s|$)", rest)
        if qty_match:
            qty = to_float(qty_match.group("qty"))
            desc = normalize_spaces(rest[: qty_match.start()])
        desc = re.sub(r"\s+\d{5,}\s*$", "", desc).strip()
        if not desc:
            continue

        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m.group("code"),
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": "",
                "DescuentoPct": None,
                "Importe": None,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "elt_no_importe_visible",
            }
        )

    return items, 0.0


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _header(lines, joined)
    items, suma = _parse_items(lines, page_num, albaran, fecha, su_pedido)

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
