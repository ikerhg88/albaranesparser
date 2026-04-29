import re
import numpy as np
from common import normalize_spaces, to_float, parse_date_es

PARSER_ID = "elicetxe"
PROVIDER_NAME = "ELICETXE"
BRAND_ALIASES = ["ELICETXE", "GRUPO UNASE", "UNASE"]

ALB_CONTEXT_RE = re.compile(
    r"\b(?P<alb>\d{6,10})\s+(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s+\d{2,6}\s+(?P<sup>[A-Z0-9./-]{4,})",
    re.I,
)
ALB_LABEL_RE = re.compile(r"ALBAR[ÁA]N|EMATE\s+AGIRIA", re.I)
SUPEDIDO_RE = re.compile(r"\b(?:[AH]-?\d{6}/[A-Z0-9]{1,4}|\d{2}\.\d{3}/\d{2,4})\b", re.I)
DEC_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2,4}$")


def _digits(token: str) -> str:
    return re.sub(r"\D", "", token or "")


def _extract_header(lines: list[str], text: str):
    albaran = ""
    fecha = parse_date_es(text)
    supedido = ""

    m = ALB_CONTEXT_RE.search(text)
    if m:
        albaran = m.group("alb")
        if not fecha:
            fecha = parse_date_es(m.group("fecha"))
        supedido = m.group("sup")
        return albaran, fecha, supedido

    for idx, ln in enumerate(lines):
        if not ALB_LABEL_RE.search(ln):
            continue
        scope = " ".join(lines[idx : min(idx + 6, len(lines))])
        nums = re.findall(r"\b\d{6,10}\b", scope)
        if nums:
            albaran = nums[0]
            break
    if not albaran:
        nums = re.findall(r"\b\d{6,10}\b", text)
        if nums:
            albaran = nums[0]

    m2 = SUPEDIDO_RE.search(text)
    if m2:
        supedido = m2.group(0)
    return albaran, fecha, supedido


def _num(tok: str):
    tok = (tok or "").replace(".", "").replace("â‚¬", "")
    return to_float(tok)


def _is_row_start_without_tail(ln: str) -> bool:
    tokens = normalize_spaces(ln).split()
    if len(tokens) < 2:
        return False
    has_ref = any(len(_digits(tok)) >= 8 for tok in tokens)
    has_dec = any(DEC_RE.match(tok) for tok in tokens)
    return has_ref and not has_dec


def _parse_row(ln: str):
    ln = normalize_spaces(ln)
    if not ln:
        return None
    up = ln.upper()
    if any(tok in up for tok in ("MARCA", "REFERENCIA", "KONTZEPTUA", "VALIDACION", "TASAR")):
        return None

    tokens = ln.split()
    if len(tokens) < 4:
        return None

    price_idx = None
    for i in range(len(tokens) - 1, -1, -1):
        if DEC_RE.match(tokens[i]):
            price_idx = i
            break
    if price_idx is None:
        return None

    qty_idx = None
    dec_before_price = [i for i in range(0, price_idx) if DEC_RE.match(tokens[i])]
    if dec_before_price:
        qty_idx = dec_before_price[-1]
    else:
        for i in range(price_idx - 1, -1, -1):
            tok = tokens[i]
            if re.fullmatch(r"\d{1,4}", tok):
                qty_idx = i
                break
    if qty_idx is None:
        return None

    ref_idx = None
    ref_len = 0
    for i in range(0, qty_idx):
        d = _digits(tokens[i])
        if len(d) >= 8 and len(d) >= ref_len:
            ref_idx = i
            ref_len = len(d)
    if ref_idx is None:
        return None

    code = _digits(tokens[ref_idx])
    if not code:
        return None

    qty = _num(tokens[qty_idx])
    price = _num(tokens[price_idx])
    if qty is None:
        return None

    ue_idx = qty_idx + 1 if (qty_idx + 1 < price_idx and re.fullmatch(r"\d{1,3}", tokens[qty_idx + 1])) else None

    concept_tokens = []
    for i in range(ref_idx + 1, price_idx):
        if i == qty_idx or i == ue_idx:
            continue
        concept_tokens.append(tokens[i])
    concept = " ".join(concept_tokens).strip()

    imp = None
    for i in range(price_idx + 1, len(tokens)):
        if DEC_RE.match(tokens[i]):
            imp = _num(tokens[i])
            break
    if imp == 0 and price == 0:
        imp = None
    elif imp is None and price != 0:
        imp = price

    return qty, code, concept, price, imp


def parse_page(page, page_num, proveedor_detectado="ELICETXE"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, supedido = _extract_header(lines, joined)
    is_packing_list = "PACKING LIST" in joined.upper() and ("MIGUELEZ" in joined.upper() or "MIGUÉLEZ" in joined.upper())
    items = []
    suma = 0.0

    stop_markers = ("TASAR", "VALIDACION", "VALIDACIÃ“N")
    start_idx = next((i for i, ln in enumerate(lines) if "MARCA" in ln.upper() and "REFER" in ln.upper()), 0)

    i = start_idx + 1
    while i < len(lines):
        ln = lines[i]
        up = ln.upper()
        if any(m in up for m in stop_markers):
            break

        detail = _parse_row(ln)
        if detail is None and i + 1 < len(lines) and _is_row_start_without_tail(ln):
            detail = _parse_row(f"{ln} {lines[i + 1]}")
            if detail is not None:
                i += 1
        if not detail:
            i += 1
            continue

        qty, code, concept, price, imp = detail
        if is_packing_list:
            concept_u = concept.upper()
            if code == "10010071" and "Z'6:" in concept_u and "&L/" in concept_u:
                i += 1
                continue
            imp = None
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
                "DescuentoPct": None,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "" if imp is not None else "NO_IMPORTE_IN_LINE",
            }
        )
        if imp is not None:
            suma += imp
        i += 1

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
