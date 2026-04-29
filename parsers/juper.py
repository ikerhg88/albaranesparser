from __future__ import annotations

import re
import unicodedata

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "juper"
PROVIDER_NAME = "JUPER"
BRAND_ALIASES = ["JUPER", "JUPER BAT", "JUPERBAT", "JUPER S.A.U."]

ALB_RE = re.compile(r"ALBAR[ÁA]N[^A-Z0-9]{0,24}(AV\d{6,})", re.I)
ALT_ALB_RE = re.compile(r"\bAV\d{6,}\b", re.I)
CLIENT_RE = re.compile(
    r"(?:BEZERO\s+ZK\./N[ºO°]?\s*CL[IL1]ENTE|N[ºO°]?\s*CL[IL1]ENTE)[^A-Z0-9]{0,12}([A-Z]{0,3}\d{4,})",
    re.I,
)
CLIENT_ASCII_RE = re.compile(
    r"(?:BEZERO\s+ZK\./N[ºO°]?\s*C\W*L\W*I?\W*E\W*N\W*T\W*E|N[ºO°]?\s*C\W*L\W*I?\W*E\W*N\W*T\W*E)"
    r"[^A-Z0-9]{0,16}([A-Z]{0,3}\d{4,})",
    re.I,
)


def _ascii_upper(value: str) -> str:
    text = value or ""
    normalized = unicodedata.normalize("NFKD", text.upper())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_client_code(raw: str) -> str:
    token = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not token:
        return ""
    m = re.match(r"[A-Z]{1,3}(\d{4,})$", token)
    if m:
        return m.group(1)
    return token


def _extract_header(lines: list[str], joined: str) -> tuple[str, str, str]:
    albaran = ""

    joined_ascii = _ascii_upper(joined)
    m = ALB_RE.search(joined_ascii)
    if m:
        albaran = m.group(1).upper()
    if not albaran:
        m2 = ALT_ALB_RE.search(joined_ascii)
        if m2:
            albaran = m2.group(0).upper()

    fecha = parse_date_es(joined)

    supedido = ""
    for txt in (joined, joined_ascii):
        m3 = CLIENT_RE.search(txt)
        if m3:
            supedido = _normalize_client_code(m3.group(1))
            if supedido:
                break
        m3b = CLIENT_ASCII_RE.search(txt)
        if m3b:
            supedido = _normalize_client_code(m3b.group(1))
            if supedido:
                break

    if not supedido:
        for ln in lines[:40]:
            up = _ascii_upper(ln)
            if not re.search(r"C\W*L\W*I?\W*E\W*N\W*T\W*E", up):
                continue
            m4 = re.search(r"([A-Z]{0,3}\d{4,})", up)
            if m4:
                supedido = _normalize_client_code(m4.group(1))
                if supedido:
                    break
    return albaran, fecha, supedido


def _parse_row(line: str):
    line = normalize_spaces(line)
    if not line:
        return None
    up = _ascii_upper(line)
    if any(tok in up for tok in ("ARTIK", "ART.", "DESCRIP", "DESCRP", "KOP", "CANT")):
        return None
    tokens = line.split()
    if not tokens:
        return None

    code = tokens[0]
    # OCR frecuente: "3P141002" por "JP141002"
    code = re.sub(r"^[0-9]P(?=\d{5,})", "JP", code)
    if not re.match(r"^JP[0-9A-Z]{3,}$", code):
        return None

    numeric_pos = [i for i, t in enumerate(tokens[1:], start=1) if re.match(r"^[0-9]+(?:[.,][0-9]+)?$", t)]
    if not numeric_pos:
        return None
    first_num = numeric_pos[0]

    qty = None
    if "PENDI" in up and len(numeric_pos) >= 2:
        asked = to_float(tokens[numeric_pos[0]])
        pending = to_float(tokens[numeric_pos[-1]])
        if asked is not None and pending is not None:
            qty = max(asked - pending, 0.0)
    if qty is None:
        qty = to_float(tokens[first_num])

    concept = " ".join(tokens[1:first_num]).strip()
    if qty is None or not concept:
        return None
    return qty, code, concept


def parse_page(page, page_num, proveedor_detectado="JUPER"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    lines = [re.sub(r"^\s*\d{1,3}:\s*", "", ln) for ln in lines]
    joined = " ".join(lines)

    albaran, fecha, supedido = _extract_header(lines, joined)
    items = []

    stop_markers = ("TOTAL ALBARAN", "DESGLOSE DE DESCUENTOS", "TOTAL BRUTO")
    start_idx = 0
    for i, ln in enumerate(lines):
        up = _ascii_upper(ln)
        if ("ART" in up and "DES" in up) and ("KOP" in up or "CANT" in up):
            start_idx = i + 1
            break

    for ln in lines[start_idx:]:
        up = _ascii_upper(ln)
        if any(marker in up for marker in stop_markers):
            break
        detail = _parse_row(ln)
        if not detail:
            continue
        qty, code, concept = detail
        items.append(
            {
                "Proveedor": proveedor_detectado,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": supedido,
                "Codigo": code,
                "Descripcion": concept,
                "CantidadServida": qty,
                "PrecioUnitario": None,
                "DescuentoPct": None,
                "Importe": None,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "NO_PRICE_LOG",
            }
        )

    meta = {
        "Proveedor": proveedor_detectado,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }

    try:
        from debugkit import dbg_parser_page

        dbg_parser_page(
            PARSER_ID,
            page_num,
            header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": supedido},
            items=items,
            meta=meta,
        )
    except Exception:
        pass

    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
