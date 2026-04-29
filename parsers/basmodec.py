import re
import numpy as np
from common import normalize_spaces, to_float, parse_date_es

PARSER_ID = "basmodec"
PROVIDER_NAME = "BASMODEC"
BRAND_ALIASES = ["BASMODEC", "B A S M O D E C", "BASMODEC.COM"]

ALB_RE = re.compile(r"\b(\d{2,4}\s*/\s*\d{2}\s*/\s*\d{5,})\b")


def _num(tok: str | None):
    if tok is None:
        return None
    tok = tok.replace("Â·", "").replace("·", "")
    tok = tok.replace(".", "").replace(",", ".")
    try:
        return float(tok)
    except Exception:
        return to_float(tok)


def _extract_header(text: str):
    albaran = ""
    m = ALB_RE.search(text)
    if m:
        albaran = m.group(1).replace(" ", "")
    fecha = parse_date_es(text)
    return albaran, fecha


def _parse_row(ln: str):
    ln = normalize_spaces(ln)
    if not ln or "ARTICULO" in ln.upper():
        return None
    tokens = ln.split()
    if len(tokens) < 5:
        return None
    numeric_idx = [i for i, t in enumerate(tokens) if re.fullmatch(r"[0-9][0-9.,]*", t)]
    if len(numeric_idx) < 3:
        return None
    qty = _num(tokens[numeric_idx[0]])
    price = _num(tokens[numeric_idx[1]]) if len(numeric_idx) > 1 else None
    disc = None
    if len(numeric_idx) >= 3 and numeric_idx[-2] != numeric_idx[-1]:
        maybe_disc = _num(tokens[numeric_idx[-2]])
        if maybe_disc is not None and maybe_disc <= 100:
            disc = maybe_disc
    imp = _num(tokens[numeric_idx[-1]])

    code = tokens[0] if re.search(r"[A-Z]", tokens[0], re.I) else ""
    desc_tokens = tokens[1:numeric_idx[0]]
    desc = " ".join(desc_tokens).strip()

    if qty is None or imp is None or not desc:
        return None
    return qty, code or None, desc, price, disc, imp


def parse_page(page, page_num, proveedor_detectado=PROVIDER_NAME):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha = _extract_header(joined)

    items = []
    suma = 0.0

    # localizar inicio de tabla
    start_idx = 0
    for i, ln in enumerate(lines):
        u = ln.upper()
        if "ARTICULO" in u and "DESCRIPCION" in u:
            start_idx = i + 1
            break

    for ln in lines[start_idx:]:
        up = ln.upper()
        if "IMPORTE NETO" in up or "TOTAL ALBARAN" in up:
            break
        parsed = _parse_row(ln)
        if not parsed:
            continue
        qty, code, desc, price, disc, imp = parsed
        items.append(
            {
                "Proveedor": proveedor_detectado,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": "",
                "Codigo": code,
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": price,
                "DescuentoPct": disc,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "",
            }
        )
        if imp is not None:
            suma += imp

    meta = {
        "Proveedor": proveedor_detectado,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": "",
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan,
        "TotalAlbaranPie": np.nan,
    }

    try:
        from debugkit import dbg_parser_page

        dbg_parser_page(
            PARSER_ID,
            page_num,
            header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": ""},
            items=items,
            meta=meta,
        )
    except Exception:
        pass

    return items, meta


__all__ = ["parse_page", "PROVIDER_NAME", "PARSER_ID", "BRAND_ALIASES"]
