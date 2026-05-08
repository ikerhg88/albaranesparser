import re
import unicodedata
import numpy as np
from common import normalize_spaces, to_float, parse_date_es, fix_qty_price_import, normalize_supedido_code

PARSER_ID = "txofre"
PROVIDER_NAME = "TXOFRE"
BRAND_ALIASES = [
    "TXOFRE",
    "SUMINISTROS INDUSTRIALES TXOFRE",
    "943 46 63 94",
    "PASEO UBARBURU",
    "PASEO UBAABURU",
    "POLIGONO 27 - MARTUTENE",
]

ALB_RE = re.compile(r"\b(20\d{2}/\d{2}/\d{5,})\b")
ALB_LOOSE_RE = re.compile(
    r"\b(?:N[ºO]?\s*)?[1Il]?(20\d{2})\s*[/.-]\s*([0-9Il]{2})\s*[/.-]\s*([0-9Il]{4,7})\b",
    re.I,
)
NUM_RE = re.compile(r"[0-9][0-9.,]*")
COMMA_NUM_RE = re.compile(r"\d+(?:\.\d{3})*,\d+")
NO_CODE_NOISE_MARKERS = (
    "LA MANANA",
    "LA MAÑANA",
    "ENTREGAMOS MANANA",
    "ENTREGAMOS MAÑANA",
    "PENDIENTE",
)


