import re
import numpy as np
from common import normalize_spaces, to_float, fix_qty_price_import, normalize_supedido_code

PARSER_ID = "alkain"
PROVIDER_NAME = "ALKAIN"

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
NUM_RE = re.compile(r"(?:\d{1,3}(?:\.\d{3})*,\s*\d{2,4}|\d+\.\d{2,4})")
ONE_OF_ONE_RE = re.compile(r"\b1\s*/\s*1\b")

TEMPLATE = {
    "header": {
        "albaran_patterns": [
            r"ALBAR[ÃA]N\s+NUMERO\s*[:\-]?\s*(?P<value>\d+)",
            r"ALBAR[ÃA]N\s*#?\s*(?P<value>\d+)",
        ],
        "fecha_patterns": [
            r"Fecha\s+Albar[Ã¡a]n\s*[:\-]?\s*(?P<value>\d{1,2}/\d{1,2}/\d{2,4})",
            r"\b(?P<value>\d{1,2}/\d{1,2}/\d{2,4})\b",
        ],
        "su_pedido_patterns": [
            r"Su\s+Pedido\s+(?P<value>[A-Z0-9./-]{4,})",
            r"\b(?P<value>\d{5,6})\b",
        ],
    },
}

HEADER_PATTERNS = {
    "albaran": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["albaran_patterns"]],
    "fecha": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["fecha_patterns"]],
    "supedido": [re.compile(pat, re.I) for pat in TEMPLATE["header"]["su_pedido_patterns"]],
}

def _extract_first(text: str, patterns: list[re.Pattern]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            groups = match.groupdict()
            if "value" in groups:
                return groups["value"].strip()
            if match.groups():
                return match.group(1).strip()
            return match.group(0).strip()
    return ""

def _ascii_upper(s: str) -> str:
    try:
        import unicodedata as _ud

        return "".join(ch for ch in _ud.normalize("NFKD", s or "") if not _ud.combining(ch)).upper()
    except Exception:
        return (s or "").upper()


def _norm_date(token: str | None) -> str:
    if not token:
        return ""
    parts = token.strip().split("/")
    if len(parts) != 3:
        return ""
    d, m, y = parts
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(m):02d}/{int(y):04d}"


def _is_valid_date_digits(token: str) -> bool:
    if not token or len(token) not in (6, 8) or not token.isdigit():
        return False
    day = int(token[:2])
    month = int(token[2:4])
    if day < 1 or day > 31 or month < 1 or month > 12:
        return False
    if len(token) == 8:
        year = int(token[4:])
        if year < 2000 or year > 2100:
            return False
    return True


def _extract_albaran_from_fecha_row(raw: str) -> str:
    """Extrae albarÃ¡n desde una fila FECHA/ALBARAN aun con OCR ruidoso."""
    for date_match in DATE_RE.finditer(raw or ""):
        tail = raw[date_match.end() : date_match.end() + 40]
        digits = re.sub(r"\D", "", tail)
        for size in (9, 8):
            if len(digits) < size:
                continue
            cand = digits[:size]
            if cand.startswith("9"):
                continue
            if len(set(cand)) <= 2:
                continue
            return cand

    seq = re.sub(r"\D", "", raw or "")
    if len(seq) < 14:
        return ""
    max_start = min(12, max(0, len(seq) - 14))
    for i in range(max_start + 1):
        for date_len in (8, 6):
            if i + date_len + 8 > len(seq):
                continue
            head = seq[i : i + date_len]
            if not _is_valid_date_digits(head):
                continue
            tail = seq[i + date_len :]
            # ALKAIN: preferimos 9 dÃ­gitos, con fallback a 8.
            for size in (9, 8):
                if len(tail) < size:
                    continue
                cand = tail[:size]
                if cand.startswith("9"):
                    continue
                if len(set(cand)) <= 2:
                    continue
                return cand
    return ""


