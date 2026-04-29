"""
Quick regression checker for Semana 05.

It compares the predicted master file with the corrected ground truth and
prints per-proveedor accuracy plus a few example mismatches.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEF_PRED = ROOT / "Albaranes_Pruebas" / "SEMANA_05" / "albaranes_master_run_semana05_newparsers.xlsx"
DEF_GT = ROOT / "Albaranes_Pruebas" / "SEMANA_05" / "albaranes_master_corregido.xlsx"
OUT_DIFF = ROOT / "Albaranes_Pruebas" / "SEMANA_05" / "debug" / "diff_sem05.csv"


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    # Normaliza nombres esperados
    for col in ("UnidadesPor", "CantidadPedida", "CantidadPendiente"):
        if col not in df.columns:
            df[col] = pd.NA
    return df


def _make_key(df: pd.DataFrame) -> pd.Series:
    if "Pagina" in df.columns:
        page = pd.to_numeric(df["Pagina"], errors="coerce").fillna(0).astype(int).astype(str)
    else:
        page = "0"
    # Usa Codigo si existe; si es nan, usa una versión recortada de la descripción para evitar cartesianazos
    code_raw = df["Codigo"].astype(str)
    desc_fallback = df.get("Descripcion", pd.Series([""] * len(df))).astype(str)
    code = code_raw.mask(code_raw.str.lower() == "nan", desc_fallback.str.slice(0, 32))
    code = code.str.replace(r"\s+", " ", regex=True).str.strip()
    return (
        df["Proveedor"].astype(str).str.upper()
        + "|"
        + df["AlbaranNumero"].astype(str)
        + "|"
        + code
        + "|"
        + page
    )


def _num_equal(a, b, tol=0.02) -> bool:
    try:
        if pd.isna(a) and pd.isna(b):
            return True
        fa = float(a)
        fb = float(b)
        return abs(fa - fb) <= tol
    except Exception:
        return False


def compare(pred_path: Path, gt_path: Path, save: Optional[Path] = None) -> pd.DataFrame:
    pred = _load(pred_path)
    gt = _load(gt_path)

    pred["__key"] = _make_key(pred)
    gt["__key"] = _make_key(gt)

    gt_keep = gt[
        [
            "__key",
            "Proveedor",
            "AlbaranNumero",
            "Codigo",
            "Descripcion",
            "CantidadServida",
            "PrecioUnitario",
            "DescuentoPct",
            "Importe",
            "UnidadesPor",
        ]
    ]
    merged = pred.merge(gt_keep, on="__key", how="left", suffixes=("_pred", "_gt"))

    merged["qty_ok"] = merged.apply(
        lambda r: _num_equal(r["CantidadServida_pred"], r["CantidadServida_gt"]), axis=1
    )
    merged["price_ok"] = merged.apply(
        lambda r: _num_equal(r["PrecioUnitario_pred"], r["PrecioUnitario_gt"]), axis=1
    )
    merged["dto_ok"] = merged.apply(
        lambda r: _num_equal(r["DescuentoPct_pred"], r["DescuentoPct_gt"]), axis=1
    )
    merged["imp_ok"] = merged.apply(
        lambda r: _num_equal(r["Importe_pred"], r["Importe_gt"]), axis=1
    )
    merged["line_ok"] = merged[["qty_ok", "price_ok", "dto_ok", "imp_ok"]].all(axis=1)

    summary = (
        merged.groupby("Proveedor_pred")
        .agg(total=("line_ok", "size"), ok=("line_ok", "sum"))
        .reset_index()
    )
    summary["accuracy_pct"] = (summary["ok"] / summary["total"] * 100).round(2)
    summary = summary.rename(columns={"Proveedor_pred": "Proveedor"})

    if save:
        save.parent.mkdir(parents=True, exist_ok=True)
        merged.to_csv(save, index=False)

    return summary, merged


def main():
    ap = argparse.ArgumentParser(description="Regression checker for Semana 05.")
    ap.add_argument("--pred", type=Path, default=DEF_PRED, help="Predicted master xlsx")
    ap.add_argument("--gt", type=Path, default=DEF_GT, help="Corrected (ground truth) xlsx")
    ap.add_argument("--out", type=Path, default=OUT_DIFF, help="CSV to store detailed diff")
    args = ap.parse_args()

    summary, merged = compare(args.pred, args.gt, args.out)
    print("=== Accuracy por proveedor (linea completa) ===")
    for _, row in summary.sort_values("accuracy_pct", ascending=False).iterrows():
        print(f"{row['Proveedor']:<12} {row['ok']:>4}/{row['total']:<4}  {row['accuracy_pct']:5.2f}%")

    print("\n=== Ejemplos de discrepancias (hasta 3 por proveedor) ===")
    for prov in merged["Proveedor_pred"].dropna().unique():
        subset = merged[(merged["Proveedor_pred"] == prov) & (~merged["line_ok"])]
        if subset.empty:
            continue
        print(f"\n[{prov}]")
        for _, r in subset.head(3).iterrows():
            print(
                f"- Alb {r['AlbaranNumero_pred']} Cod {r['Codigo_pred']}: "
                f"qty {r['CantidadServida_pred']} vs {r['CantidadServida_gt']}, "
                f"price {r['PrecioUnitario_pred']} vs {r['PrecioUnitario_gt']}, "
                f"dto {r['DescuentoPct_pred']} vs {r['DescuentoPct_gt']}, "
                f"imp {r['Importe_pred']} vs {r['Importe_gt']}"
            )


if __name__ == "__main__":
    main()