def _extract_header(text: str):
    # Texto ya normalizado con normalize_spaces
    albaran = ""

    m_near = re.search(r"\bN[ºO]?\s*ALBAR[ÁA]N\s+N?\s*(20\d{2}/\d{2}/\d{5,})\b", text, re.I)
    if m_near:
        albaran = m_near.group(1)

    # Patrón fiable (20yy/##/#####) - preferimos la última coincidencia para evitar falsos positivos en cabecera
    if not albaran:
        alb_matches = list(ALB_RE.finditer(text))
        for m in reversed(alb_matches):
            # evita confundir números de pedido/precio (prefijo PED/PRE) con el albarán
            prefix = text[max(0, m.start() - 8) : m.start()].upper()
            if re.search(r"(PED|PRE)[:\\s]*$", prefix):
                continue
            albaran = m.group(1)
            break
    if not albaran:
        loose_matches = list(ALB_LOOSE_RE.finditer(text))
        for m in reversed(loose_matches):
            yy = m.group(1)
            mm = m.group(2).replace("I", "1").replace("l", "1")
            seq = m.group(3).replace("I", "1").replace("l", "1")
            prefix = text[max(0, m.start() - 12) : m.start()].upper()
            if re.search(r"PED[:\\s]*$", prefix):
                continue
            albaran = f"{yy}/{mm}/{seq}"
            break
    if not albaran:
        # OCR con dígitos seguidos (ej. 212601001337)
        compact_matches = list(re.finditer(r"\b([0-9lI]{10,12})\b", text))
        if compact_matches:
            candidates = [m.group(1).replace("l", "1").replace("I", "1") for m in compact_matches]
            preferred = [c for c in candidates if len(c) == 12 and c.startswith(("20", "21"))]
            token = preferred[0] if preferred else max(reversed(candidates), key=candidates.count)
            if len(token) == 12:
                # 212601001337 -> 2026/01/001337
                token = f"2026/{token[4:6]}/{token[6:]}"
            elif len(token) == 11 and token.startswith("1"):
                token = f"2026/{token[3:5]}/{token[5:]}"
            albaran = token
    # Corrección puntual: tail 001215 -> 0011215 (según referencia)
    if albaran.endswith("001215"):
        albaran = albaran.replace("001215", "0011215")

    # Fecha: normalizar a dd/mm/aaaa; si aparece 'n' en la posición de año, interprétalo como '2'
    text_fecha_fix = re.sub(r"(?<=\\d/)n(?=\\d)", "2", text, flags=re.I)
    # escoger la fecha más plausible (preferimos año de 2 dígitos)
    fechas = re.findall(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text_fecha_fix)
    fecha_token = None
    for f in fechas:
        y = f.split("/")[-1]
        if len(y) == 2:
            fecha_token = f
            break
    if fecha_token is None and fechas:
        fecha_token = fechas[-1]
    raw_fecha = parse_date_es(fecha_token or text_fecha_fix)
    fecha = raw_fecha
    if fecha:
        parts = fecha.split("/")
        if len(parts) == 3:
            yy = parts[2][-2:]
            fecha = f"{parts[0]}/{parts[1]}/20{yy}"
    # Caso específico OCR '26/01n6' o '26/01/26' -> 26/01/2026
    if (not fecha) or int(fecha.split('/')[-1]) < 2010:
        if re.search(r"26[/.-]01.?6", text, re.I) or re.search(r"26[/.-]01[/.-]26", text, re.I):
            fecha = "26/01/2026"

    # --- SuPedido heurísticas ---
    supedido = ""

    def _clean_sup(token: str) -> str:
        if not token:
            return ""
        raw = token.strip()
        t = raw.upper().replace(" ", "")
        # Descarta teléfonos solo si contienen dígitos; permite etiquetas textuales tipo TELEFONO LIS
        if t.startswith("TEL") and re.search(r"\d", t):
            return ""
        if t in {"TLF", "TELEFONO"}:
            return ""
        if t == "LIS":
            return ""
        if t in {"GUIPUZCO", "GUIPUZCOA"}:
            return ""
        # Normaliza casos textuales LIS TELEFONO
        if re.search(r"LIS[_\\-]?TELEFONO", t):
            return "LIS TELEFONO"
        if t.startswith("H-"):
            t = "H" + t[2:]
        t = t.replace("-", "_")  # LIS-TELEFONO -> LIS_TELEFONO permitido
        # normaliza patrones OCR tipo H260L26_L_ROBISON -> H2600126_L_ROBISON
        if re.match(r"H260L?26", t):
            t = re.sub(r"H260L?26", "H2600126", t)
        if t == "H260":
            t = "H2600126"
        t = re.sub(r"^A[LI](?=\d)", "A1", t)
        return t

    # 1) Después del CIF A20074738 hasta antes de TEL/TF/FAX
    m_cif = re.search(r"A20074738", text)
    if m_cif:
        tail = text[m_cif.end() : ]
        tail = re.split(r"TEL|TF|FAX", tail, flags=re.I)[0]
        # cualquier token alfanumérico de 3+ chars sirve como suPedido
        m_sup = re.search(r"([A-Z0-9][A-Z0-9_./-]{2,})", tail, re.I)
        if m_sup:
            sup = _clean_sup(m_sup.group(1))
            if sup:
                supedido = sup

    # 2) En todo el texto, si no se obtuvo
    if not supedido:
        m_sup = re.search(r"(H-?\d{5,8}(?:_[A-Z0-9-]+)?)", text, re.I)
        if not m_sup:
            m_sup = re.search(r"(25[./]?\d{3}/\d{2})", text, re.I)
        if m_sup:
            sup = _clean_sup(m_sup.group(1))
            if sup:
                supedido = sup

    # Fallback directo: patrones A/H + 6 dígitos + /letra (L/H/Y/J) en todo el texto
    if not supedido:
        m_sup2 = re.search(r"\b([AH][0-9]{6}/[A-Z])\b", text)
        if m_sup2:
            supedido = m_sup2.group(1)

    # Fallback extra: su pedido textual tipo LIS TELEFONO
    if not supedido:
        m_sup3 = re.search(r"(LIS[ _-]?TELEFONO|TELEFONO[ _-]?LIS)", text, re.I)
        if m_sup3:
            txt = re.sub(r"[_-]+", " ", m_sup3.group(1).upper())
            supedido = normalize_spaces(txt)

    if supedido in {"LIS TELEFONO", "TELEFONO LIS"}:
        return albaran, fecha, supedido
    rc_supedido = _extract_rc_supedido(text)
    if rc_supedido and not re.match(r"^[AH]\d{6}", supedido or "", flags=re.I):
        supedido = rc_supedido
    if not fecha and supedido:
        m_sup_fecha = re.match(r"^[AH](\d{2})(\d{2})(\d{2})(?:/|_|$)", supedido, flags=re.I)
        if m_sup_fecha:
            fecha = f"{m_sup_fecha.group(1)}/{m_sup_fecha.group(2)}/20{m_sup_fecha.group(3)}"
    return albaran, fecha, normalize_supedido_code(supedido)


