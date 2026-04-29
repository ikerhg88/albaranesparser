from __future__ import annotations

import re
import unicodedata
from typing import Iterable

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

NUM_DEC_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d{2,4})|-?\d+(?:,\d{2,4})")


def fold_upper(value: object) -> str:
    text = normalize_spaces(str(value or ""))
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.upper())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def extract_first(text: str, patterns: Iterable[str]) -> str:
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if not m:
            continue
        if m.groups():
            for g in m.groups():
                if g:
                    return normalize_spaces(g).strip()
        return normalize_spaces(m.group(0)).strip()
    return ""


def extract_first_from_lines(lines: list[str], patterns: Iterable[str]) -> str:
    for line in lines:
        got = extract_first(line, patterns)
        if got:
            return got
    return ""


def extract_all_decimals(line: str) -> list[float]:
    values: list[float] = []
    for token in NUM_DEC_RE.findall(line or ""):
        val = to_float(token)
        if val is not None:
            values.append(val)
    return values


def extract_last_decimal(line: str) -> float | None:
    vals = extract_all_decimals(line)
    return vals[-1] if vals else None


def find_header_index(lines: list[str], markers: Iterable[str]) -> int:
    marker_up = [fold_upper(m) for m in markers]
    for idx, line in enumerate(lines):
        up = fold_upper(line)
        if all(m in up for m in marker_up):
            return idx
    return -1


def normalize_albaran(
    raw: str | None,
    *,
    compact: bool = True,
    n_prefix_to_a: bool = False,
) -> str:
    value = normalize_spaces(raw or "").upper()
    if not value:
        return ""
    value = re.sub(r"\b(FECHA|PORTES|DEBIDOS|PAGINA)\b.*$", "", value).strip()
    if compact:
        value = re.sub(r"[^A-Z0-9]", "", value)
    else:
        value = re.sub(r"\s+", "", value)
    if n_prefix_to_a and re.fullmatch(r"N\d{4,}", value):
        value = "A" + value[1:]
    return value


def normalize_supedido(raw: str | None) -> str:
    value = normalize_spaces(raw or "").upper()
    if not value:
        return ""
    value = value.replace("\\", "/")
    value = re.sub(r"[^A-Z0-9./-]", "", value)
    value = re.sub(r"/{2,}", "/", value).strip("/")
    return value


def extract_first_item_row(
    lines: list[str],
    *,
    header_markers: Iterable[str],
    stop_markers: Iterable[str] | None = None,
) -> tuple[str, str, float | None]:
    idx = find_header_index(lines, header_markers)
    if idx < 0:
        return "", "", None

    stop_words = [fold_upper(x) for x in (stop_markers or [])]
    for line in lines[idx + 1 :]:
        up = fold_upper(line)
        if stop_words and any(sw in up for sw in stop_words):
            break
        if "PEDIDO:" in up or "S/PED" in up:
            continue

        m = re.match(
            r"^\s*(?P<code>[A-Z0-9][A-Z0-9./-]{2,})\s+(?P<desc>.+?)\s+(?P<qty>-?\d+(?:[.,]\d+)?)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            code = normalize_spaces(m.group("code"))
            desc = normalize_spaces(m.group("desc"))
            qty = to_float(m.group("qty"))
            return code, desc, qty
    return "", "", None


def build_single_result(
    *,
    provider_name: str,
    parser_id: str,
    page_num: int,
    albaran: str,
    fecha: str,
    su_pedido: str,
    descripcion: str,
    codigo: str = "",
    cantidad: float | None = None,
    precio: float | None = None,
    dto: float | None = None,
    importe: float | None = None,
    parse_warn: str = "vendor_structured",
):
    item = {
        "Proveedor": provider_name,
        "Parser": parser_id,
        "AlbaranNumero": albaran or "",
        "FechaAlbaran": fecha or "",
        "SuPedidoCodigo": su_pedido or "",
        "Codigo": codigo or "",
        "Descripcion": descripcion or "",
        "CantidadPedida": None,
        "CantidadServida": cantidad,
        "CantidadPendiente": None,
        "UnidadesPor": None,
        "PrecioUnitario": precio if precio is not None else "",
        "DescuentoPct": dto,
        "Importe": importe if importe is not None else None,
        "Pagina": page_num,
        "Pdf": "",
        "ParseWarn": parse_warn,
    }
    meta = {
        "Proveedor": provider_name,
        "Parser": parser_id,
        "AlbaranNumero": albaran or "",
        "FechaAlbaran": fecha or "",
        "SuPedidoCodigo": su_pedido or "",
        "SumaImportesLineas": float(importe) if importe is not None else 0.0,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan if importe is None else float(importe),
    }

    try:
        from debugkit import dbg_parser_page

        dbg_parser_page(
            parser_id,
            page_num,
            header={
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
            },
            items=[item],
            meta=meta,
        )
    except Exception:
        pass

    return [item], meta


def default_fecha(lines: list[str], joined: str) -> str:
    return parse_date_es(joined) or parse_date_es(" ".join(lines[:8])) or ""

