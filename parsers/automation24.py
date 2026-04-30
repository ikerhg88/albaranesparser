from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "automation24"
PROVIDER_NAME = "AUTOMATION24"
BRAND_ALIASES = ["AUTOMATION24", "AUTOMATION24 GMBH", "AUTOMATION24.ES", "DE277419107"]


def _normalize_supedido(raw: str | None) -> str:
    value = normalize_spaces(raw or "").upper()
    value = re.sub(r"\s+", "", value)
    m = re.fullmatch(r"(\d{2})[.](\d{3})/(\d{2})", value)
    if m:
        return f"{m.group(1)}{m.group(2)}/{m.group(3)}"
    return value


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = ""
    su_pedido = ""
    m = re.search(r"N[°º]?\s*doc\.?\s*([0-9]{4}-[0-9]{6,})", joined, flags=re.I)
    if m:
        albaran = m.group(1)
    m = re.search(r"\bFecha\s+(\d{1,2}/\d{1,2}/\d{2,4})", joined, flags=re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)
    else:
        fecha = parse_date_es(joined) or ""
    m = re.search(r"Su\s+ref\.?\s+Pedido\s+n[ºo]?\s*([0-9./-]{5,})", joined, flags=re.I)
    if not m:
        m = re.search(r"Su\s+n[ºo]?\s+ped\.?\s+Pedido\s+n[ºo]?\s*([0-9./-]{5,})", joined, flags=re.I)
    if m:
        su_pedido = _normalize_supedido(m.group(1))
    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    items: list[dict] = []
    for line in lines:
        m = re.match(
            r"^(?P<code>\d{5,})\s+(?P<desc>.+?)\s+\d{2}[./]\d{2}[./]\d{4}\s+(?P<qty>\d+(?:[.,]\d+)?)\s*Pzas\.?",
            line,
            flags=re.I,
        )
        if not m:
            continue
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m.group("code"),
                "Descripcion": normalize_spaces(m.group("desc")),
                "CantidadServida": to_float(m.group("qty")),
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": 0.0,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "automation24_structured",
            }
        )
    return items


def parse_page(page, page_num, proveedor_detectado="AUTOMATION24"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _extract_header(joined)
    items = _parse_items(lines, page_num, albaran, fecha, su_pedido)
    suma = sum(float(item.get("Importe") or 0.0) for item in items)
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
