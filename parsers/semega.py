import re
import numpy as np
from common import normalize_spaces, to_float, parse_date_es

PARSER_ID = "semega"
PROVIDER_NAME = "SEMEGA"
BRAND_ALIASES = ["SEMEGA", "SEMEGA.NET", "SUMINISTROS SEMEGA"]

ALB_RE = re.compile(r"ALBAR[AÁ]N\s*(?P<value>\d+)", re.I)
REF_RE = re.compile(r"Referencia\s*:\s*(?P<value>[A-Z0-9./-]+)", re.I)
FECHA_RE = re.compile(r"Fecha\s*[: ]\s*(?P<value>\d{1,2}/\d{1,2}/\d{2,4})", re.I)


def _clean_num(tok: str) -> str:
    tok = tok or ""
    tok = re.sub(r"\([^)]*\)", "", tok)  # quita "(100)" etc
    tok = tok.replace(".", "")
    return re.sub(r"[^0-9,.-]", "", tok)


def _num_like(tok: str) -> bool:
    return bool(re.fullmatch(r"[0-9][0-9.,()-]*", tok or ""))


def _to_num(tok: str):
    tok = _clean_num(tok)
    if not tok:
        return None
    if "," in tok:
        return to_float(tok)
    try:
        return float(tok)
    except Exception:
        return to_float(tok)

def _normalize_supedido_ref(value: str | None) -> str:
    if not value:
        return ""
    token = normalize_spaces(str(value)).upper()
    token = re.sub(r"\s+", "", token)
    token = token.strip(" .,:;-/")

    # Ej: 25.018-E -> 25018
    m = re.fullmatch(r"(\d{2})\.(\d{3})-[A-Z]{1,3}", token)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    # Ej: A-130226-FJ -> A130226
    m = re.fullmatch(r"([AH])-(\d{6})-[A-Z]{1,3}", token)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return token


def _extract_header(text: str):
    alb = ""
    fecha = parse_date_es(text)
    supedido = ""
    m = ALB_RE.search(text)
    if m:
        alb = m.group("value")
    m = REF_RE.search(text)
    if m:
        supedido = _normalize_supedido_ref(m.group("value"))
    m = FECHA_RE.search(text)
    if m:
        fecha = parse_date_es(m.group("value"))
    return alb, fecha, supedido


def _extract_base_importe(text: str):
    m = re.search(r"Base\s+imponible.*?(\d{1,3}(?:\.\d{3})*,\d{2})", text, flags=re.I | re.S)
    if not m:
        return None
    return to_float(m.group(1))


def _parse_row(ln: str):
    ln = normalize_spaces(ln)
    ln = re.sub(r"(\d+,)\s+(\d{3}\(100\))", r"\1\2", ln)
    per_100_price = "(100)" in ln
    if not ln or "REF." in ln.upper():
        return None
    up = ln.upper()
    if "TEL" in up or "FAX" in up or "WWW" in up:
        return None
    tokens = ln.split()
    code = tokens[0]
    # buscar números a partir de la posición 1 (evita el código)
    num_positions = [i for i, t in enumerate(tokens[1:], start=1) if _num_like(t)]
    while len(num_positions) >= 2:
        first_tok = tokens[num_positions[0]]
        second_tok = tokens[num_positions[1]]
        first = _to_num(first_tok)
        if first is not None and first > 100 and "," not in first_tok and "," in second_tok:
            num_positions = num_positions[1:]
            continue
        break
    if len(num_positions) < 3:
        return None
    qty_idx = num_positions[0]
    if qty_idx <= 0:
        return None
    qty = _to_num(tokens[qty_idx])
    if qty is None or qty > 100000:
        return None
    imp_idx = num_positions[-1]
    price_idx = num_positions[-2] if len(num_positions) >= 2 else imp_idx
    dto_idx = num_positions[-2] if len(num_positions) >= 3 else None
    price = _to_num(tokens[price_idx])
    importe = _to_num(tokens[imp_idx])
    dto = _to_num(tokens[dto_idx]) if (dto_idx is not None and dto_idx not in (price_idx, imp_idx)) else None
    concept_tokens = tokens[1:qty_idx]
    concept = " ".join(concept_tokens).strip()
    if qty is None or price is None or not concept:
        return None
    expected = round(qty * price / (100 if per_100_price else 1), 2) if qty is not None and price is not None else None
    if expected is not None and importe is not None and 0 <= importe < expected * 0.1:
        importe = expected
    return qty, code, concept, price, dto, importe


def parse_page(page, page_num, proveedor_detectado="SEMEGA"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, fecha, supedido = _extract_header(joined)
    items = []
    suma = 0.0

    stop_markers = ("BASE IMPONIBLE", "OBSERVACIONES", "OPERACION ASEGURADA")

    start_idx = next(
        (i for i, ln in enumerate(lines) if ("REF" in ln.upper() and "PRECIO" in ln.upper())),
        0,
    )

    for ln in lines[start_idx + 1 :]:
        up = ln.upper()
        if any(m in up for m in stop_markers):
            break
        detail = _parse_row(ln)
        if not detail:
            continue
        qty, code, concept, price, dto, imp = detail
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
                "PrecioUnitario": price,
                "DescuentoPct": dto,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "",
            }
        )
        if imp is not None:
            suma += imp

    base_importe = _extract_base_importe(joined)
    if len(items) == 1 and base_importe is not None:
        current = items[0].get("Importe")
        if current is None or float(current or 0) == 0 or base_importe > float(current or 0) * 2:
            items[0]["Importe"] = base_importe
            suma = base_importe

    meta = {
        "Proveedor": proveedor_detectado,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": suma,
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
