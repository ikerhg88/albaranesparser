
import re
import unicodedata
from pathlib import Path
import numpy as np
from common import normalize_spaces, to_float, fix_qty_price_import, calc_importe, normalize_supedido_code

PARSER_ID = "elektra"
PROVIDER_NAME = "ELEKTRA"

ALBARAN_EXCLUIDOS_5D = {"54162"}
_ALB_SUFFIX_RE = re.compile(r"/\s*\d{3}\s*/\s*\d{2}")

# Ej.: "1,00", "1.234,56", "327,00/C", "3.015,00/M"
NUM_TOKEN_RE = re.compile(
    r"(?P<num>[0-9]{1,3}(?:\.[0-9]{3})*,\s*[0-9]{2})(?:\s*/\s*(?P<unit>[A-Z]?))?"
)
UNIT_FACTORS = {"D": 10, "C": 100, "M": 1000}


def _collapse_number_spaces(s: str) -> str:
    """Compacta espacios internos de tokens numericos sin unir columnas."""
    # Solo si a la izquierda hay 'digito + , o .' y a la derecha hay digito o '/'
    s = re.sub(r"(?<=\d[.,])\s+(?=\d|/)", "", s)
    # Espacios tras coma o punto
    s = re.sub(r"(?<=,)\s+(?=\d)", "", s)
    s = re.sub(r"(?<=\.)\s+(?=\d)", "", s)
    # Segundo digito decimal separado (p.ej. '70, 0 0' -> '70,00')
    s = re.sub(r"(?<=,\d)\s+(?=\d)", "", s)
    # Mantener los negativos pegados al numero
    s = re.sub(r"(?P<num>\d{1,3}(?:\.\d{3})*,\d{2})\s*-(?!\d)", r"-\g<num>", s)
    return s


_DEBUG_PREFIX_RE = re.compile(r"^\s*\d{1,3}:\s*")


def _strip_debug_counter(text: str) -> str:
    """
    Elimina los prefijos 'NNN:' que añadimos en los volcados debug/pXX_lines.txt.
    El texto extraído por pdfplumber no los incluye, pero esta limpieza permite
    que las funciones sigan funcionando cuando analizamos esos ficheros en pruebas.
    """
    return _DEBUG_PREFIX_RE.sub("", text or "")

def _ascii_upper(value: str | None) -> str:
    """Devuelve el texto en mayúsculas sin tildes ni diacríticos."""
    if value is None:
        return ""
    try:
        normalized = unicodedata.normalize("NFKD", value)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).upper()
    except Exception:
        return (value or "").upper()



def _to_float_signed(token: str) -> float | None:
    if token is None:
        return None
    token = _collapse_number_spaces(token)
    token = token.strip()
    neg = token.startswith("-")
    base = token.lstrip("-").strip()
    base = re.sub(r"/[A-Z]$", "", base, flags=re.I).strip()
    val = to_float(base)
    if val is None:
        return None
    return -val if neg else val

def _unit_factor(token: str | None) -> int | None:
    if not token:
        return None
    m = re.search(r"/\s*([DCM])\b", token, flags=re.I)
    if not m:
        return None
    return UNIT_FACTORS.get(m.group(1).upper())

def _extract_unidades_por(tokens: list[str]) -> int | None:
    for tok in tokens:
        fac = _unit_factor(tok)
        if fac:
            return fac
    return None

def _norm_date(token: str) -> str | None:
    if not token:
        return None
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", token)
    if not m:
        return None
    d, mth, y = m.group(1), m.group(2), m.group(3)
    d = d.zfill(2); mth = mth.zfill(2)
    if len(y) == 2: y = "20" + y
    return f"{d}/{mth}/{y}"