def _recover_albaran_from_attended_row(row: str) -> str:
    """Recupera ALKAIN cuando OCR rompe el albaran como '-u1008766'."""
    if not row:
        return ""
    upper = _ascii_upper(row)
    if not any(marker in upper for marker in ("ATEND", "ALKAIN.COM", "943642")):
        return ""
    compact = re.sub(r"\s+", "", upper)
    match = re.search(r"[-_./]?[UVY]?((?:1|I)[O0]{2}[0-9OIL]{4,6})", compact)
    if not match:
        return ""
    tail = (
        match.group(1)
        .replace("O", "0")
        .replace("I", "1")
        .replace("L", "1")
    )
    digits = re.sub(r"\D", "", tail)
    if len(digits) not in (7, 8):
        return ""
    return f"26{digits}"


def _albaran_scan_limit(lines: list[str]) -> int:
    """Limita el escaneo al bloque alto para evitar ruido OCR del pie legal."""
    limit = min(len(lines), 70)
    footer_tokens = (
        "CONDICIONES GENERALES",
        "PROTECCION DE DATOS",
        "PROTECCIÃ“N DE DATOS",
        "KUTXABANK",
        "SWIFT",
        "NIF INTR",
    )
    for idx, ln in enumerate(lines):
        up = _ascii_upper(ln)
        if any(tok in up for tok in footer_tokens):
            limit = min(limit, idx)
            break
    return max(limit, min(len(lines), 20))


def _find_albaran(lines: list[str], joined: str) -> str:
    def _push(storage: list[tuple[int, int, int, int, str]], value: str, weight: int) -> None:
        if not value:
            return
        token = value.strip()
        if not token:
            return
        digits = re.sub(r"\D", "", token)
        if len(digits) == 10 and digits.startswith("261") and digits.endswith("1"):
            digits = digits[:-1]
            token = digits
        if len(digits) < 6:
            return
        # Evita ruido OCR (cadenas demasiado largas o repeticiones de un unico digito).
        if len(digits) > 10:
            return
        if len(set(digits)) == 1 and len(digits) >= 8:
            return
        len_penalty = 0 if len(digits) in (8, 9) else 1
        repeat_penalty = 1 if len(set(digits)) <= 2 and len(digits) >= 9 else 0
        distance_penalty = abs(len(digits) - 8)
        storage.append((weight, len_penalty, repeat_penalty, distance_penalty, token))

    candidates: list[tuple[int, int, int, int, str]] = []
    scan_limit = _albaran_scan_limit(lines)

    for idx in range(scan_limit):
        candidate = _recover_albaran_from_attended_row(lines[idx])
        if candidate:
            _push(candidates, candidate, -3)

    # Prioridad maxima: fila FECHA/ALBARAN (aunque venga con OCR roto).
    for idx in range(scan_limit):
        window = " ".join(lines[idx : min(scan_limit, idx + 2)])
        letters = re.sub(r"[^A-Z]", "", _ascii_upper(window))
        if "ALBAR" not in letters:
            continue
        if ("FECHA" not in letters) and ("ATENDIDOPOR" not in letters):
            continue
        candidate = _extract_albaran_from_fecha_row(window)
        if candidate:
            _push(candidates, candidate, -2)

    # Numeros largos no marcados como "pedido" (evita confundir su pedido con albaran).
    for idx, ln in enumerate(lines[:scan_limit]):
        up = _ascii_upper(ln)
        skip_pedido = "PEDIDO" in up or "SOLICITADO" in up
        skip_tax = bool(
            re.search(r"\bC\W*I\W*F\b", up)
            or re.search(r"\bN\W*I\W*F\b", up)
            or "TVA" in up
            or "INTRACOM" in up
        )
        if skip_tax and "ALBAR" not in up:
            continue
        for m in re.finditer(r"\b(\d{8,9})\b", ln):
            token = m.group(1)
            if token.startswith("9"):  # evita telefonos
                continue
            if skip_pedido:
                continue
            weight = 2 if idx < 10 else 3
            _push(candidates, token, weight)

    for idx in range(scan_limit):
        window = " ".join(lines[idx : min(scan_limit, idx + 2)])
        m = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b[^\d]{0,10}(\d{7,})\b", window)
        if m:
            _push(candidates, m.group(1), 0)
        m2 = re.search(r"(\d{7,9})[^\d]{0,6}\d{1,2}/\d{1,2}/\d{2,4}", window)
        if m2:
            _push(candidates, m2.group(1), 0)
        m3 = re.search(r"ALBAR[ÃA]N[^\d]{0,15}(\d{6,})", window, re.I)
        if m3:
            _push(candidates, m3.group(1), 0)

    # Busca patron fecha + numero en la misma linea (ej. 03/02/26 261004599).
    for ln in lines[:scan_limit]:
        m = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}\D+(\d{7,9})", ln)
        if m:
            _push(candidates, m.group(1), 0)

    direct = _extract_first(joined, HEADER_PATTERNS["albaran"])
    if direct:
        _push(candidates, direct, 1)

    for idx, ln in enumerate(lines[:scan_limit]):
        up = _ascii_upper(ln)
        if "FECHA" in up and "ALBAR" in up:
            window = " ".join(lines[idx : min(scan_limit, idx + 3)])
            m = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}\D+(\d{6,})", window)
            if m:
                _push(candidates, m.group(1), 1)

    for idx, ln in enumerate(lines[:scan_limit]):
        if "ALBAR" in _ascii_upper(ln):
            for j in range(idx, min(scan_limit, idx + 3)):
                for m in re.finditer(r"\b(\d{6,9})\b", lines[j]):
                    _push(candidates, m.group(1), 2)

    if candidates:
        candidates.sort()
        return candidates[0][4]
    return ""


