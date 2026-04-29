from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PRED = {
    "SEMANA_05": "albaranes_master_run_sem05_berdin_supedido_nhc.xlsx",
    "SEMANA_06": "albaranes_master_run_sem06_berdin_supedido_nhc.xlsx",
    "SEMANA_07": "albaranes_master_run_sem07_berdin_supedido_nhc.xlsx",
}
DEFAULT_GT = "albaranes_master_corregido.xlsx"
DEFAULT_WEEKS = ["SEMANA_05", "SEMANA_06", "SEMANA_07"]


@dataclass(frozen=True)
class RunSet:
    semana: str
    pred_path: Path
    gt_path: Path


def _load_lines(path: Path) -> pd.DataFrame:
    xls = pd.ExcelFile(path)
    sheet = "Lineas" if "Lineas" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(path, sheet_name=sheet)


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def _norm_upper(value: object) -> str:
    return _norm_text(value).upper()


def _norm_importe(value: object) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return ""
    return f"{float(num):.2f}"


def _norm_qty(value: object) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return ""
    return f"{float(num):.3f}"


def _desc_hint(desc: object, code: object) -> str:
    d = _norm_upper(desc)
    d = re.sub(r"[^A-Z0-9 ]+", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    if d:
        return d[:80]
    c = _norm_upper(code)
    return c[:40]


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in (
        "Proveedor",
        "Pdf",
        "Pagina",
        "AlbaranNumero",
        "SuPedidoCodigo",
        "Codigo",
        "Descripcion",
        "CantidadServida",
        "Importe",
    ):
        if col not in out.columns:
            out[col] = ""
    out["Proveedor"] = out["Proveedor"].map(_norm_upper)
    out["Pdf"] = out["Pdf"].map(_norm_text)
    out["Pagina"] = pd.to_numeric(out["Pagina"], errors="coerce")
    out["AlbaranNumero"] = out["AlbaranNumero"].map(_norm_upper)
    out["SuPedidoCodigo"] = out["SuPedidoCodigo"].map(_norm_upper)
    out["Codigo"] = out["Codigo"].map(_norm_upper)
    out["Descripcion"] = out["Descripcion"].map(_norm_text)
    out["CantidadServida"] = pd.to_numeric(out["CantidadServida"], errors="coerce")
    out["Importe"] = pd.to_numeric(out["Importe"], errors="coerce")
    return out


def _prepare_gt(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    raw_pdf_blank = out["Pdf"].astype(str).str.strip().isin(["", "nan", "NaN"])
    raw_pag_blank = out["Pagina"].isna()
    raw_alb_blank = out["AlbaranNumero"].astype(str).str.strip().isin(["", "nan", "NaN"])
    raw_prov_blank = out["Proveedor"].astype(str).str.strip().isin(["", "nan", "NaN"])
    for col in ("Proveedor", "Pdf", "Pagina", "AlbaranNumero"):
        out.loc[out[col].astype(str).str.strip().isin(["", "nan", "NaN"]), col] = pd.NA
    out[["Proveedor", "Pdf", "Pagina", "AlbaranNumero"]] = out[
        ["Proveedor", "Pdf", "Pagina", "AlbaranNumero"]
    ].ffill()
    out["Proveedor"] = out["Proveedor"].fillna("").map(_norm_upper)
    out["Pdf"] = out["Pdf"].fillna("").map(_norm_text)
    out["Pagina"] = pd.to_numeric(out["Pagina"], errors="coerce")
    out["AlbaranNumero"] = out["AlbaranNumero"].fillna("").map(_norm_upper)
    out["_weak_location"] = raw_pdf_blank | raw_pag_blank | raw_alb_blank | raw_prov_blank
    return out


def _legacy_missing_extra(pred: pd.DataFrame, gt: pd.DataFrame) -> tuple[int, int]:
    p = pred.sort_values(["Proveedor", "Pdf", "Pagina"]).reset_index(drop=True).copy()
    g = gt.sort_values(["Proveedor", "Pdf", "Pagina"]).reset_index(drop=True).copy()
    p["idx"] = p.groupby(["Proveedor", "Pdf", "Pagina"]).cumcount()
    g["idx"] = g.groupby(["Proveedor", "Pdf", "Pagina"]).cumcount()
    m = p[["Proveedor", "Pdf", "Pagina", "idx"]].merge(
        g[["Proveedor", "Pdf", "Pagina", "idx"]],
        on=["Proveedor", "Pdf", "Pagina", "idx"],
        how="outer",
        indicator=True,
    )
    miss = int((m["_merge"] == "right_only").sum())
    extra = int((m["_merge"] == "left_only").sum())
    return miss, extra


def _add_match_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_importe_key"] = out["Importe"].map(_norm_importe)
    out["_qty_key"] = out["CantidadServida"].map(_norm_qty)
    out["_desc_hint"] = [
        _desc_hint(d, c) for d, c in zip(out["Descripcion"].tolist(), out["Codigo"].tolist())
    ]
    out["_code_key"] = [_norm_upper(c) for c in out["Codigo"].tolist()]
    weak_keys: list[tuple] = []
    strong_keys: list[tuple] = []
    alt_keys: list[tuple] = []
    for _, row in out.iterrows():
        if row["_importe_key"]:
            core = (row["Proveedor"], row["_importe_key"])
            alt_key = ()
        else:
            # Sin importe, usamos Albaran+Codigo para mantener cardinalidad de líneas.
            # Si el código falla por OCR, el fallback por descripción (alt_key) cubre el caso.
            if row["_code_key"]:
                core = (
                    row["Proveedor"],
                    row["AlbaranNumero"],
                    row["_code_key"],
                )
            else:
                core = (
                    row["Proveedor"],
                    row["AlbaranNumero"],
                    row["_desc_hint"],
                )
            alt_key = (
                row["Proveedor"],
                row["_desc_hint"],
            )
        weak_keys.append(core)
        strong_keys.append(
            (
                row["Proveedor"],
                row["Pdf"],
                int(row["Pagina"]) if pd.notna(row["Pagina"]) else -1,
            )
            + core
        )
        alt_keys.append(alt_key)
    out["_weak_key"] = weak_keys
    out["_strong_key"] = strong_keys
    out["_alt_key"] = alt_keys
    return out


def _choose_match(candidates: list[int], unmatched_gt: set[int]) -> int | None:
    for idx in candidates:
        if idx in unmatched_gt:
            return idx
    return None


def _robust_match(pred: pd.DataFrame, gt: pd.DataFrame) -> tuple[list[int], list[int]]:
    gt = gt.copy()
    pred = pred.copy()
    strong_map: dict[tuple, list[int]] = {}
    weak_map: dict[tuple, list[int]] = {}
    alt_map: dict[tuple, list[int]] = {}
    for gidx, row in gt.iterrows():
        strong_map.setdefault(row["_strong_key"], []).append(gidx)
        weak_map.setdefault(row["_weak_key"], []).append(gidx)
        if row["_alt_key"]:
            alt_map.setdefault(row["_alt_key"], []).append(gidx)

    unmatched_gt: set[int] = set(gt.index.tolist())
    extra_pred: list[int] = []
    for pidx, prow in pred.iterrows():
        gidx = _choose_match(strong_map.get(prow["_strong_key"], []), unmatched_gt)
        if gidx is None:
            gidx = _choose_match(weak_map.get(prow["_weak_key"], []), unmatched_gt)
        if gidx is None and prow["_alt_key"]:
            gidx = _choose_match(alt_map.get(prow["_alt_key"], []), unmatched_gt)
        if gidx is None:
            extra_pred.append(pidx)
            continue
        unmatched_gt.discard(gidx)
    missing_gt = sorted(unmatched_gt)
    return missing_gt, extra_pred


def _dedupe_gt_eval(gt: pd.DataFrame) -> pd.DataFrame:
    # En algunos GT corregidos quedan filas duplicadas con el mismo contenido clave
    # (normalmente tras correcciones manuales de codigo). Para no inflar "faltantes",
    # se colapsan por firma operativa.
    subset_with_importe = [
        "Proveedor",
        "Pdf",
        "Pagina",
        "AlbaranNumero",
        "_importe_key",
        "_desc_hint",
    ]
    with_importe = gt[gt["_importe_key"] != ""].drop_duplicates(
        subset=subset_with_importe, keep="last"
    )
    without_importe = gt[gt["_importe_key"] == ""]
    return (
        pd.concat([with_importe, without_importe], axis=0)
        .sort_index()
        .copy()
    )


def _build_runs(
    weeks: list[str],
    root: Path,
    pred_override: dict[str, str] | None,
    pred_template: str | None,
) -> list[RunSet]:
    runs: list[RunSet] = []
    for week in weeks:
        pred_name = (pred_override or {}).get(week)
        if not pred_name and pred_template:
            sem = week.split("_")[-1]
            pred_name = pred_template.format(week=week, sem=sem)
        if not pred_name:
            pred_name = DEFAULT_PRED.get(week)
        if not pred_name:
            raise ValueError(f"No pred file configured for {week}")
        runs.append(
            RunSet(
                semana=week,
                pred_path=root / week / pred_name,
                gt_path=root / week / DEFAULT_GT,
            )
        )
    return runs


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compare missing/extra lines: legacy idx vs robust key matching."
    )
    ap.add_argument("--root", type=Path, default=ROOT / "Albaranes_Pruebas")
    ap.add_argument("--weeks", nargs="+", default=DEFAULT_WEEKS)
    ap.add_argument(
        "--pred-template",
        default="",
        help="Template filename for prediction per week (use {sem} and/or {week}).",
    )
    args = ap.parse_args()

    runs = _build_runs(
        args.weeks,
        args.root,
        pred_override=None,
        pred_template=(args.pred_template or None),
    )

    summary_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    provider_rows: list[dict[str, object]] = []

    for run in runs:
        pred = _add_match_keys(_normalize_frame(_load_lines(run.pred_path)))
        gt = _add_match_keys(_prepare_gt(_normalize_frame(_load_lines(run.gt_path))))
        gt = _dedupe_gt_eval(gt)

        legacy_miss, legacy_extra = _legacy_missing_extra(pred, gt)
        robust_missing_idx, robust_extra_idx = _robust_match(pred, gt)
        robust_miss = len(robust_missing_idx)
        robust_extra = len(robust_extra_idx)

        summary_rows.append(
            {
                "Semana": run.semana,
                "Legacy_Faltan": legacy_miss,
                "Legacy_Extras": legacy_extra,
                "Robust_Faltan": robust_miss,
                "Robust_Extras": robust_extra,
                "Delta_Faltan": robust_miss - legacy_miss,
                "Delta_Extras": robust_extra - legacy_extra,
            }
        )

        for gidx in robust_missing_idx:
            row = gt.loc[gidx]
            detail_rows.append(
                {
                    "Semana": run.semana,
                    "Tipo": "FALTANTE",
                    "Proveedor": row["Proveedor"],
                    "Pdf": row["Pdf"],
                    "Pagina": row["Pagina"],
                    "AlbaranNumero": row["AlbaranNumero"],
                    "SuPedidoCodigo": row["SuPedidoCodigo"],
                    "Importe": row["Importe"],
                    "Codigo": row["Codigo"],
                    "Descripcion": row["Descripcion"],
                    "WeakLocationGT": bool(row.get("_weak_location", False)),
                }
            )
        for pidx in robust_extra_idx:
            row = pred.loc[pidx]
            detail_rows.append(
                {
                    "Semana": run.semana,
                    "Tipo": "EXTRA",
                    "Proveedor": row["Proveedor"],
                    "Pdf": row["Pdf"],
                    "Pagina": row["Pagina"],
                    "AlbaranNumero": row["AlbaranNumero"],
                    "SuPedidoCodigo": row["SuPedidoCodigo"],
                    "Importe": row["Importe"],
                    "Codigo": row["Codigo"],
                    "Descripcion": row["Descripcion"],
                    "WeakLocationGT": False,
                }
            )

        missing_set = set(robust_missing_idx)
        extra_set = set(robust_extra_idx)
        providers = sorted(set(gt["Proveedor"].tolist()) | set(pred["Proveedor"].tolist()))
        for prov in providers:
            gt_idx = set(gt.index[gt["Proveedor"] == prov].tolist())
            pred_idx = set(pred.index[pred["Proveedor"] == prov].tolist())
            provider_rows.append(
                {
                    "Semana": run.semana,
                    "Proveedor": prov,
                    "GT_Lineas": len(gt_idx),
                    "Pred_Lineas": len(pred_idx),
                    "Robust_Faltan": len(gt_idx & missing_set),
                    "Robust_Extras": len(pred_idx & extra_set),
                }
            )

    summary_df = pd.DataFrame(summary_rows).sort_values("Semana").reset_index(drop=True)
    detail_df = pd.DataFrame(detail_rows)
    provider_df = pd.DataFrame(provider_rows).sort_values(["Semana", "Proveedor"]).reset_index(drop=True)

    out_dir = ROOT / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "missing_extra_compare_summary.csv"
    detail_path = out_dir / "missing_extra_compare_details.csv"
    provider_path = out_dir / "missing_extra_compare_by_provider.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    provider_df.to_csv(provider_path, index=False, encoding="utf-8-sig")

    print(summary_df.to_string(index=False))
    print("\nPor proveedor:")
    print(provider_df.to_string(index=False))
    print(f"\nSaved: {summary_path}")
    print(f"Saved: {detail_path}")
    print(f"Saved: {provider_path}")


if __name__ == "__main__":
    main()
