from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "vizcaina"
PROVIDER_NAME = "VIZCAINA"
BRAND_ALIASES = [
    "VIZCAINA DE PETROLEOS",
    "VIZCAINA DE PETROLEOS, S.L.",
    "V1ZCAINA DE PETROLEOS",
    "V!ZCAINA DE PETROLEO",
    "B48484752",
    "ES00020HF021Q",
]


def _extract_albaran(joined: str) -> str:
    for pat in (
        r"N[^\w]{0,3}\s*ALBAR\S*\s*[:#-]?\s*([0-9A-Z/-]{5,})",
        r"ALBAR\S*\s*[:#-]?\s*([0-9A-Z/-]{5,})",
    ):
        m = re.search(pat, joined, flags=re.I)
        if m:
            return normalize_spaces(m.group(1)).strip(" .,:;-")
    return ""


def _extract_quantity(lines: list[str], joined: str) -> float | None:
    for probe in [*lines, joined]:
        up = probe.upper().replace("GASOLEOA", "GASOLEO A")
        if "GASOLEO A" not in up:
            continue
        matches = re.findall(r"(?<![A-Z0-9])(\d{2,5})(?![A-Z0-9])", probe)
        if matches:
            return to_float(matches[-1])
    return None


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran = _extract_albaran(joined)
    fecha = parse_date_es(joined) or ""
    cantidad = _extract_quantity(lines, joined)
    codigo = "B2" if re.search(r"\bB2\b", joined, flags=re.I) else ""

    item = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": "",
        "Codigo": codigo,
        "Descripcion": "GASOLEO A",
        "CantidadPedida": None,
        "CantidadServida": cantidad,
        "CantidadPendiente": None,
        "UnidadesPor": None,
        "PrecioUnitario": "",
        "DescuentoPct": None,
        "Importe": None,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": "vizcaina_no_importe_visible",
    }
    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": "",
        "SumaImportesLineas": 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }
    return [item], meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
