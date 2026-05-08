from __future__ import annotations

import re

import numpy as np

from common import fix_qty_price_import, normalize_spaces, parse_date_es, to_float

PARSER_ID = "axor"
PROVIDER_NAME = "AXOR"
BRAND_ALIASES = ["AXOR", "AXOR RENTALS", "AXOR RENTALS S.L.U.", "B01213032"]


def _num(token: str | None) -> float | None:
    if not token:
        return None
    return to_float(token.replace(" ", ""))


def _extract_header(joined: str) -> tuple[str, str, str]:
    albaran = ""
    fecha = ""
    su_pedido = ""

    m = re.search(
        r"ALBAR[ÁA]N\s+DE\s+DEVOLUCI[ÓO]N\s*:?\s*([0-9]{3,5}\s*[-/]\s*[0-9]{6,10})",
        joined,
        flags=re.I,
    )
    if m:
        albaran = re.sub(r"\s+", "", m.group(1))

    m = re.search(r"FECHA\s+(?:INICIO|VALOR)\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})", joined, flags=re.I)
    if m:
        fecha = parse_date_es(m.group(1)) or m.group(1)

    m = re.search(r"\bPEDIDO\s*:?\s*([A-Z0-9./-]{3,})", joined, flags=re.I)
    if m and not re.match(r"C\.?I\.?F", m.group(1), flags=re.I):
        su_pedido = normalize_spaces(m.group(1)).upper()

    return albaran, fecha, su_pedido


def _parse_items(lines: list[str], page_num: int, albaran: str, fecha: str, su_pedido: str) -> list[dict]:
    items: list[dict] = []
    current_idx: int | None = None
    started = False

    for line in lines:
        up = line.upper()
        if "ART" in up and "CONCEPTO" in up and "CAN" in up and "IMPORTE" in up:
            started = True
            continue
        if not started:
            continue
        if "ES DEVOLUCI" in up or "CONTRATO DE ALQUILER" in up or "LUGAR RETIRADA" in up:
            break

        clean = normalize_spaces(line)
        if not clean:
            continue

        m = re.match(
            r"^(?P<code>\d{7,13})\s+(?P<desc>.+?)\s+(?P<qty>\d{1,4},\s*\d{2})"
            r"(?:\s+(?P<price>\d{1,4},\s*\d{2,4}))?(?:\s+(?P<imp>\d{1,4},\s*\d{2}))?$",
            clean,
            flags=re.I,
        )
        if m:
            item = {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": m.group("code"),
                "Descripcion": normalize_spaces(m.group("desc")),
                "CantidadServida": _num(m.group("qty")),
                "PrecioUnitario": _num(m.group("price")),
                "DescuentoPct": None,
                "Importe": _num(m.group("imp")),
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "axor_no_importe_visible" if not m.group("imp") else "",
            }
            items.append(fix_qty_price_import(item))
            current_idx = len(items) - 1
            continue

        m_seguro = re.match(r"^(SEGURO\s+SEG[ÚU]N\s+LEGISLACI[ÓO]N\s+VIGENTE)\s+(\d{1,4},\s*\d{2})$", clean, flags=re.I)
        if m_seguro:
            if current_idx is not None and not items[current_idx].get("Importe"):
                items[current_idx]["Importe"] = _num(m_seguro.group(2))
                warn = items[current_idx].get("ParseWarn") or ""
                items[current_idx]["ParseWarn"] = normalize_spaces(f"{warn}; axor_seguro_importe".strip("; "))
            else:
                items.append(
                    {
                        "Proveedor": PROVIDER_NAME,
                        "Parser": PARSER_ID,
                        "AlbaranNumero": albaran,
                        "FechaAlbaran": fecha,
                        "SuPedidoCodigo": su_pedido,
                        "Codigo": "",
                        "Descripcion": normalize_spaces(m_seguro.group(1)),
                        "CantidadServida": None,
                        "PrecioUnitario": None,
                        "DescuentoPct": None,
                        "Importe": _num(m_seguro.group(2)),
                        "Pagina": page_num,
                        "Pdf": "",
                        "ParseWarn": "axor_seguro_importe",
                    }
                )
            continue

        if "GEST" in up and "RES" in up:
            items.append(
                {
                    "Proveedor": PROVIDER_NAME,
                    "Parser": PARSER_ID,
                    "AlbaranNumero": albaran,
                    "FechaAlbaran": fecha,
                    "SuPedidoCodigo": su_pedido,
                    "Codigo": "",
                    "Descripcion": clean,
                    "CantidadServida": None,
                    "PrecioUnitario": None,
                    "DescuentoPct": None,
                    "Importe": None,
                    "Pagina": page_num,
                    "Pdf": "",
                    "ParseWarn": "axor_no_importe_visible",
                }
            )

    return items


def parse_page(page, page_num, proveedor_detectado="AXOR"):
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