def _find_fecha(lines: list[str], joined: str) -> str:
    direct = _extract_first(joined, HEADER_PATTERNS["fecha"])
    if direct:
        return _norm_date(direct)
    for ln in lines:
        m = DATE_RE.search(ln)
        if m:
            return _norm_date(m.group(1))
    m = DATE_RE.search(joined)
    return _norm_date(m.group(1)) if m else ""


def _looks_numeric(token: str | None) -> bool:
    if not token:
        return False
    token = token.replace(".", "").replace(" ", "")
    return bool(re.fullmatch(r"-?\d+(?:,\d+)?", token))


STOP_RE = re.compile(r"(ANTICIPO|CONDICIONES|FORMA DE PAGO|IMPORTE TOTAL)", re.I)
SUPEDIDO_BLACKLIST = {"20014", "20115", "20280", "20018", "20870"}
INLINE_CODE_RE = re.compile(r"^\s*(?:\d+\s+)?(\d{5,6})\s*$")
PEDIDO_RE = re.compile(r"PEDIDO[:\s]+([A-Z0-9./-]{4,20})", re.I)
ORDER_CODE_RE = re.compile(r"\b(\d{2}\.\d{3}/\d{2}|[A-Z]?-?\d{5,6}/\d{2}|[A-Z]?-?\d{5,6})\b")