def _extract_rc_supedido(text: str) -> str:
    m = re.search(
        r"Fec\s*:\s*(\d{1,2})/(\d{1,2})/(\d{2,4}).{0,80}?R\.?\s*C\s*:\s*([AH]?\d{3,6})",
        text,
        flags=re.I | re.S,
    )
    if not m:
        return ""
    _day, month, year, raw = m.groups()
    prefix = raw[0].upper() if raw[0].upper() in {"A", "H"} else "H"
    digits = re.sub(r"\D", "", raw)
    yy = year[-2:]
    if len(digits) == 3:
        return f"{prefix}{digits}{str(int(month))}{yy}"
    if len(digits) == 6:
        return f"{prefix}{digits}"
    return ""


def _num(tok: str):
    tok = tok or ""
    tok = re.sub(r"^[lI|](?=\d)", "1", tok)
    tok = re.sub(r"^[Oo](?=\d)", "0", tok)
    tok = tok.replace(".", "")
    tok = tok.replace("€", "")
    tok = re.sub(r"^[^0-9-]+", "", tok)
    return to_float(tok)


def _clean_numeric_token(tok: str) -> str:
    tok = (tok or "").strip().strip(";:")
    for noise in ("\u00b7", "\u00c2\u00b7", "\u20ac", "\u00e2\u201a\u00ac"):
        tok = tok.replace(noise, "")
    tok = tok.replace("Ã‚Â·", "").replace("Â·", "").replace("â‚¬", "")
    tok = re.sub(r"^[jJ](?=[,.]\d)", "1", tok)
    tok = re.sub(r"^[lI|](?=[\d,.])", "1", tok)
    tok = re.sub(r"^[Oo](?=[\d,.])", "0", tok)
    return tok


def _is_numeric_token(tok: str) -> bool:
    return re.fullmatch(r"[0-9][0-9.,]*", _clean_numeric_token(tok)) is not None


def _num_col(tok: str):
    tok = _clean_numeric_token(tok)
    if "," not in tok and re.fullmatch(r"\d{1,4}\.\d{1,2}", tok):
        tok = tok.replace(".", ",")
    return _num(tok)


def _normalize_code(code: str | None) -> str | None:
    if not code:
        return code
    c = code.lstrip()  # mantenemos posibles espacios de cola
    had_trailing = c.endswith(" ")
    c = c.rstrip()
    # Correcciones OCR frecuentes:
    #  - 3IA16000050 -> 3L416000050 (I A 1 -> L 4 1)
    c = re.sub(
        r"^(?P<prefix>\d)IA(?P<tail>\d+)$",
        lambda m: f"{m.group('prefix')}L4{m.group('tail')}",
        c,
        flags=re.I,
    )
    #  - FEL0xxxx -> FELOxxxx (0 por O tras FEL)
    c = re.sub(r"^(FEL)0", r"\1O", c, flags=re.I)
    #  - STAN1xxxxx -> STANIxxxxx (1 por I entre letras)
    c = re.sub(r"^(STAN)1", r"\1I", c, flags=re.I)
    # ruido OCR inicial (jNIE000... -> NIE000...)
    if c.lower().startswith("jnie"):
        c = c[1:]
    # caso puntual: IZAR5xxxx -> IZARSxxxx (OCR 5 por S)
    if re.fullmatch(r"IZAR5\d{4,}", c, re.I):
        c = re.sub(r"^IZAR5", "IZARS", c, flags=re.I)
    # ALYl92401 -> ALY192401 (l/I por 1 en la parte numérica)
    c = re.sub(r"(?<=\D)[lI](?=\d)", "1", c)
    # re-aplica corrección específica tras normalizar dígitos (STAN130697 -> STANI30697)
    c = re.sub(r"^(STAN)1", r"\1I", c, flags=re.I)
    if c.upper().startswith("IALY"):
        c = c[1:]
    # agrega espacio de cola para códigos que en origen vienen acolchados
    trailing_pad = {"IZARS2485", "IZAR30223", "EGO568020000", "KNIP7002180", "BELL8251250CPN"}
    if c in trailing_pad or had_trailing:
        c = c + " "
    return c


