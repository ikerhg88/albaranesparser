import re
import numpy as np
from common import normalize_spaces, to_float, parse_date_es

PARSER_ID = "generic"
PROVIDER_NAME = "DESCONOCIDO"

def parse_page(page, page_num, proveedor_detectado="DESCONOCIDO"):
    text = page.extract_text() or ""
    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
    desc = " | ".join(lines[:10])
    joined = " ".join(lines)
    albaran = _extract_first(joined, [
        r"ALBAR[ÁA]N\s*(?:N[ºO]|NUM(?:ERO)?)?\s*[:#-]?\s*([A-Z0-9\-/]+)",
        r"ALB\.?:\s*([A-Z0-9\-/]+)",
    ])

    su_pedido = _extract_first(joined, [
        r"SU\s+PEDIDO\s*(?:N[ºO]|NUM(?:ERO)?)?\s*[:#-]?\s*([A-Z0-9\-/]+)",
        r"S/REF[:#-]?\s*([A-Z0-9\-/]+)",
    ])

    fecha = parse_date_es(joined) or ""

    total = _extract_number(joined, [
        r"TOTAL(?:\s+ALBAR[ÁA]N|\s+FACTURA|\s+EUR|\s+EUROS)?\s*[:=]?\s*([0-9][0-9.,]*)",
        r"IMPORTE\s+TOTAL\s*[:=]?\s*([0-9][0-9.,]*)",
    ])

    neto = _extract_number(joined, [
        r"NETO\s+(?:COMERCIAL|TOTAL)\s*[:=]?\s*([0-9][0-9.,]*)",
    ], allow_fallback=False)

    items = [{
        "Proveedor": proveedor_detectado, "Parser": PARSER_ID,
        "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
        "Descripcion": desc, "CantidadPedida": None, "CantidadServida": None,
        "CantidadPendiente": None, "UnidadesPor": None, "PrecioUnitario": "",
        "DescuentoPct": None, "Importe": total if total is not None else None, "Pagina": page_num,
        "Pdf": "", "ParseWarn": "GENERIC_PARSER_USED"
    }]
    meta = {
        "Proveedor": proveedor_detectado, "Parser": PARSER_ID,
        "AlbaranNumero": albaran, "FechaAlbaran": fecha, "SuPedidoCodigo": su_pedido,
        "SumaImportesLineas": total if total is not None else 0.0,
        "NetoComercialPie": np.nan if neto is None else neto,
        "TotalAlbaranPie": np.nan if total is None else total
    }

    # --- DEBUG unificado ---
    try:
        from debugkit import dbg_parser_page
        dbg_parser_page(PARSER_ID, page_num,
                        header={"AlbaranNumero": "", "FechaAlbaran": "", "SuPedidoCodigo": ""},
                        items=items, meta=meta)
    except Exception:
        pass

    return items, meta


_NUM_TOKEN = re.compile(r"[0-9][0-9.,]*")


def _extract_first(text: str, patterns: list[str]) -> str:
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g is not None]
            if groups:
                return groups[0].strip()
            return m.group(0).strip()
    return ""


def _extract_number(text: str, patterns: list[str], *, allow_fallback: bool = True) -> float | None:
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            candidate = m.group(1)
            if candidate:
                val = to_float(candidate)
                if val is not None:
                    return val
    if allow_fallback:
        tail = None
        for m in _NUM_TOKEN.finditer(text):
            val = to_float(m.group(0))
            if val is not None:
                tail = val
        return tail
    return None