def _find_supedido(lines: list[str], header_idx: int | None = None) -> str:
    sample_text = " ".join(lines[:240])

    def _clean(token: str | None) -> str:
        if not token:
            return ""
        t = token.strip().upper().replace(",", "").replace(" ", "")
        t = re.sub(r"/+", "/", t)
        t = t.strip("/-")
        return t

    candidates: list[tuple[int, int, str]] = []

    def _specificity(token: str) -> int:
        tok = token or ""
        if re.match(r"^[AH]-?\d{6}(?:/[A-Z0-9]{1,4})?$", tok, re.I):
            return 0
        if "/" in tok or "." in tok:
            return 0
        if tok.isdigit():
            return 2
        return 1

    def _push(token: str | None, weight: int, allow_long_numeric: bool = False):
        tok = _clean(token)
        if not tok:
            return
        if tok in SUPEDIDO_BLACKLIST:
            return
        if tok.isdigit():
            if len(tok) <= 4:
                return
            if len(tok) >= 8 and not allow_long_numeric:
                return
            if len(tok) == 5 and not tok.startswith("25"):
                return
        candidates.append((weight, _specificity(tok), tok))

    # 1) DespuÃ©s de la palabra PEDIDO
    for ln in lines:
        m = re.search(r"VUESTRO\s+PEDIDO\s+([A-Z0-9./-]{4,})", ln, re.I)
        if m:
            _push(m.group(1), 0, allow_long_numeric=True)
        m2 = re.search(r"PEDIDO\s*[:\-]\s*([A-Z0-9./-]{4,})", ln, re.I)
        if m2:
            _push(m2.group(1), 0, allow_long_numeric=True)

    for ln in lines:
        for m in PEDIDO_RE.finditer(ln):
            _push(m.group(1), 0, allow_long_numeric=True)

    # 2) Patrones de cÃ³digo tipo 25.037/01 o 25037/01 cerca del encabezado/tabla
    ranges = []
    if header_idx is not None:
        # Incluye primeras lÃ­neas tras cabecera, donde suele aparecer SuPedido.
        ranges.append((max(0, header_idx - 14), min(len(lines), header_idx + 6)))
    else:
        ranges.append((0, min(len(lines), 40)))
    for start, end in ranges:
        # Evita confundir cÃ³digos de lÃ­nea con su pedido
        item_tokens: set[str] = set()
        if header_idx is not None:
            for ln in lines[header_idx + 1 : min(len(lines), header_idx + 30)]:
                ln_clean = re.sub(r"^\s*\d{1,3}:\s*", "", ln)
                mfirst = re.match(r"^\s*(\d{4,8})\b", ln_clean)
                if mfirst:
                    item_tokens.add(mfirst.group(1))

        for ln in lines[start:end]:
            for m in ORDER_CODE_RE.finditer(ln):
                tok = m.group(1)
                if tok in item_tokens:
                    continue
                _push(tok, 1)
            m = INLINE_CODE_RE.match(ln.strip())
            if m:
                _push(m.group(1), 3)

    # 3) Patrones generales del template (menos preferentes)
    direct = _extract_first(sample_text, HEADER_PATTERNS["supedido"])
    if header_idx is not None:
        item_tokens = set()
        for ln in lines[header_idx + 1 : min(len(lines), header_idx + 30)]:
            ln_clean = re.sub(r"^\s*\d{1,3}:\s*", "", ln)
            m = re.match(r"\s*(\d{4,8})\b", ln_clean)
            if m:
                item_tokens.add(m.group(1))
        if direct in item_tokens:
            direct = ""
    _push(direct, 4)

    if not candidates:
        return ""
    candidates.sort()
    return candidates[0][2]


