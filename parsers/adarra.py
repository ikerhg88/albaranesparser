from __future__ import annotations

import re

import numpy as np

from common import normalize_spaces, parse_date_es, to_float

PARSER_ID = "adarra"
PROVIDER_NAME = "ADARRA"
BRAND_ALIASES = ["SUMINISTROS INDUSTRIALES ADARRA", "ADARRA S.A."]

ALB_RE = re.compile(r"ALBARAN[AE]?\s*([A-Z0-9./-]{6,})", re.I)
SUPEDIDO_RE = re.compile(r"(?:BEZEROAREN\s+ERREFERENTZIA|REFERENTZIA)\s*([A-Z]*\d[A-Z0-9./-]{5,})", re.I)
ROW_RE = re.compile(
    r"^(?P<code>[0-9A-Z./-]{6,})\s+(?P<desc>.+?)\s+(?P<qty>\d{1,4},\d{2,4})\s+"
    r"(?P<price>\d{1,3}(?:\.\d{3})*,\d{2,4})\s+(?P<imp>\d{1,3}(?:\.\d{3})*,\d{2})(?:\s*€)?$",
    re.I,
)


def _normalize_albaran(raw: str) -> str:
    token = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not token:
        return ""
    digits = re.sub(r"\D", "", token)
    if token[0].isalpha() and len(digits) >= 7:
        return digits
    return token


def _normalize_supedido(raw: str) -> str:
    token = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not token:
        return ""
    if len(token) >= 2 and token[0].isalpha():
        token = token[0] + token[1:].replace("O", "0")
    return token


def _extract_header(lines: list[str], text: str) -> tuple[str, str, str]:
    albaran = ""
    m = ALB_RE.search(text)
    if m:
        albaran = _normalize_albaran(m.group(1))
    fecha = parse_date_es(text)

    supedido = ""
    m2 = SUPEDIDO_RE.search(text)
    if m2:
        supedido = _normalize_supedido(m2.group(1))
    if not supedido:
        for idx, ln in enumerate(lines):
            up = ln.upper()
            if "ERREFERENTZIA" not in up and "REFERENTZIA" not in up:
                continue
            window = " ".join(lines[idx : idx + 5])
            for token in re.findall(r"\b([A-Z0-9./-]{6,})\b", window):
                if sum(ch.isdigit() for ch in token) < 4:
                    continue
                supedido = _normalize_supedido(token)
                if supedido:
                    break
            if supedido:
                break
    return albaran, fecha, supedido


def _num(token: str):
    return to_float((token or "").replace(".", "").replace("€", ""))


def _parse_row(line: str):
    line = normalize_spaces(line)
    if not line:
        return None
    m = ROW_RE.match(line)
    if not m:
        return None
    code = m.group("code").strip()
    desc = m.group("desc").strip()
    qty = _num(m.group("qty"))
    price = _num(m.group("price"))
    imp = _num(m.group("imp"))
    if qty is None or imp is None:
        return None
    return qty, code, desc, price, imp


def parse_page(page, page_num, proveedor_detectado="ADARRA"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    joined = " ".join(lines)

    albaran, fecha, supedido = _extract_header(lines, joined)
    items = []
    suma = 0.0

    stop_markers = ("ZERGAK", "GUZTIRA", "TOTAL", "IZENA:", "DATA/ORDUA")
    idx = 0
    while idx < len(lines):
        ln = lines[idx]
        up = ln.upper()
        if any(marker in up for marker in stop_markers):
            break
        detail = _parse_row(ln)
        if detail:
            qty, code, concept, price, imp = detail
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
                    "ParseWarn": "",
                }
            )
            if imp is not None:
                suma += imp
            idx += 1
            continue

        # Variante multilinea: codigo+descripcion y numeros en lineas siguientes.
        m_code = re.match(r"^(?P<code>[0-9A-Z./-]*\d[0-9A-Z./-]{5,})\s+(?P<desc>.+)$", ln, re.I)
        if m_code:
            window = " ".join(lines[idx : min(len(lines), idx + 5)])
            decimals = re.findall(r"\d{1,4},\d{2,4}", window)
            if len(decimals) >= 3:
                qty = _num(decimals[0])
                price = _num(decimals[1])
                imp = _num(decimals[2])
                if qty is not None and imp is not None:
                    items.append(
                        {
                            "Proveedor": proveedor_detectado,
                            "Parser": PARSER_ID,
                            "AlbaranNumero": albaran,
                            "FechaAlbaran": fecha,
                            "SuPedidoCodigo": supedido,
                            "Codigo": m_code.group("code").strip(),
                            "Descripcion": normalize_spaces(m_code.group("desc")),
                            "CantidadServida": qty,
                            "PrecioUnitario": price,
                            "DescuentoPct": None,
                            "Importe": imp,
                            "Pagina": page_num,
                            "Pdf": "",
                            "ParseWarn": "adarra_multiline_rescue",
                        }
                    )
                    suma += imp
                    idx += 4
                    continue

        idx += 1

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
