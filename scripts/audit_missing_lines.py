from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"\s+", " ", text)
    return text


def _norm_code(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm_text(value))


def _importe_tokens(value: object) -> list[str]:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return []
    token = f"{float(num):.2f}"
    token_comma = token.replace(".", ",")
    token_dot = token
    compact = token_comma.replace(",", "")
    return [token_comma, token_dot, compact]


def _desc_keywords(value: object) -> list[str]:
    text = _norm_text(value)
    clean = re.sub(r"[^A-Z0-9 ]+", " ", text)
    tokens = [t for t in clean.split() if len(t) >= 4 and not t.isdigit()]
    stop = {
        "PARA",
        "CON",
        "DEL",
        "DELA",
        "PENDIENTE",
        "TOTAL",
        "BASE",
    }
    out: list[str] = []
    for tok in tokens:
        if tok in stop:
            continue
        out.append(tok)
        if len(out) >= 5:
            break
    return out


def _candidate_page_files(pdf_name: str, page: object) -> list[Path]:
    if not pdf_name:
        return []
    stem = Path(pdf_name).stem
    folder = ROOT / "debug" / "pages" / stem
    if not folder.exists():
        return []
    p = pd.to_numeric(pd.Series([page]), errors="coerce").iloc[0]
    if pd.isna(p):
        return []
    pnum = int(p)
    candidates = [
        folder / f"p{pnum:02d}_lines.txt",
        folder / f"p{pnum}_lines.txt",
    ]
    return [c for c in candidates if c.exists()]


def _score_line(
    line: str,
    code: str,
    desc_keys: list[str],
    imp_tokens: list[str],
) -> tuple[int, list[str]]:
    uline = _norm_text(line)
    reasons: list[str] = []
    score = 0
    if code and code in re.sub(r"[^A-Z0-9]", "", uline):
        score += 3
        reasons.append("code")
    if desc_keys:
        hit = sum(1 for k in desc_keys if k in uline)
        if hit >= 2:
            score += 2
            reasons.append(f"desc:{hit}")
    if imp_tokens:
        if any(tok and tok in uline for tok in imp_tokens):
            score += 1
            reasons.append("importe")
    return score, reasons


def _best_match_in_file(
    file_path: Path,
    code: str,
    desc_keys: list[str],
    imp_tokens: list[str],
) -> tuple[int, str, str]:
    best_score = 0
    best_line = ""
    best_reason = ""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0, "", ""
    for raw in lines:
        score, reasons = _score_line(raw, code, desc_keys, imp_tokens)
        if score > best_score:
            best_score = score
            best_line = raw
            best_reason = ",".join(reasons)
    return best_score, best_line, best_reason


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit missing lines against OCR dumps.")
    ap.add_argument(
        "--details",
        type=Path,
        default=ROOT / "debug" / "missing_extra_compare_details.csv",
        help="CSV with missing/extra details.",
    )
    args = ap.parse_args()

    details = pd.read_csv(args.details)
    missing = details[details["Tipo"].astype(str).str.upper() == "FALTANTE"].copy()
    rows: list[dict[str, object]] = []

    for _, row in missing.iterrows():
        pdf_name = str(row.get("Pdf", "") or "")
        page = row.get("Pagina")
        code = _norm_code(row.get("Codigo"))
        desc_keys = _desc_keywords(row.get("Descripcion"))
        imp_tokens = _importe_tokens(row.get("Importe"))

        same_files = _candidate_page_files(pdf_name, page)
        same_best_score = 0
        same_best_line = ""
        same_best_reason = ""
        same_file_used = ""
        for fp in same_files:
            score, line, reason = _best_match_in_file(fp, code, desc_keys, imp_tokens)
            if score > same_best_score:
                same_best_score, same_best_line, same_best_reason = score, line, reason
                same_file_used = str(fp.relative_to(ROOT))

        status = "NOT_FOUND_OCR"
        best_scope = ""
        best_line = ""
        best_reason = ""

        if same_best_score >= 2:
            status = "FOUND_SAME_PAGE"
            best_scope = same_file_used
            best_line = same_best_line
            best_reason = same_best_reason
        else:
            if pdf_name:
                folder = ROOT / "debug" / "pages" / Path(pdf_name).stem
            else:
                folder = Path("")
            if folder.exists():
                global_score = 0
                global_line = ""
                global_reason = ""
                global_file = ""
                for fp in sorted(folder.glob("p*_lines.txt")):
                    score, line, reason = _best_match_in_file(fp, code, desc_keys, imp_tokens)
                    if score > global_score:
                        global_score, global_line, global_reason = score, line, reason
                        global_file = str(fp.relative_to(ROOT))
                if global_score >= 2:
                    status = "FOUND_OTHER_PAGE"
                    best_scope = global_file
                    best_line = global_line
                    best_reason = global_reason
                elif not same_files:
                    status = "NO_PAGE_DUMP"
            elif not same_files:
                status = "NO_PDF_DUMP"

        rows.append(
            {
                "Semana": row.get("Semana", ""),
                "Proveedor": row.get("Proveedor", ""),
                "Pdf": pdf_name,
                "Pagina": page,
                "AlbaranNumero": row.get("AlbaranNumero", ""),
                "Codigo_GT": row.get("Codigo", ""),
                "Importe_GT": row.get("Importe", ""),
                "Descripcion_GT": row.get("Descripcion", ""),
                "AuditStatus": status,
                "EvidenceFile": best_scope,
                "EvidenceReason": best_reason,
                "EvidenceLine": best_line,
            }
        )

    out = pd.DataFrame(rows)
    out_path = ROOT / "debug" / "missing_lines_audit.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    if out.empty:
        summary = pd.DataFrame(columns=["Semana", "Proveedor", "AuditStatus", "Count"])
    else:
        summary = (
            out.groupby(["Semana", "Proveedor", "AuditStatus"], dropna=False)
            .size()
            .rename("Count")
            .reset_index()
            .sort_values(["Semana", "Proveedor", "AuditStatus"])
        )
    sum_path = ROOT / "debug" / "missing_lines_audit_summary.csv"
    summary.to_csv(sum_path, index=False, encoding="utf-8-sig")

    print(summary.to_string(index=False))
    print(f"\nSaved: {out_path}")
    print(f"Saved: {sum_path}")


if __name__ == "__main__":
    main()