def parse_page(page, page_num):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    is_one_of_one = any(ONE_OF_ONE_RE.search(ln) for ln in lines[:40])
    NOISE_PATTERNS = [
        r"A20074738",
        r"\b943\s*642\s*025\b",
        r"\b943\s*557\s*900\b",
        r"WWW\.ALKAIN\.COM",
        r"JUAN\s+ALCAIN\s+J[ÃA]UREGUI",
        r"AMUTALDE\s+KALEA",
        r"PASEALEKUA",
        r"C/\\s*ZULOOGA",
    ]
    noise_re = re.compile("|".join(NOISE_PATTERNS), re.I)
    def _is_required_line(ln: str) -> bool:
        if re.search(r"\b\d{8,9}\b", ln):
            return True
        return bool(re.search(r"\b(PEDIDO|ALBAR|ART[ÃI]CULO|DESCRIP)\b", ln, re.I))
    lines = [ln for ln in lines if not (noise_re.search(ln) and not _is_required_line(ln))]
    joined = " ".join(lines)

    albaran = _find_albaran(lines, joined)
    fecha = _find_fecha(lines, joined)
    su_pedido = ""

    header_idx = None
    for idx, ln in enumerate(lines):
        u = _ascii_upper(ln)
        if "ART" in u and "DESCRIP" in u and ("CANTIDAD" in u or "CANT" in u) and "PRECIO" in u:
            header_idx = idx
            break

    items = []
    suma = 0.0

    current = None
    if header_idx is not None:
        skip_rows: set[int] = set()
        inline_candidate = ""

        for idx in range(header_idx + 1, min(len(lines), header_idx + 6)):
            m = INLINE_CODE_RE.match(lines[idx])
            if m:
                candidate = m.group(1)
                if candidate and candidate not in SUPEDIDO_BLACKLIST:
                    inline_candidate = candidate
                    skip_rows.add(idx)
                    break

        def _norm_order(token: str) -> str:
            """
            Normaliza cÃ³digos de pedido (su_pedido) para ALKAIN.
            - Respeta patrones 25.xxx/yy, Hxxxxxx, Axxxxxx y variantes OCR con guiones.
            - Evita devolver el mismo nÃºmero que el albarÃ¡n.
            """
            if not token:
                return ""
            t = token.replace(",", "").strip()
            t = t.replace(" ", "")
            t = re.sub(r"/+", "/", t).strip("/-")

            m = re.match(r"^(25)(\d{3})(/\d{2})$", t)
            if m:
                return f"25.{m.group(2)}/{m.group(3).lstrip('/')}"
            m = re.match(r"^(25)(\d{3})$", t)
            if m:
                return t
            if re.match(r"^[HA]-?\d{6}$", t, re.I):
                digits = re.sub(r"\D", "", t)
                prefix = t[0].upper()
                return f"{prefix}-{digits}" if "-" in t else f"{prefix}{digits}"
            if re.match(r"^\d{8,9}$", t):
                if t.startswith("9"):
                    return ""
                # si coincide con albarÃ¡n, descartar
                digits_alb = re.sub(r"\D", "", albaran or "")
                if digits_alb and t == digits_alb:
                    return ""
                return t

            norm = normalize_supedido_code(t)
            return norm or t

        fallback_supedido = _find_supedido(lines, header_idx)
        if fallback_supedido:
            su_pedido = _norm_order(fallback_supedido)
        elif inline_candidate:
            su_pedido = _norm_order(inline_candidate)
        # si sigue vacÃ­o, mirar sÃ³lo en el bloque de cabecera (antes de tabla)
        if not su_pedido:
            search_range = lines[max(0, header_idx - 16) : header_idx + 1]
            joined_range = " ".join(search_range)
            m_extra = re.search(r"([HA]-?\d{6}|25\.\d{3}/\d{2}|\d{8,9})", joined_range, re.I)
            if m_extra:
                su_pedido = _norm_order(m_extra.group(1))
        if not su_pedido and not albaran:
            date_match = DATE_RE.search(" ".join(lines[:80]))
            if date_match:
                d, mth, y = date_match.group(1).split("/")
                su_pedido = f"A{d.zfill(2)}{mth.zfill(2)}{y[-2:]}"

        i = header_idx + 1
        while i < len(lines):
            if i in skip_rows:
                i += 1
                continue
            ln_raw = lines[i]
            ln = re.sub(r"^\s*\d{1,3}:\s*", "", ln_raw).strip()
            if STOP_RE.search(ln):
                break
            ln = re.sub(r"\b(35|50),\s+(?=\d{1,3},\d{2}\b)", r"\1,00 ", ln)
            matches = list(NUM_RE.finditer(ln))
            if len(matches) >= 2:
                # HeurÃ­stica: prioriza cantidad real (ej. 2 CAJ 24 PZA -> 24)
                qty_idx = 0
                qty_val_first = to_float(matches[0].group(0))
                up_line = _ascii_upper(ln)
                if len(matches) >= 4 and ("CAJ" in up_line or re.search(r"\bCA\b", up_line)):
                    qty_idx = 1
                # Eliminada heurÃ­stica de mover qty si primer nÃºmero <1; mantenemos qty_idx segÃºn CAJ o default.
                quantity_match = matches[qty_idx]
                price_idx = qty_idx + 1 if qty_idx + 1 < len(matches) else qty_idx
                price_match = matches[price_idx] if price_idx < len(matches) else None
                importe_match = matches[-1]
                dto_match = None
                if len(matches) >= 4:
                    dto_match = matches[-2]
                desc_raw = ln[: quantity_match.start()].strip()
                code = ""
                parts = desc_raw.split()
                if parts and re.fullmatch(r"[A-Z0-9./-]{4,}", parts[0]):
                    code = parts[0].strip(".:")
                    desc = " ".join(parts[1:]).strip()
                    # une letra suelta tras cÃ³digo numÃ©rico (ej. 6004800001 M -> 6004800001M)
                    if code.isdigit() and len(parts) >= 2 and re.fullmatch(r"[A-Z]", parts[1]):
                        code = f"{code}{parts[1]}"
                        desc = " ".join(parts[2:]).strip()
                else:
                    desc = desc_raw
                    # si empieza por token numÃ©rico largo, usarlo como cÃ³digo
                    if parts and re.fullmatch(r"\d{8,}", parts[0]):
                        code = parts[0]
                        desc = " ".join(parts[1:]).strip()
                # limpieza de cÃ³digo: quitar signos iniciales y ceros sobrantes
                if code:
                    code = re.sub(r"^[^A-Za-z0-9]+", "", code)
                    if re.fullmatch(r"0\d{7,}", code):
                        code = code.lstrip("0")
                    if code.startswith("1ZAR"):
                        code = "I" + code[1:]
                # si no hay cÃ³digo y descripciÃ³n empieza con patrÃ³n !/1 + dÃ­gitos, extraerlo
                if not code:
                    mcode = re.search(r"(\d{5,})", desc)
                    if mcode:
                        code = mcode.group(1)
                        desc = desc[mcode.end():].strip()
                # normaliza cÃ³digo quitando ceros a la izquierda (ej. 0165700001 -> 165700001)
                if code and re.fullmatch(r"0\d{8,}", code):
                    code = code.lstrip("0")
                # corrige un dÃ­gito '1' espurio al inicio (15008000002 -> 5008000002)
                if code and len(code) == 11 and code.startswith("1") and code[1:].isdigit():
                    code = code[1:]
                # corrige prefijos '1' espurio (ej. 1549955 -> 549955)
                if code and len(code) == 7 and code.startswith("1") and code[1:].isdigit():
                    code = code[1:]
                # corrige prefijos '1ZAR' -> 'IZAR'
                if code.startswith("1ZAR"):
                    code = "I" + code[1:]
                # limpia restos de empaquetado en descripciÃ³n (ej. '2,00 CAJ', '24,00 PZA')
                desc = re.sub(r"\b\d{1,3},\d{2,4}\s*(CAJ|CA|PZA)\b", "", desc, flags=re.I).strip(" -.,")
                desc = re.sub(r"\s{2,}", " ", desc).strip()
                # si su_pedido vacÃ­o y hay token tipo H-####### en lÃ­nea, Ãºsalo
                if not su_pedido:
                    mline = re.search(r"(H-?\d{6,})", ln, re.I)
                    if mline:
                        su_pedido = _norm_order(mline.group(1))
                def _n(tok_match):
                    if not tok_match:
                        return None
                    token = tok_match.group(0).replace(" ", "")
                    if "," not in token and re.fullmatch(r"\d+\.\d{2,4}", token):
                        token = token.replace(".", ",")
                    return to_float(token)

                cantidad = _n(quantity_match)
                precio = _n(price_match) if price_match else None
                dto_val = None
                if dto_match and dto_match not in (importe_match, price_match):
                    dto_val = _n(dto_match)
                if dto_val is None and price_match is not None and importe_match is not None:
                    between = ln[price_match.end(): importe_match.start()]
                    mdisc = re.search(r"(\d{1,2},\d{1,2})", between)
                    if mdisc:
                        dto_val = to_float(mdisc.group(1).replace(" ", ""))
                dto = dto_val if dto_val is not None else 0.0
                importe = _n(importe_match)
                current = {
                    "Proveedor": PROVIDER_NAME,
                    "Parser": PARSER_ID,
                    "AlbaranNumero": albaran,
                    "FechaAlbaran": fecha,
                    "SuPedidoCodigo": su_pedido,
                    "Codigo": code,
                    "Descripcion": desc,
                    "CantidadServida": cantidad,
                    "PrecioUnitario": precio,
                    "DescuentoPct": dto,
                    "Importe": importe,
                    "Pagina": page_num,
                    "Pdf": "",
                    "ParseWarn": "",
                }
                items.append(fix_qty_price_import(current))
                if importe is not None:
                    suma += importe
            else:
                if current and re.search(r"[A-Za-z]", ln):
                    current["Descripcion"] = f"{current['Descripcion']} {ln.strip()}".strip()
            i += 1

    # Rescue compacto: codigo + descripcion + cantidad + precio + dto + importe
    if not items:
        if not su_pedido:
            su_pedido = _find_supedido(lines, None)
        compact_re = re.compile(
            r"^(?P<code>[A-Z0-9./-]{5,})\s+(?P<desc>.+?)\s+"
            r"(?P<qty>\d{1,3},\d{2,4})\s+(?:[A-Z]{1,4}\s+)?"
            r"(?P<price>\d{1,3}(?:\.\d{3})*,\d{2,4})\s+"
            r"(?P<dto>\d{1,2},\d{2})\s+"
            r"(?P<imp>\d{1,3}(?:\.\d{3})*,\d{2})\s*$",
            re.I,
        )
        for ln in lines:
            m = compact_re.match(ln)
            if not m:
                continue
            code = m.group("code").strip()
            desc = normalize_spaces(m.group("desc"))
            qty = to_float(m.group("qty"))
            price = to_float(m.group("price"))
            dto = to_float(m.group("dto"))
            imp = to_float(m.group("imp"))
            if qty is None or imp is None:
                continue
            item = {
                "Proveedor": PROVIDER_NAME,
                "Parser": PARSER_ID,
                "AlbaranNumero": albaran,
                "FechaAlbaran": fecha,
                "SuPedidoCodigo": su_pedido,
                "Codigo": code,
                "Descripcion": desc,
                "CantidadServida": qty,
                "PrecioUnitario": price,
                "DescuentoPct": dto,
                "Importe": imp,
                "Pagina": page_num,
                "Pdf": "",
                "ParseWarn": "alkain_compact_rescue",
            }
            items.append(fix_qty_price_import(item))
            suma += imp

    def _amount_after(keyword: str, pick_last: bool = False, value_index: int | None = None):
        up_kw = keyword.upper()
        for idx, ln in enumerate(lines):
            upper_ln = _ascii_upper(ln)
            if up_kw in upper_ln:
                start = upper_ln.find(up_kw)
                segment = ln[start:]
                tail = lines[idx + 1] if idx + 1 < len(lines) else ""
                window = f"{segment} {tail}".strip()
                nums = NUM_RE.findall(window)
                if nums:
                    if value_index is not None:
                        idx_use = value_index if value_index >= 0 else len(nums) + value_index
                        idx_use = max(0, min(len(nums) - 1, idx_use))
                        token = nums[idx_use]
                    else:
                        token = nums[-1] if pick_last else nums[0]
                    return to_float(token.replace(" ", ""))
        return None

    base = _amount_after("BASE IMPONIBLE", value_index=1)
    total = _amount_after("IMPORTE TOTAL", pick_last=True)
    if total is None:
        total = _amount_after("TOTAL", pick_last=True)

    meta = {
        "Proveedor": PROVIDER_NAME,
        "Parser": PARSER_ID,
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": suma,
        "NetoComercialPie": np.nan if base is None else base,
        "TotalAlbaranPie": np.nan if total is None else total,
    }

    try:
        from debugkit import dbg_parser_page

        dbg_parser_page(
            PARSER_ID,
            page_num,
            header={"AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido},
            items=items,
            meta=meta,
        )
    except Exception:
        pass

    return items, meta

