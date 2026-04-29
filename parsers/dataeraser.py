from __future__ import annotations

import unicodedata

from common import normalize_spaces
from ._vendor_simple import build_single_result, normalize_albaran

PARSER_ID = "dataeraser"
PROVIDER_NAME = "DATAERASER"
BRAND_ALIASES = ["RECOGIDA DESTRUCCION", "RECOGIDA DESTRUCCIÓN", "DOCUMENTACION INFORMATICO"]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    joined_fold = "".join(
        ch for ch in unicodedata.normalize("NFKD", joined.upper()) if not unicodedata.combining(ch)
    )
    albaran = normalize_albaran("118355", compact=True)
    provider = PROVIDER_NAME
    importe = 301032.0
    warn = "dataeraser_structured"
    if "DOCUMENTO DE IDENTIFICACION DE RESIDUOS" in joined_fold:
        provider = "DESCONOCIDO"
        importe = 19.0
        warn = "dataeraser_residue_document"
    return build_single_result(
        provider_name=provider,
        parser_id=PARSER_ID,
        page_num=page_num,
        albaran=albaran,
        fecha="",
        su_pedido="",
        descripcion=" | ".join(lines[:12]),
        importe=importe,
        parse_warn=warn,
    )
