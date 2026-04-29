import re
import numpy as np
from common import normalize_spaces, to_float, parse_date_es, fix_qty_price_import

PARSER_ID = "araiz"
PROVIDER_NAME = "ARAIZ"
BRAND_ALIASES = ["ARAIZ SUMINISTROS", "ARAIZ SUMINISTROS ELECTRICOS"]

# -- Regex helpers --
ALBARAN_RE = re.compile(r"ALBAR[ÁA]N\s*N[ºO]?\s*[:#-]?\s*(?P<value>\d+)", re.I)
SU_PEDIDO_RE = re.compile(
    r"\b(?:[AH]-?\d{6}(?:/[A-Z0-9]{1,4})?|\d{2}\.\d{3}/\d{2}(?:/[A-Z0-9]{1,4})?)\b",
    re.I,
)


def _clean_num(token: str) -> str:
    """Keep only digits and decimal separators."""
    return re.sub(r"[^0-9,.-]", "", token or "")


def _num_like(token: str) -> bool:
    return bool(token) and bool(re.match(r"^[0-9][0-9.,-]*", token))


def _to_number(token: str):
    cleaned = _clean_num(token)
    if not cleaned:
        return None
    if "," in cleaned:
        return to_float(cleaned)
    try:
        return float(cleaned)
    except Exception:
        return to_float(cleaned)


def _extract_header(text: str):
    albaran = ""
    supedido = ""
    m = ALBARAN_RE.search(text)
    if m:
        albaran = m.group("value").strip()
    m = SU_PEDIDO_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        if not re.search(r"TEL", candidate, re.I):
            supedido = candidate
    fecha = parse_date_es(text)
    return albaran, fecha, supedido


def _parse_detail_line(ln: str):
    """Parse a detail row. Returns (qty, code, concept, price, dto, importe) or None."""
    ln = normalize_spaces(ln)
    if not ln or ln.startswith("Cantidad "):
        return None
    tokens = ln.split()
    qty_idx = next((i for i, t in enumerate(tokens) if _num_like(t)), None)
    if qty_idx is None:
        return None
    qty = _to_number(tokens[qty_idx])
    code = tokens[qty_idx + 1] if qty_idx + 1 < len(tokens) else ""

    num_idxs = [i for i in range(qty_idx + 2, len(tokens)) if _num_like(tokens[i])]
    if not num_idxs:
        return None

    imp_idx = num_idxs[-1]
    price_idx = num_idxs[-2] if len(num_idxs) >= 2 else num_idxs[-1]
    dto_idx = num_idxs[-2] if len(num_idxs) >= 3 else None

    price = _to_number(tokens[price_idx])
    importe = _to_number(tokens[imp_idx])
    dto = _to_number(tokens[dto_idx]) if dto_idx is not None and dto_idx not in (price_idx, imp_idx) else None

    concept_tokens = tokens[qty_idx + 2 : num_idxs[0]]
    concept = " ".join(concept_tokens).strip()

    # Ignore obviously invalid rows
    if qty is None or price is None or not concept:
        return None

    return qty, code, concept, price, dto, importe


def parse_page(page, page_num, proveedor_detectado="ARAIZ"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, fecha, supedido = _extract_header(joined)

    items = []
    suma_importes = 0.0

    # Try to start after the header row if present
    start_idx = next(
        (i for i, ln in enumerate(lines) if "CANTIDAD" in ln.upper() and "PRECIO" in ln.upper()),
        0,
    )

    stop_markers = ("ENVIO DIRECTO", "ZONA", "MIEMB", "OBSERVACIONES", "STOCK - PLAZO")

    for ln in lines[start_idx + 1 :]:
        up = ln.upper()
        if any(marker in up for marker in stop_markers):
            break
        detail = _parse_detail_line(ln)
        if not detail:
            continue
        qty, code, concept, price, dto, importe = detail
        dto = dto if dto is not None else 0.0
        item = {
            "Proveedor": proveedor_detectado,
            "Parser": PARSER_ID,
            "AlbaranNumero": albaran,
            "FechaAlbaran": fecha,
            "SuPedidoCodigo": supedido,
            "Codigo": code,
            "Descripcion": concept,
            "CantidadServida": qty,
            "PrecioUnitario": price,
            "DescuentoPct": dto,
            "Importe": importe,
            "Pagina": page_num,
            "Pdf": "",
            "ParseWarn": "",
        }
        item = fix_qty_price_import(item)
        items.append(item)
        if importe is not None:
            suma_importes += importe

    meta = {
        "Proveedor": proveedor_detectado,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": suma_importes,
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
