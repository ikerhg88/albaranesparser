"""
Common utilities for OCR -> Excel parsers.
Uses Decimal with ROUND_HALF_UP for financial rounding.
"""
import re
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP, getcontext
import numpy as np
import pandas as pd

getcontext().prec = 16

# ------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------

def app_dir() -> Path:
    """Return the executable folder or the python file folder."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def normalize_spaces(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s).strip()

def to_float(num_str):
    if num_str is None:
        return None
    s = str(num_str).strip()
    s = re.sub(r"/[A-Za-z]*\s*$", "", s)  # remove trailing unit
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def normalize_supedido_code(value: str | None) -> str:
    """
    Normaliza códigos de 'Su Pedido' manteniendo sufijos /L,H,Y,J y corrigiendo OCR comunes.
    Acepta patrones:
      - A110226/L, H110226/Y, etc. (prefijo A/H, 6 dígitos tipo fecha, sufijo letra).
      - 26.501/04/H, 25.004/33/Y (aa.xxx/yy con sufijos opcionales /letra o -letra).
      - 25058-01-FJ (guiones en lugar de barras).
    """
    if not value:
        return ""
    raw = normalize_spaces(str(value))
    # Literales telefónicos frecuentes en TXOFRE
    if re.search(r"TELEFONO\s*LIS", raw, re.I) or re.search(r"LIS\s*TELEFONO", raw, re.I):
        return "LIS TELEFONO"
    v = raw
    v = v.replace("·", ".").replace(" ", "").upper()
    # Correcciones OCR: prefijo '1' -> 'A' cuando encaja en el patrón
    v = re.sub(r"^[1I](\d{6})(/[A-Z])?$", r"A\1\2", v)
    # Corrección '1ALL0226/L' -> 'A110226/L'
    v = re.sub(r"^1A[L1]L(\d{4})(/[A-Z])?$", r"A11\1\2", v)
    # Corrección 'ALL0226/L' (OCR se come el primer 1)
    v = re.sub(r"^A[L1]{2}(\d{4})(/[A-Z])?$", r"A11\1\2", v)

    # Patrones año.obra/tramo [/-sufijos]  e.g. 26.501/04/H o 25.004/33-Y
    if "." in v:
        # casos con tramo opcional y sufijos variados (25.077-FJ, 25.058/Y, 21.207-FJ)
        if re.match(r"^\d{2}\.\d{3}(?:[-/]\d{1,3})?(?:[-/][A-Z0-9]+)*$", v):
            return v.strip(" -:/")
        # Variante compacta sin separador intermedio: 25.62501/E
        if re.match(r"^\d{2}\.\d{4,6}(?:/[A-Z0-9]+)*$", v):
            return v.strip(" -:/")
        # si lleva punto pero no cumple el patrón, lo descartamos (evita 10.183/898)
        return ""

    # Patrones año/obra [/sufijos] sin punto (ej. 26008/07/Y, 25034/01/IA22)
    m = re.match(r"^(\d{4,6})/(\d{2})(/[A-Z0-9]+)*$", v)
    if m:
        return v.strip(" -:/")
    # Patrones con prefijo letra y guiones (A-0402226-FJ)
    if re.match(r"^[A-Z]-?\d{5,7}(?:[-/][A-Z0-9]+)*$", v):
        return v.strip(" -:/")
    # Corrección 'ALL0226/L' (OCR se come el primer 1)
    v = re.sub(r"^A[L1]{2}(\d{4})(/[A-Z])?$", r"A11\1\2", v)
    # Inserta barra antes del sufijo si falta (A110226L -> A110226/L)
    m = re.match(r"^([AH])(\d{6})([A-Z0-9]+)$", v)
    if m:
        v = f"{m.group(1)}{m.group(2)}/{m.group(3)}"
    # Variante ya con barra
    m = re.match(r"^([AH])(\d{6})/([A-Z0-9]+)$", v)
    if m:
        pref, digits, suf = m.groups()
        suf = suf if suf else ""
        v = f"{pref}{digits}/{suf}"
    # Si no encaja en ningún patrón pero sólo contiene A-Z0-9./- y longitud razonable, devuélvelo tal cual.
    if re.fullmatch(r"[A-Z0-9./-]{4,24}", v):
        return v.strip(" -:/")
    return v.strip(" -:/")

# Canonical detail columns
DETAIL_COLS = [
    "Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo",
    "Codigo", "Descripcion",
    "CantidadServida", "PrecioUnitario", "DescuentoPct", "Importe",
    "UnidadesPor",
    "Pagina", "Pdf", "ParseWarn"
]

def _to_num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None

def money_round(x, ndigits: int = 2):
    try:
        q = Decimal(10) ** -ndigits
        return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))
    except Exception:
        return x

def calc_importe(qty, price, dto=0.0, unidades_por=1):
    try:
        q = Decimal(str(qty))
        p = Decimal(str(price))
        u = Decimal(str(unidades_por if unidades_por else 1))
        d = Decimal(str(dto if dto is not None else 0))
        base = (q / u) * p
        factor = (Decimal("100") - d) / Decimal("100")
        return money_round(base * factor, 2)
    except Exception:
        return None

def fix_qty_price_import(item: dict, tol: float = 0.05, mode: str = "safe") -> dict:
    """
    Post-proceso defensivo configurable:
    - safe: ajustes minimos, no recalcula dto ni swaps agresivos.
    - aggressive: incluye heuristicas de rescate OCR.
    """
    if not isinstance(item, dict):
        return item
    qty = _to_num(item.get("CantidadServida"))
    price = _to_num(item.get("PrecioUnitario"))
    imp = _to_num(item.get("Importe"))
    imp_ocr = imp  # guarda el valor leído por OCR; no lo sobreescribimos si existe
    dto = _to_num(item.get("DescuentoPct"))
    unidades_por = _to_num(item.get("UnidadesPor")) or 1

    # Si hay UnidadesPor>1 y el importe cuadra, no toques qty/precio/dto
    if unidades_por > 1 and qty and price and imp:
        factor = (100 - (dto or 0)) / 100 if dto not in (None, 0) else 1.0
        expected = (qty / unidades_por) * price * factor
        if expected and abs(expected - imp) <= max(tol, 0.05 * abs(expected)):
            return item

    if (price is None or price == 0) and qty not in (None, 0) and imp not in (None, 0):
        price = imp / qty if qty else price
    if (qty is None or qty == 0) and price not in (None, 0) and imp not in (None, 0):
        qty = imp / price if price else qty

    if qty and price and imp:
        if qty > 10 and (dto is None or dto < 5) and abs(imp - price) <= max(tol, 0.1) * max(1, imp):
            qty = money_round(imp / price, 2)

    # Si el importe coincide con 1 unidad (con dto) pero qty es grande, reajusta qty a 1
    if qty and price and imp and qty > 1:
        unit_expected = price * ((100 - (dto or 0)) / 100 if dto is not None else 1)
        if unit_expected > 0 and abs(imp - unit_expected) <= max(tol, 0.1) * max(imp, 1):
            qty = 1.0
            imp = calc_importe(qty, price, dto, unidades_por)

    # qty desproporcionada frente a importe (ej. qty 200, precio 11, imp 21)
    if qty and price and imp:
        factor_tmp = (100 - (dto or 0)) / 100 if dto not in (None, 0) else 1.0
        expected_tmp = (qty / unidades_por) * price * factor_tmp if unidades_por else qty * price * factor_tmp
        if expected_tmp > 0 and imp > 0 and qty > 50 and price > 1 and imp < expected_tmp * 0.2:
            qty_new = (imp / (price * factor_tmp)) * (unidades_por if unidades_por else 1)
            qty = money_round(qty_new, 2)

    if qty and price and imp:
        factor = (100 - (dto or 0)) / 100 if dto not in (None, 0) else 1.0
        expected_imp_unit = price * factor
        expected_total = (qty / unidades_por) * expected_imp_unit if unidades_por else qty * expected_imp_unit
        if expected_imp_unit > 0 and expected_total > imp * 5:
            qty_new = (imp / expected_imp_unit) * (unidades_por if unidades_por else 1)
            if qty_new > 0:
                qty = money_round(qty_new, 2)
                imp = calc_importe(qty, price, dto, unidades_por)

    # Ajuste de precio si el importe cuadra y el precio difiere claramente
    if qty and imp and dto is not None and price:
        factor = (100 - dto) / 100
        if factor > 0:
            price_hat = imp * unidades_por / (qty * factor)
            if price_hat > 0:
                rel_diff = abs(price_hat - price) / max(price_hat, price, 1e-6)
                if rel_diff > max(tol, 0.05):
                    price = money_round(price_hat, 4)

    # Recalcula dto desde importe cuando el dto faltaba o es claramente incoherente
    if qty and price and imp and (dto is None or dto < 0 or dto > 80):
        expected_base = qty * price
        if expected_base > 0:
            dto_calc = 100 * (1 - (imp / expected_base))
            if 0 <= dto_calc <= 80:
                dto = round(dto_calc, 2)

    if mode == "aggressive" and qty and price and imp:
        factor = (100 - (dto or 0)) / 100 if dto not in (None, 0) else 1.0
        if factor:
            if price > 10 and qty > 5 and (imp / price) < 0.5:
                price = price / 100.0
            qty_expected = imp / (price * factor)
            if qty_expected > 0:
                if qty / qty_expected > 10 or qty_expected / max(qty, 1e-9) > 10:
                    candidates = [(price, qty_expected)]
                    for p in (price / 10.0, price / 100.0):
                        if p > 0:
                            qexp = imp / (p * factor)
                            if qexp > 0:
                                candidates.append((p, qexp))
                    chosen = min(candidates, key=lambda x: abs(x[1] - qty))
                    price, qty_expected = chosen
                if qty_expected > 0 and qty > qty_expected * (1 + tol) and abs(qty - qty_expected) > tol:
                    qty = money_round(qty_expected, 2)
        if qty > 5 and abs(imp - (qty/10)*price*factor) <= tol*max(1, imp):
            qty = qty / 10.0

    if mode == "aggressive" and dto is None and qty and price and imp:
        base = qty * price
        if base > 0:
            cand = 100 * (1 - imp / base)
            if 0 < cand < 90:
                dto = money_round(cand, 2)

    if qty and imp and price and price > 0:
        factor = (100 - (dto or 0)) / 100 if dto not in (None, 0) else 1.0
        expected_price = imp / (qty * factor) if qty and factor else None
        if expected_price and expected_price > 0 and price < expected_price * 0.5 and abs(imp - qty * price * factor) > tol * max(1, imp):
            if dto is None or dto <= 60 or mode == "aggressive":
                price = expected_price

    if qty and price and imp is None:
        imp_calc = calc_importe(qty, price, dto, unidades_por)
        if imp_calc is not None:
            imp = imp_calc

    # Solo recalculamos/ajustamos importe cuando no vino del OCR
    if imp_ocr is not None:
        imp = imp_ocr

    item["CantidadServida"] = qty
    item["PrecioUnitario"] = price
    if dto is not None:
        item["DescuentoPct"] = dto
    if imp is not None:
        item["Importe"] = imp
    item["UnidadesPor"] = unidades_por
    return item


def last_non_nan(series):
    vals = [v for v in series.values if not (isinstance(v, float) and np.isnan(v))]
    return vals[-1] if vals else np.nan


def consolidate_totals(page_meta_df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["Proveedor","Parser","AlbaranNumero","FechaAlbaran","SuPedidoCodigo"]
    if page_meta_df.empty:
        return pd.DataFrame(columns=group_cols+["SumaImportesLineas","NetoComercialPie","TotalAlbaranPie","Dif_Suma_vs_Neto","Dif_Suma_vs_Total"])
    out = (page_meta_df.groupby(group_cols, dropna=False)
                      .agg({"SumaImportesLineas":"sum","NetoComercialPie":last_non_nan,"TotalAlbaranPie":last_non_nan})
                      .reset_index())
    out["Dif_Suma_vs_Neto"]  = (pd.to_numeric(out["SumaImportesLineas"], errors="coerce") - pd.to_numeric(out["NetoComercialPie"], errors="coerce")).round(2)
    out["Dif_Suma_vs_Total"] = (pd.to_numeric(out["SumaImportesLineas"], errors="coerce") - pd.to_numeric(out["TotalAlbaranPie"], errors="coerce")).round(2)
    return out


def provider_summary(df_detail: pd.DataFrame, df_tot: pd.DataFrame) -> pd.DataFrame:
    if df_detail.empty and df_tot.empty:
        return pd.DataFrame(columns=[
            "Proveedor","Parser","#PDFs","#Paginas","#Albaranes","#Lineas",
            "Importe_lineas_sum","Neto_pie_sum","Total_pie_sum","#Lineas_con_warn","Primer_dia","Ultimo_dia"
        ])
    prov = df_detail["Proveedor"].iloc[0] if not df_detail.empty else (df_tot["Proveedor"].iloc[0] if not df_tot.empty else "")
    parser = df_detail["Parser"].iloc[0] if not df_detail.empty else (df_tot["Parser"].iloc[0] if not df_tot.empty else "")
    n_alb = df_tot[["Proveedor","AlbaranNumero"]].drop_duplicates().shape[0] if not df_tot.empty else 0
    n_lin = df_detail.shape[0]
    imp_sum = pd.to_numeric(df_detail["Importe"], errors="coerce").sum()
    neto_sum = pd.to_numeric(df_tot["NetoComercialPie"], errors="coerce").sum() if "NetoComercialPie" in df_tot else 0.0
    total_sum = pd.to_numeric(df_tot["TotalAlbaranPie"], errors="coerce").sum() if "TotalAlbaranPie" in df_tot else 0.0
    n_warn = df_detail["ParseWarn"].astype(str).replace("", np.nan).notna().sum() if "ParseWarn" in df_detail else 0
    fechas = pd.to_datetime(df_detail["FechaAlbaran"], errors="coerce", dayfirst=True)
    primer = fechas.min(); ultimo = fechas.max()
    return pd.DataFrame([{
        "Proveedor": prov, "Parser": parser,
        "#PDFs": len(df_detail["Pdf"].unique()) if "Pdf" in df_detail else None,
        "#Paginas": df_detail["Pagina"].nunique() if "Pagina" in df_detail else None,
        "#Albaranes": n_alb, "#Lineas": n_lin,
        "Importe_lineas_sum": round(imp_sum,2), "Neto_pie_sum": round(neto_sum,2), "Total_pie_sum": round(total_sum,2),
        "#Lineas_con_warn": int(n_warn),
        "Primer_dia": "" if pd.isna(primer) else primer.strftime("%d/%m/%Y"),
        "Ultimo_dia": "" if pd.isna(ultimo) else ultimo.strftime("%d/%m/%Y"),
    }])

import re as _re
def parse_date_es(s: str | None) -> str:
    if not s: return ""
    txt = s.strip()
    m = _re.search(r"(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})", txt)
    if m:
        d, mth, y = m.groups()
        if len(y)==2: y = ("20"+y) if int(y)<=69 else ("19"+y)
        return f"{int(d):02d}/{int(mth):02d}/{int(y):04d}"
    m = _re.search(r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})", txt)
    if m:
        y, mth, d = m.groups()
        return f"{int(d):02d}/{int(mth):02d}/{int(y):04d}"
    return ""