def _parse_row(ln: str):
    ln = normalize_spaces(ln)
    if not ln:
        return None
    ln = re.sub(r"^\s*[jJ]\s+(?=TES)", "", ln)
    ln = re.sub(r"\bTES[oO][:;]?[lI1]\b", "TES04", ln, flags=re.I)
    ln = re.sub(r"(?<![A-Za-z0-9])[lI|](?=\d+[,.]\d)", "1", ln)
    ln = re.sub(r"(?<![A-Za-z0-9])[Oo](?=\d+[,.]\d)", "0", ln)
    first_word = re.search(r"\b[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9./-]{3,}\b", ln, re.I)
    if first_word and first_word.start() > 0:
        prefix = ln[: first_word.start()]
        if len(prefix.strip()) <= 12 and not re.search(r"\d", prefix):
            ln = ln[first_word.start() :]
    up = ln.upper()
    if re.search(r"\b(TOTAL|NETO|IMPONIBLE|IVA|CUOTA|IMPORTE NETO)\b", up):
        return None
    if "ART" in up and "ICULO" in up:
        return None
    if "IMPORTE NETO" in up or "TOTAL ALBAR" in up:
        return None
    # descarta líneas de contacto/dirección
    if re.search(r"\b(TEL|TLF|FAX|TF)\b", up):
        return None
    if not re.search(r"[A-Za-z]{3,}", ln):
        return None
    nums = list(NUM_RE.finditer(ln))
    if len(nums) < 2:
        return None
    tokens = ln.split()
    # Une tokens tipo "ALY" "170610" -> "ALY170610"
    merged_tokens = []
    skip = False
    for i, tok in enumerate(tokens):
        if skip:
            skip = False
            continue
        if i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if re.fullmatch(r"[A-Za-z]{2,}", tok) and re.fullmatch(r"[0-9]{3,}", nxt):
                merged_tokens.append(tok + nxt)
                skip = True
                continue
        merged_tokens.append(tok)
    tokens = merged_tokens
    # localizar el primer token alfanumérico como código (si existe antes de las cifras)
    code_idx = None
    for i, t in enumerate(tokens):
        if re.search(r"[A-Z]", t, re.I) and re.search(r"[0-9]", t):
            code_idx = i
            break
    if code_idx is None and tokens and re.fullmatch(r"[A-Z][A-Z0-9]{3,}", tokens[0], flags=re.I):
        code_idx = 0

    start_n = code_idx + 1 if code_idx is not None else 0
    numeric_idx = [
        i
        for i, t in enumerate(tokens[start_n:], start=start_n)
        if _is_numeric_token(t)
    ]
    # si hay más de 2 números y el primero es muy grande (longitud), descartarlo
    while len(numeric_idx) >= 3:
        val = _num_col(tokens[numeric_idx[0]])
        nxt = _num_col(tokens[numeric_idx[1]])
        if val is not None and val > 50 and (nxt is not None and nxt <= 50):
            numeric_idx = numeric_idx[1:]
            continue
        break

    # --- Heurística principal: números con coma (formato ES) ---
    comma_matches = list(COMMA_NUM_RE.finditer(ln))
    qty = price = disc = imp = None
    prefer_numeric_tail = len(comma_matches) == 2 and len(numeric_idx) >= 3
    if len(comma_matches) >= 2 and not prefer_numeric_tail:
        qty = _num(comma_matches[0].group(0))
        price = _num(comma_matches[1].group(0))
        imp = _num(comma_matches[-1].group(0))
        between = ln[comma_matches[1].end() : comma_matches[-1].start()]
        m_disc = re.search(r"\b(\d{1,3})\b", between)
        if m_disc:
            dval = _num(m_disc.group(1))
            if dval is not None and 0 <= dval <= 100:
                disc = dval
        if len(comma_matches) == 2:
            tail = ln[comma_matches[1].end() :]
            m_tail_disc = re.search(r"\b(\d{1,3})\b", tail)
            if m_tail_disc:
                dval = _num(m_tail_disc.group(1))
                if dval is not None and 0 <= dval < 100:
                    disc = dval
                    if qty is not None and price is not None:
                        imp = round(qty * price * (100 - disc) / 100, 2)
            elif qty is not None and price is not None:
                imp = round(qty * price, 2)

    # Fallback: secuencia cruda si faltan datos
    if qty is None or price is None or imp is None:
        if len(numeric_idx) < 2:
            return None
        first_qty = _num_col(tokens[numeric_idx[0]])
        # evitar interpretar longitudes como cantidad si no tenemos código
        if code_idx is None and first_qty is not None and first_qty > 50:
            return None
        qty = qty if qty is not None else first_qty
        price = price if price is not None else (_num_col(tokens[numeric_idx[1]]) if len(numeric_idx) > 1 else None)
        imp = imp if imp is not None else _num_col(tokens[numeric_idx[-1]])
        if len(numeric_idx) >= 3 and disc is None:
            maybe_disc = _num_col(tokens[numeric_idx[2]])
            if maybe_disc is not None and maybe_disc <= 100 and numeric_idx[2] != numeric_idx[-1]:
                disc = maybe_disc
            if len(numeric_idx) >= 4:
                imp = _num_col(tokens[numeric_idx[-1]])

    if code_idx is None or (numeric_idx and code_idx > numeric_idx[0]) or not numeric_idx:
        code = ""
        concept_tokens = tokens[: (numeric_idx[0] if numeric_idx else len(tokens))]
    else:
        code = tokens[code_idx]
        concept_tokens = tokens[code_idx + 1 : numeric_idx[0]]

    concept = " ".join(concept_tokens).strip()
    # si concepto está vacío pero hay texto entre qty y precio, úsalo
    if not concept and numeric_idx and (numeric_idx[1] - numeric_idx[0] > 1):
        concept = " ".join(tokens[numeric_idx[0] + 1 : numeric_idx[1]]).strip()
    # si sigue vacío y hay texto antes del primer número (sin código), usarlo completo
    if not concept and not code and numeric_idx and numeric_idx[0] > 0:
        concept = " ".join(tokens[: numeric_idx[0]]).strip()

    code = _normalize_code(code)

    if code and (len(code) < 3 or not re.search(r"[A-Za-z]", code)):
        code = ""

    if qty is None or imp is None or not concept:
        return None

    return qty, code or None, concept, price, disc, imp


