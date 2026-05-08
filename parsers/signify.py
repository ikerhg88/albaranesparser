from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, to_float

PARSER_ID = "signify"
PROVIDER_NAME = "SIGNIFY"
BRAND_ALIASES = ["SIGNIFY", "IGNIFY", "SIGNIFY POLAND", "PALLET CONTENTS"]


def _date_dot(token: str | None) -> str:
    if not token:
        return ""
    m = re.search(r"(\d{1,2})[.](\d{1,2})[.](\d{2,4})", token)
    if not m:
        return ""
    day, month, year = m.groups()
    if len(year) == 2:
        year = "20" + year
    return f"{int(day):02d}/{int(month):02d}/{int(year):04d}"


def _extract_header(lines: list[str], joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = ""
    su_pedido = ""

    m = re.search(r"N[uú]mero\s+de\s+albar[aá]n\s+(\d{7,10})", joined, re.I)
    if m:
        albaran = m.group(1)
    if not albaran:
        m = re.search(r"\bDelivery\s+number\s+(\d{7,10})\b", joined, re.I)
        if m:
            albaran = m.group(1)
    if not albaran:
        m = re.search(r"\bPacking\s+List\b.*?\b\d{7,10}/[A-Z]\s+(\d{7,10})\b", joined, re.I)
        if m:
            albaran = m.group(1)
    if not albaran:
        m = re.search(r"\b(\d{7,10})\s*/\s*\d{1,3}\b", joined)
        if m:
            albaran = m.group(1)
    if not albaran:
        m = re.search(r"\bAlbaran\b.+?\b(\d{7,10})\b", joined, re.I)
        if m:
            albaran = m.group(1)

    m = re.search(r"\b(\d{1,2}[.]\d{1,2}[.]\d{2,4})\b", joined)
    if m:
        fecha = _date_dot(m.group(1))

    for ln in lines:
        m = re.search(r"(?:Pedido\s+Cliente|Customer\s+PO)\s*:?\s*(.+)$", ln, re.I)
        if m:
            value = normalize_spaces(m.group(1))
            value = re.split(r"\b(?:Trafico|Tráfico|Direccion|Dirección|Pedido|Sales\s+Order|Delivery\s+number)\b", value, flags=re.I)[0]
            value = normalize_spaces(value).strip(":- ")
            if value:
                su_pedido = value
                break

    if not su_pedido:
        m = re.search(r"\b\d{7,10}/\d+\s+(.+?)\s+([A-Z]{2,}\d{2,}[A-Z]?)\s+\d+\s+PC\b", joined, re.I)
        if m:
            su_pedido = normalize_spaces(m.group(1))
            sol = re.search(r"\(Solicitud\s+\d+\)", joined, re.I)
            if sol:
                su_pedido = normalize_spaces(f"{su_pedido} {sol.group(0)}")

    return albaran, fecha, su_pedido


def _parse_delivery_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    joined = " ".join(lines)
    product = ""
    desc = ""
    qty = None

    m_prod = re.search(r"Producto\s*:\s*([A-Z0-9./-]{3,})", joined, re.I)
    if m_prod:
        product = m_prod.group(1).upper()
    if not product:
        m_prod = re.search(r"\bMaterial\s+([A-Z0-9./-]{3,})\b", joined, re.I)
        if m_prod:
            product = m_prod.group(1).upper()
    m_desc = re.search(r"Descripci[oó]n\s*:\s*(.+?)(?:\s+Mediante\b|\s+Pais\b|\s+Pa[ií]s\b|$)", joined, re.I)
    if m_desc:
        desc = normalize_spaces(m_desc.group(1))
    if not desc:
        m_desc = re.search(r"Product\s+description\s+(.+?)(?:\s+Country\s+of\s+origin\b|\s+Customer\s+PO\b|$)", joined, re.I)
        if m_desc:
            desc = normalize_spaces(m_desc.group(1))
    m_qty = re.search(r"\bPCE\s+(\d+(?:[.,]\d+)?)\s+PCE\b", joined, re.I)
    if m_qty:
        qty = to_float(m_qty.group(1))
    if qty is None:
        m_qty = re.search(r"\bMaterial\s+[A-Z0-9./-]{3,}.*?\b(\d+(?:[.,]\d+)?)\s+PCE\b", joined, re.I)
        if m_qty:
            qty = to_float(m_qty.group(1))

    if not product:
        return []
    return [
        {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Codigo": product,
            "Descripcion": desc or product,
            "CantidadServida": qty,
            "PrecioUnitario": None,
            "DescuentoPct": None,
            "Importe": None,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "signify_delivery_no_importe",
        }
    ]


def _parse_pallet_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    items: list[dict] = []
    for ln in lines:
        m = re.search(
            r"\b(?P<delivery>\d{7,10})/\d+\s+(?P<ref>.+?)\s+(?P<code>[A-Z]{2,}\d{2,}[A-Z]?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+PC\b",
            ln,
            re.I,
        )
        if not m:
            continue
        if not albaran:
            albaran = m.group("delivery")
        ref = normalize_spaces(m.group("ref"))
        desc = normalize_spaces(f"{m.group('code').upper()} {ref}".strip())
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido or ref,
                "Codigo": m.group("code").upper(),
                "Descripcion": desc,
                "CantidadServida": to_float(m.group("qty")),
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": None,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "signify_pallet_no_importe",
            }
        )
    return items


def parse_page(page, page_num, proveedor_detectado="SIGNIFY"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _extract_header(lines, joined)

    if "PALLET CONTENTS" in joined.upper():
        items = _parse_pallet_items(lines, page_num, albaran, fecha, su_pedido)
    else:
        items = _parse_delivery_items(lines, page_num, albaran, fecha, su_pedido)

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
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