def _find_albaran_y_fecha(lines: list[str]) -> tuple[str, str]:
    flat = " ".join([normalize_spaces(ln) for ln in lines if ln.strip()])
    mdate = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b", flat)
    fecha = _norm_date(mdate.group(1)) if mdate else ""

    albaran_num = ""
    m_slash = re.search(r"\b(\d{4,6}(?:\s*/\s*\d{1,4}){1,2})\b", flat)
    if m_slash:
        raw = m_slash.group(1)
        albaran_num = re.sub(r"\s*/\s*", "/", raw.strip())
        albaran_num = re.sub(r"\s+", "", albaran_num)
    else:
        cands = []
        for m in re.finditer(r"(?<!\d)(\d{5})(?!\d)", flat):
            num = m.group(1)
            start, end = m.span()
            window = flat[end:end + 150]
            window_clean = re.sub(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", " ", window)
            has_suffix = bool(_ALB_SUFFIX_RE.search(window_clean))
            next_char = window[0] if window else ""
            near_ok = (next_char == "/" or (next_char and (next_char.isspace() or next_char.isalpha())))
            cands.append({"num": num, "pos": start, "suffix": has_suffix, "near_ok": near_ok})
        if cands:
            pool = [c for c in cands if c["suffix"]]
            if not pool:
                pool = [c for c in cands if c["near_ok"]] or cands
            pool_nb = [c for c in pool if c["num"] not in ALBARAN_EXCLUIDOS_5D]
            chosen = min(pool_nb or pool, key=lambda c: c["pos"])
            albaran_num = chosen["num"]

    return albaran_num, (fecha or "")


def _read_header_values(lines: list[str]) -> tuple[str, str, str, str]:
    i_hdr = -1
    for i, ln in enumerate(lines):
        base = _strip_debug_counter(ln)
        u = base.upper()
        if "COD. CLIENTE" in u and "S/PEDIDO" in u:
            i_hdr = i
            break
    if i_hdr == -1:
        return "", "", "", ""

    vals, j = [], i_hdr + 1
    while j < len(lines) and len(vals) < 10:
        row = _strip_debug_counter(lines[j]).strip()
        if not row:
            j += 1; continue
        if re.search(r"(C\.I\.F|DIRECCI[ÓO]N|ART[IÍ]CULO|POL\. IND|APOSTOLADO|TEL[:\s]|FAX[:\s])", row, re.I):
            break
        cols = [c.strip() for c in re.split(r"\s{2,}", row) if c.strip()]
        vals.extend(cols if cols else [row])
        j += 1

    codcli = nref = sped = sref = ""
    for tok in vals:
        if not codcli and re.fullmatch(r"\d{3,}", tok):
            codcli = tok; continue
        if not nref and (re.fullmatch(r"\d{4,}", tok) or re.fullmatch(r"P\s*-\s*\d{3,}", tok, re.I)):
            nref = tok.replace(" ", ""); continue
        if (not sped and (re.search(r"\d|[./]", tok) or (len(tok) > 5 and not tok.isupper()))):
            sped = tok; continue
        if not sref: sref = tok
    return codcli, nref, sped, sref

def _extract_supedido_block(lines: list[str], codcli: str | None) -> str:
    i_hdr = None
    for i, ln in enumerate(lines):
        base = _strip_debug_counter(ln)
        u = base.upper()
        if "COD. CLIENTE" in u and "S/PEDIDO" in u:
            i_hdr = i; break
    if i_hdr is None: return ""

    i_stop = None
    stop_re = re.compile(
        r"(ART[IÍ]CULO.*CONCEPTO.*CANTIDAD.*IMPORTE|C\.I\.F|DIRECCI[ÓO]N|POL\. IND|APOSTOLADO|TEL[:\s]|FAX[:\s])",
        re.I,
    )
    for j in range(i_hdr + 1, min(i_hdr + 40, len(lines))):
        if stop_re.search(_strip_debug_counter(lines[j])):
            i_stop = j; break
    if i_stop is None: i_stop = min(i_hdr + 40, len(lines))

    raw = []
    for ln in lines[i_hdr + 1 : i_stop + 1]:
        s = normalize_spaces(_strip_debug_counter(ln))
        if not s:
            continue
        if re.search(r"\bFax\b", s, flags=re.I):
            parsed = _parse_supedido_line(s, codcli)
            if parsed:
                return parsed
            s = re.sub(r"\bFax\s*:?.*$", "", s, flags=re.I).strip()
        raw.append(s)

    if not raw:
        return ""
    joined = normalize_spaces(" ".join(raw))
    if codcli:
        c = codcli.replace(".", "")
        joined = re.sub(rf"(?<!\d){re.escape(c)}(?!\d)", " ", joined)
    return normalize_spaces(joined).strip()


def _parse_supedido_line(line: str, codcli: str | None) -> str:
    s = normalize_spaces(_strip_debug_counter(line))
    s = re.split(r"\bFax\b", s, maxsplit=1, flags=re.I)[0].strip()
    if codcli:
        s = re.sub(rf"(?<!\d){re.escape(codcli)}(?!\d)", " ", s)
    s = normalize_spaces(s)
    tokens = s.split()
    if not tokens:
        return ""
    # Quitar N/Referencia numérica (primer token tras codcli) si procede
    while tokens and re.fullmatch(r"\d{3,}", tokens[0]):
        # Evitar eliminar el propio S/Pedido si no queda nada más
        if len(tokens) == 1:
            break
        tokens.pop(0)
    if not tokens:
        return ""
    result = " ".join(tokens).strip()
    # Normalizar espacios alrededor de separadores
    result = re.sub(r"\.\s+", ".", result)
    result = re.sub(r"\s+/", "/", result)
    result = re.sub(r"/\s+", "/", result)
    return result.strip()

_PAT_DOC  = re.compile(r"\b\d{2,3}\.\d{3}/\d{2}/[A-Z0-9]\b")
_PAT_PNUM = re.compile(r"\bP-?\d{3,}\b", re.I)
_PAT_NUM5 = re.compile(r"\b\d{5,}\b")
_PAT_NUM4 = re.compile(r"\b\d{4,}\b")
_NOISE = {"WEB", "FAX", "CANON", "RAEE", "R.A.E.E."}

def _shrink_supedido(raw: str, codcli: str | None) -> str:
    if not raw:
        return ""
    s = normalize_spaces(raw)
    s = s.strip("[]() ")
    s = s.replace("P -", "P-")
    s = re.sub(r"\s*([./-])\s*", r"\1", s)
    tokens = [t for t in s.split() if t.upper() not in _NOISE]
    s = " ".join(tokens)

    # Patrones directos con puntos y barras
    m = _PAT_DOC.search(s)
    if m:
        val = m.group(0)
        if re.fullmatch(r"\d{3}\.\d{3}/\d{2}/[A-Z]", val) and val.startswith("1"):
            return val[1:]
        return val

    m = re.search(r"\b\d{5,}[A-Z]?(?:-[A-Z])\b", s)
    if m:
        return m.group(0)

    codcli_clean = (codcli or "").replace(".", "")
    for m in _PAT_NUM5.finditer(s):
        cand = m.group(0)
        if cand != codcli_clean:
            return cand

    m = _PAT_PNUM.search(s)
    if m:
        return m.group(0).upper().replace(" ", "")

    for m in _PAT_NUM4.finditer(s):
        cand = m.group(0)
        if cand != codcli_clean:
            return cand

    words = s.split()
    return " ".join(words) if words else ""

def _grab_numbers_from_context(lines: list[str], i_start: int, max_tokens=4):
    tokens, j = [], i_start
    while j < len(lines) and len(tokens) < max_tokens:
        line = _collapse_number_spaces(lines[j])
        if j > i_start and re.match(r"^\s*\d{3,}\*?\s+\S", lines[j]):
            break
        if re.search(r"(BASE IMPONIBLE|TOTAL|SUMA PORTES|SUMA MATERIALES|SUMA CANON)", line.upper()):
            break
        line_wo_neto = re.sub(r"\bNETO\b", " ", line, flags=re.I)
        for m in NUM_TOKEN_RE.finditer(line_wo_neto):
            tokens.append(m.group(0))
            if len(tokens) >= max_tokens:
                return tokens, j + 1
        j += 1
    return tokens, j

def _pick_raee_description(raw_line: str) -> str:
    """
    Devuelve 'Canon RAEE' o 'Canon RAEE X' si termina en entero (p.ej. 'Canon RAEE 5').
    """
    u = normalize_spaces(raw_line)
    m = re.search(r"CANON\s+R\.?A\.?E\.?E\.?(?:\s+(\d+))?", u, flags=re.I)
    if m:
        suf = m.group(1)
        return "Canon RAEE" + (f" {suf}" if suf else "")
    return "Canon RAEE"

def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = []
    for ln in text.splitlines():
        ln = normalize_spaces(_strip_debug_counter(ln))
        if not ln:
            continue
        lines.append(ln)

    albaran, fecha = _find_albaran_y_fecha(lines)
    codcli, nref, sped, sref = _read_header_values(lines)

    su_pedido_raw = _extract_supedido_block(lines, codcli) or (nref or sped or sref or "")
    su_pedido = normalize_supedido_code(_shrink_supedido(su_pedido_raw, codcli))

    # Fallback robusto: si no encontramos S/Pedido en el bloque,
    # buscamos el patrón 'NNN.NNN/NN/L' en toda la página (ej. '125.510/01/H').
    if not su_pedido:
        flat = " ".join(lines)
        m_all = _PAT_DOC.search(flat)
        if m_all:
            su_pedido = m_all.group(0)

    # Cabecera
    header_idx = None
    for idx, ln in enumerate(lines):
        u = _ascii_upper(ln)
        if ("ARTICULO" in u) and "CONCEPTO" in u and "CANTIDAD" in u and "IMPORTE" in u:
            header_idx = idx
            break

    items, suma_pag = [], 0.0

    if header_idx is not None:
        i = header_idx + 1
        while i < len(lines):
            ln = lines[i]
            u = _ascii_upper(ln)
            if re.search(r"(BASE IMPONIBLE|TOTAL|SUMA PORTES|SUMA MATERIALES|SUMA CANON)", u):
                break

            # Canon RAEE (con posible sufijo entero en la misma línea)
            if "ARTICULO SUJETO A CANON R.A.E.E" in u or ("CANON" in u and "R.A.E.E" in u):
                desc_raee = _pick_raee_description(ln)
                toks, j = _grab_numbers_from_context(lines, i, max_tokens=3)
                unidades_por = _extract_unidades_por(toks)
                qty   = _to_float_signed(toks[0]) if len(toks) >= 1 else 1.0
                price = _to_float_signed(toks[1]) if len(toks) >= 2 else 0.04
                if unidades_por and price is not None:
                    price = price * unidades_por
                imp   = _to_float_signed(toks[-1]) if toks else price
                suma_pag += (imp or 0.0)
                item = {
                    "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
                    "AlbaranNumero": albaran or "", "FechaAlbaran": fecha or "",
                    "SuPedidoCodigo": su_pedido or "",
                    "Codigo": "",
                    "Descripcion": desc_raee,
                    "CantidadPedida": None, "CantidadServida": qty, "CantidadPendiente": None,
                    "UnidadesPor": unidades_por, "PrecioUnitario": f"{price:.2f}" if isinstance(price, float) else (price or ""),
                    "DescuentoPct": None, "Importe": imp,
                    "Pagina": page_num, "Pdf": "", "ParseWarn": ""
                }
                items.append(fix_qty_price_import(item))
                i = j
                continue

            # Línea de artículo normal
            if re.match(r"^\s*\d{3,}\*?\s+\S", ln):
                cut_ln = _collapse_number_spaces(ln)
                first_num = NUM_TOKEN_RE.search(re.sub(r"\bNETO\b", " ", cut_ln, flags=re.I))
                desc = cut_ln[:first_num.start()].strip() if first_num else re.sub(r"^\s*\d{3,}\*?\s+", "", ln).strip()

                # Intenta separar código de artículo (primer token alfanumérico)
                code = ""
                m_code = re.match(r"^([A-Z0-9./-]{4,})", desc, flags=re.I)
                if m_code:
                    # Evita confundir importes formateados como código
                    if not NUM_TOKEN_RE.match(m_code.group(1)):
                        code = m_code.group(1).strip(" .-")
                        desc = desc[len(m_code.group(0)) :].strip(" :-")

                toks, j = _grab_numbers_from_context(lines, i, max_tokens=4)
                unidades_por = _extract_unidades_por(toks)
                qty = _to_float_signed(toks[0]) if len(toks) >= 1 else None
                price_token = _collapse_number_spaces(toks[1]) if len(toks) >= 2 else ""
                price_val = _to_float_signed(price_token) if price_token else None

                disc = None
                imp = None
                if len(toks) == 3:
                    # Sin columna de descuento; el tercer token es el importe
                    imp = _to_float_signed(toks[2])
                elif len(toks) >= 4:
                    v3 = _to_float_signed(toks[2])
                    v4 = _to_float_signed(toks[3])
                    if v3 is not None and v4 is not None and v3 <= 100.0:
                        disc = v3
                        imp = v4
                    else:
                        # Tramos ruidosos: prioriza el cuarto token como importe
                        imp = v4 if v4 is not None else v3

                suma_pag += (imp or 0.0)
                if disc is None:
                    disc = 0.0
                item = {
                    "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
                    "AlbaranNumero": albaran or "", "FechaAlbaran": fecha or "",
                    "SuPedidoCodigo": su_pedido or "",
                    "Codigo": code or "",
                    "Descripcion": desc if desc else code,
                    "CantidadPedida": None, "CantidadServida": qty, "CantidadPendiente": None,
                    "UnidadesPor": unidades_por, "PrecioUnitario": price_val if price_val is not None else (price_token or None),
                    "DescuentoPct": disc, "Importe": imp,
                    "Pagina": page_num, "Pdf": "", "ParseWarn": ""
                }
                items.append(fix_qty_price_import(item))
                i = j
                continue

            i += 1

    # Totales pie
    base_imp = total = None
    for ln in lines[-25:]:
        u = ln.upper()
        if "BASE IMPONIBLE" in u:
            m = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,\s*[0-9]{2})", _collapse_number_spaces(ln))
            if m:
                base_imp = _to_float_signed(m.group(1))
        if re.fullmatch(r"TOTAL", u) or " TOTAL" in u:
            m = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,\s*[0-9]{2})", _collapse_number_spaces(ln))
            if m:
                total = _to_float_signed(m.group(1))

    meta = {
        "Proveedor": PROVIDER_NAME, "Parser": PARSER_ID,
        "AlbaranNumero": albaran or "", "FechaAlbaran": fecha or "",
        "SuPedidoCodigo": su_pedido or "",
        "SumaImportesLineas": suma_pag,
        "NetoComercialPie": np.nan if base_imp is None else base_imp,
        "TotalAlbaranPie": np.nan if total is None else total,
    }

    try:
        from debugkit import dbg_parser_page
        dbg_parser_page(PARSER_ID, page_num,
                        header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
                        items=items, meta=meta)
    except Exception:
        pass

    return items, meta
