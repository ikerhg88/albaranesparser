from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "tc_medida"
PROVIDER_NAME = "TC MEDIDA"
BRAND_ALIASES = ["TC MEDIDA", "TC MEDIDA Y CONTROL", "TC-SA.ES", "A83703041"]


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = ""
    supedido = ""
    m = re.search(r"Albar[aá]n\s*:\s*([A-Z]{1,3}\s*\d{4,})", joined, re.I)
    if m:
        albaran = normalize_spaces(m.group(1)).upper()
    m = re.search(r"Fecha\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})", joined, re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)
    m = re.search(r"S[/I]?\s*Pedido\s*:\s*([A-Z0-9./-]+)", joined, re.I)
    if m:
        supedido = m.group(1).upper()
    return albaran, fecha, supedido


def parse_page(page, page_num, proveedor_detectado="TC MEDIDA"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, supedido = _extract_header(joined)
    certificate = "CERTIFICADO CONFORMIDAD" in joined.upper()

    priced_re = re.compile(
        r"^(?:(?P<qty>\d+(?:[.,]\d+)?)\s+)?(?P<unit>mtrs\.|unid\.)\s+"
        r"(?P<ref>.+?)\s+[/I]\s+(?P<price>\d{1,4},\d{2})\s+(?P<imp>\d{1,4},\d{2})$",
        re.I,
    )
    port_re = re.compile(
        r"^(?P<unit>unid\.)\s+(?P<ref>Portes\s+y\s+gastos\s+de\s+expedici[oó]n)\s+"
        r"(?P<price>\d{1,4},\d{2})\s+(?P<imp>\d{1,4},\d{2})$",
        re.I,
    )
    cert_re = re.compile(r"^(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<unit>mtrs\.|unid\.)\s+(?P<ref>.+)$", re.I)
    items = []
    suma = 0.0
    idx = 0
    while idx < len(lines):
        ln = lines[idx]
        m = priced_re.match(ln)
        no_amount = False
        port_match = False
        if not m:
            m = port_re.match(ln)
            port_match = bool(m)
        if not m and certificate:
            m = cert_re.match(ln)
            no_amount = True
        if not m:
            idx += 1
            continue
        qty = to_float(m.group("qty")) if ("qty" in m.groupdict() and m.group("qty")) else 1.0
        ref = normalize_spaces(m.group("ref")).replace("  ", " ")
        desc = ref
        if not port_match and idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if not priced_re.match(nxt) and not cert_re.match(nxt) and not re.search(r"\b(TOTAL|Condiciones|IBAN|TC Medida)\b", nxt, re.I):
                desc = normalize_spaces(f"{desc} {nxt}")
                idx += 1
        price = None if no_amount else to_float(m.group("price"))
        imp = None if no_amount else to_float(m.group("imp"))
        code = ref.split()[0] if ref else ""
        if port_match:
            code = "PORTES"
        items.append(
            {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": supedido,
                "Codigo": code,
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": price,
                "DescuentoPct": None,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "tc_certificate_no_importe" if no_amount else "",
            }
        )
        if imp is not None:
            suma += imp
        idx += 1

    return items, {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": suma if suma else np.nan,
        "TotalAlbaranPie": np.nan,
    }


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
