from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float
from ._vendor_simple import normalize_supedido

PARSER_ID = "murrplastik"
PROVIDER_NAME = "MURRPLASTIK"
BRAND_ALIASES = ["MURRPLASTIK", "MURRPLASTIK S.L.", "B20684106", "VENTAS@MURRPLASTIK.ES"]


def _extract_header(joined: str) -> tuple[str, str, str]:
    fecha = parse_date_es(joined) or ""
    su_pedido = ""
    albaran = ""

    dot_date = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", joined)
    if dot_date and not fecha:
        d, mth, y = dot_date.groups()
        if len(y) == 2:
            y = "20" + y
        fecha = f"{int(d):02d}/{int(mth):02d}/{int(y):04d}"

    m = re.search(r"N[uú]mero/Fecha(?:\D+\d{4,6})?\D+([0-9]{7,})\s*/\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}", joined, flags=re.I)
    if m:
        albaran = m.group(1)

    m = re.search(r"N[ºo]\s*de\s+referencia/Fecha\s*([0-9.,/\-A-Z]{5,})\s*/\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}", joined, flags=re.I)
    if m:
        su_pedido = normalize_supedido(m.group(1).replace(",", "."))

    m = re.search(r"N\S{0,3}\s*pedido\s+cliente\s*[:#-]?\s*([0-9.,/\-A-Z]{5,})", joined, flags=re.I)
    if m:
        su_pedido = normalize_supedido(m.group(1).replace(",", "."))

    m = re.search(r"N\S{0,3}\s*pedido\s*[:#-]?\s*([A-Z0-9]{5,})\s+Fecha", joined, flags=re.I)
    if m:
        albaran = m.group(1).upper()
        albaran = albaran.replace("W", "0").replace("I", "1")

    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> tuple[list[dict], float]:
    items = []
    suma = 0.0
    for idx, line in enumerate(lines):
        cleaned = normalize_spaces(line)
        m = re.match(r"^(?P<pos>\d+)\s+(?P<code>\d{6,})\s+(?P<qty>\d+(?:[.,]\d+)?)\s+PC\b", cleaned, flags=re.I)
        if m:
            desc = ""
            for nxt in lines[idx + 1 : idx + 5]:
                if "Nº de referencia" in nxt or "N° de referencia" in nxt:
                    break
                if re.search(r"[A-Za-zÁÉÍÓÚáéíóú]", nxt):
                    desc = normalize_spaces(nxt)
                    break
            qty = to_float(m.group("qty"))
            item = {
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
                "ParseWarn": "murrplastik_delivery_no_importe",
            }
            items.append(item)
            return items, suma

        m_head = re.match(r"^(?P<pos>\d+)\s+(?P<code>\d{6,})\s*$", cleaned)
        if m_head:
            desc = ""
            qty = price = importe = None
            for nxt in lines[idx + 1 : idx + 8]:
                if not desc and re.search(r"[A-Za-zÁÉÍÓÚáéíóú]", nxt) and "Número de arancel" not in nxt and "País de origen" not in nxt:
                    desc = normalize_spaces(nxt)
                m_vals = re.search(
                    r"(?P<qty>\d+(?:[.,]\d+)?)\s+PC\s+(?P<price>\d+(?:[.,]\d+)?)\s+EUR\s+1\s+PC\s+(?P<imp>\d+(?:[.,]\d+)?)",
                    nxt,
                    flags=re.I,
                )
                if m_vals:
                    qty = to_float(m_vals.group("qty"))
                    price = to_float(m_vals.group("price"))
                    importe = to_float(m_vals.group("imp"))
                    break
            if importe is not None or qty is not None:
                item = {
                    "Proveedor": PROVIDER_NAME,
                    "Parser": PARSER_ID,
                    "AlbaranNumero": albaran,
                    "FechaAlbaran": fecha,
                    "SuPedidoCodigo": su_pedido,
                    "Codigo": m_head.group("code"),
                    "Descripcion": desc,
                    "CantidadServida": qty,
                    "PrecioUnitario": price,
                    "DescuentoPct": None,
                    "Importe": importe,
                    "Pagina": page_num,
                    "Pdf": "",
                    "ParseWarn": "",
                }
                items.append(item)
                suma += float(importe or 0.0)
                return items, suma

    for line in lines:
        cleaned = normalize_spaces(line)
        m = re.match(r"^(?P<code>\d{6,})\s+(?P<rest>.+)$", cleaned, flags=re.I)
        if not m:
            continue
        nums = list(re.finditer(r"\d+(?:[.,]\d+)", m.group("rest")))
        if len(nums) < 3:
            continue
        desc = normalize_spaces(m.group("rest")[: nums[0].start()])
        values = [to_float(n.group(0)) for n in nums]
        if len(values) == 3:
            qty = 1.0
            price = values[0]
            importe = values[2]
        else:
            qty = values[0]
            price = values[1]
            importe = values[-1]
        item = {
            "Proveedor": PROVIDER_NAME,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": su_pedido,
            "Codigo": m.group("code"),
            "Descripcion": desc,
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": None,
            "Importe": importe,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "",
        }
        items.append(item)
        suma += float(importe or 0.0)
    return items, suma


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, su_pedido = _extract_header(joined)
    items, suma = _parse_items(lines, page_num, albaran, fecha, su_pedido)
    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": suma if suma else np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