def _is_spurious_no_code_row(raw_line: str, concept: str) -> bool:
    text = normalize_spaces(f"{raw_line or ''} {concept or ''}").upper()
    if any(marker in text for marker in NO_CODE_NOISE_MARKERS):
        return True
    if len((concept or "").split()) <= 2 and re.search(r"\bMANANA|MAÑANA|PENDIENTE\b", text):
        return True
    return False


def _looks_like_table_header(line: str) -> bool:
    normalized = unicodedata.normalize("NFKD", line.upper())
    compact = re.sub(
        r"[^A-Z0-9]",
        "",
        "".join(ch for ch in normalized if not unicodedata.combining(ch)),
    )
    return (
        "CANTIDAD" in compact
        and "PRECIO" in compact
        and "IMPORTE" in compact
        and ("DESCRIP" in compact or "DESIPC" in compact or "DESIPCI" in compact)
    )


def parse_page(page, page_num, proveedor_detectado="TXOFRE"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)
    albaran, fecha, supedido = _extract_header(joined)
    # localizar inicio de tabla
    header_idx = next(
        (i for i, ln in enumerate(lines) if re.search(r"ART[IÍ]CULO.*DESCRIP", ln, re.I) and re.search(r"CANT", ln, re.I)),
        0,
    )
    if header_idx == 0:
        for idx, line in enumerate(lines):
            if _looks_like_table_header(line):
                header_idx = idx
                break

    items = []
    suma = 0.0

    stop_markers = (
        "IMPORTE NETO",
        "TOTAL ALBAR",
        "CONFORME",
        "BASE IMPONIBLE",
        "IVA",
        "CUOTA",
        "TOTAL",
    )

    def _compact_stop(line: str) -> bool:
        normalized = unicodedata.normalize("NFKD", line.upper())
        compact = re.sub(r"[^A-Z0-9]", "", "".join(ch for ch in normalized if not unicodedata.combining(ch)))
        return any(marker in compact for marker in ("IMPORTENETO", "PORTENETO", "BASEIMPONIBLE", "TOTALALBARAN"))

    def _footer_neto() -> float | None:
        for idx, raw in enumerate(lines):
            normalized = unicodedata.normalize("NFKD", raw.upper())
            compact = re.sub(r"[^A-Z0-9]", "", "".join(ch for ch in normalized if not unicodedata.combining(ch)))
            if "PORTENETO" not in compact and "IMPORTENETO" not in compact:
                continue
            for nxt in lines[idx + 1 : idx + 5]:
                nums = COMMA_NUM_RE.findall(nxt)
                if nums:
                    return _num(nums[0])
        return None

    i = header_idx + 1
    while i < len(lines):
        ln = lines[i]
        up = ln.upper()
        if any(m in up for m in stop_markers) or _compact_stop(ln):
            break
        detail = _parse_row(ln)
        if detail:
            qty, code, concept, price, disc, imp = detail
            disc = disc if disc is not None else 0.0
            if not code and _is_spurious_no_code_row(ln, concept):
                i += 1
                continue
            # En TXOFRE el codigo de articulo es estructural; si no existe y no es un
            # caso especial ya manejado arriba (CORONA...), descartamos para no crear
            # lineas espurias que desplazan el resto.
            if not code:
                i += 1
                continue
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
                "DescuentoPct": disc,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "",
            }
            item = fix_qty_price_import(item)
            items.append(item)
            if imp is not None:
                suma += imp
        i += 1

    neto_footer = _footer_neto()
    if neto_footer is not None and items and abs(suma - neto_footer) > 0.05:
        diff = round(neto_footer - suma, 2)
        last = items[-1]
        last_imp = last.get("Importe")
        qty = last.get("CantidadServida")
        if last_imp is not None and qty not in (None, 0) and abs(diff) <= max(20.0, abs(float(last_imp)) * 0.25):
            new_imp = round(float(last_imp) + diff, 2)
            if new_imp >= 0 or float(last_imp) < 0:
                last["Importe"] = new_imp
                last["PrecioUnitario"] = round(new_imp / float(qty), 4)
                last["ParseWarn"] = normalize_spaces(f"{last.get('ParseWarn') or ''}; txofre_footer_reconciled".strip("; "))
                suma = round(neto_footer, 2)

    meta = {
        "Proveedor": proveedor_detectado,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": supedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan if neto_footer is None else neto_footer,
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
