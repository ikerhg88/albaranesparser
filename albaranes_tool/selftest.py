from __future__ import annotations

import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from PIL import Image, ImageDraw


def _now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _win_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    kwargs: dict = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    except Exception:
        pass
    return kwargs


def _run_cmd(cmd: list[str], timeout: int = 30) -> dict:
    started = time.time()
    try:
        cp = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            **_win_subprocess_kwargs(),
        )
        return {
            "cmd": cmd,
            "ok": cp.returncode == 0,
            "returncode": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "duration_seconds": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {
            "cmd": cmd,
            "ok": False,
            "exception": repr(exc),
            "traceback": traceback.format_exc(),
            "duration_seconds": round(time.time() - started, 3),
        }


def _write_raw_pdf(path: Path, lines: list[str]) -> None:
    """Create a tiny text PDF without third-party PDF writer dependencies."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_lines = ["BT", "/F1 10 Tf", "50 790 Td", "12 TL"]
    for line in lines:
        content_lines.append(f"({esc(line)}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{idx} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref_at = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(data))


def _create_tesseract_probe_image(path: Path) -> str:
    expected = "ALBARAN TEST 261234567 IMPORTE 12,34"
    img = Image.new("RGB", (1200, 220), "white")
    draw = ImageDraw.Draw(img)
    draw.text((35, 70), expected, fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return expected


def _create_pipeline_probe_pdf(path: Path) -> dict:
    expected = {
        "Proveedor": "ALKAIN",
        "AlbaranNumero": "261234567",
        "SuPedidoCodigo": "A010426",
        "Importe": 12.34,
    }
    lines = [
        "ALKAIN ASTIGARRAGA",
        "ALBARAN",
        "19183 - LOYOLA NORTE, S.A.",
        "SUMINISTRADO en: ASTIGARRAGA",
        "Telefono: 943557900",
        "FECHA ALBARAN ATENDIDO POR HOJA",
        "01/04/26 261234567 TEST OPERADOR - 943642025 - test@alkain.com 1 / 1",
        "VUESTRO PEDIDO A010426",
        "ARTICULO DESCRIPCION CANTIDAD PRECIO IMPORTE",
        "123456 TEST SELFTEST MATERIAL 2,00 PZA 6,1700 12,34",
        "ANTICIPO PENDIENTE BASE IMPONIBLE IMPORTE IVA IMPORTE TOTAL",
        "12,34 EUR 12,34 EUR 21,00 % 2,59 EUR 14,93 EUR",
    ]
    _write_raw_pdf(path, lines)
    return expected


def _package_probe(name: str) -> dict:
    try:
        mod = __import__(name)
        return {
            "name": name,
            "ok": True,
            "version": getattr(mod, "__version__", ""),
            "file": getattr(mod, "__file__", ""),
        }
    except Exception as exc:
        return {"name": name, "ok": False, "error": repr(exc)}


def _classify_optional_ocr(config: dict | None) -> dict:
    packages = {pkg["name"]: pkg for pkg in (
        _package_probe("ocrmypdf"),
        _package_probe("doctr"),
        _package_probe("torch"),
    )}
    ocr_cfg = ((config or {}).get("OCR_CONFIG") or {})
    return {
        "production_engine": "tesseract",
        "experimental_engines": {
            "ocrmypdf": {
                "configured_enabled": bool((ocr_cfg.get("ocrmypdf") or {}).get("enabled", False)),
                "installed": bool(packages["ocrmypdf"].get("ok")),
                "status": "available_experimental" if packages["ocrmypdf"].get("ok") else "not_installed",
                "note": "Requires OCRmyPDF Python package plus external binaries such as qpdf/Ghostscript/Tesseract.",
            },
            "doctr": {
                "configured_enabled": bool((ocr_cfg.get("doctr") or {}).get("enabled", False)),
                "installed": bool(packages["doctr"].get("ok")),
                "torch_installed": bool(packages["torch"].get("ok")),
                "status": "available_experimental" if packages["doctr"].get("ok") else "not_installed",
                "note": "Requires python-doctr, PyTorch and model files; not part of the validated Windows release.",
            },
        },
    }


def _collect_environment(base_dir: Path, config: dict | None) -> dict:
    env_keys = [
        "ALBARANES_DATA_DIR",
        "PATH",
        "PYTHONPATH",
        "TESSDATA_PREFIX",
        "OCRMYPDF_TESSERACT",
        "LOCALAPPDATA",
    ]
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_dir": str(base_dir),
        "cwd": str(Path.cwd()),
        "sys_executable": sys.executable,
        "sys_frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "environment": {key: os.environ.get(key, "") for key in env_keys},
        "config_ocr": (config or {}).get("OCR_CONFIG", {}),
        "packages": [
            _package_probe(name)
            for name in ("pandas", "numpy", "pdfplumber", "PIL", "pypdfium2", "cv2", "torch", "doctr", "ocrmypdf")
        ],
        "optional_ocr": _classify_optional_ocr(config),
    }


def _resolve_tesseract(config: dict | None) -> dict:
    try:
        from albaranes_tool.ocr_stage import _resolve_tesseract_path

        tess_cfg = ((config or {}).get("OCR_CONFIG") or {}).get("tesseract") or {}
        cmd = tess_cfg.get("cmd")
        path = _resolve_tesseract_path(cmd)
        return {"ok": True, "path": path, "configured_cmd": cmd}
    except Exception as exc:
        return {
            "ok": False,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "configured_cmd": (((config or {}).get("OCR_CONFIG") or {}).get("tesseract") or {}).get("cmd"),
        }


def _test_tesseract(report_dir: Path, config: dict | None) -> dict:
    result: dict[str, Any] = {"ok": False}
    resolved = _resolve_tesseract(config)
    result["resolve"] = resolved
    if not resolved.get("ok"):
        return result

    tess = resolved["path"]
    result["version"] = _run_cmd([tess, "--version"], timeout=20)
    result["languages"] = _run_cmd([tess, "--list-langs"], timeout=20)

    image_path = report_dir / "fixtures" / "tesseract_probe.png"
    expected = _create_tesseract_probe_image(image_path)
    ocr = _run_cmd([tess, str(image_path), "stdout", "-l", "spa+eng", "--psm", "6"], timeout=30)
    result["probe_image"] = str(image_path)
    result["expected_text"] = expected
    result["ocr"] = ocr
    compact_stdout = "".join(ch for ch in (ocr.get("stdout") or "").upper() if ch.isalnum())
    result["text_match"] = "261234567" in compact_stdout and "1234" in compact_stdout
    result["ok"] = bool(result["version"].get("ok") and result["languages"].get("ok") and ocr.get("ok") and result["text_match"])
    return result


def _test_pipeline(report_dir: Path, run_pipeline_fn: Callable[..., dict]) -> dict:
    result: dict[str, Any] = {"ok": False}
    input_dir = report_dir / "fixtures" / "pipeline_pdf"
    input_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = input_dir / "selftest_alkain.pdf"
    expected = _create_pipeline_probe_pdf(pdf_path)
    out_xlsx = report_dir / "pipeline_selftest_output.xlsx"

    started = time.time()
    try:
        run_summary = run_pipeline_fn(input_dir, out_xlsx, recursive=False)
        result["run_summary"] = run_summary
        result["duration_seconds"] = round(time.time() - started, 3)
        result["pdf"] = str(pdf_path)
        result["output_xlsx"] = str(out_xlsx)
        result["expected"] = expected
        if not out_xlsx.exists():
            result["error"] = "No se genero el Excel de salida."
            return result
        df = pd.read_excel(out_xlsx)
        result["rows"] = int(len(df))
        result["columns"] = list(df.columns)
        records = df.to_dict(orient="records")
        result["records"] = records[:10]
        if df.empty:
            result["error"] = "El Excel de salida no contiene filas."
            return result
        row = df.iloc[0].to_dict()
        checks = {
            "Proveedor": str(row.get("Proveedor", "")).upper() == expected["Proveedor"],
            "AlbaranNumero": str(row.get("AlbaranNumero", "")).replace(".0", "") == expected["AlbaranNumero"],
            "SuPedidoCodigo": str(row.get("SuPedidoCodigo", "")).upper().replace("-", "") == expected["SuPedidoCodigo"],
            "Importe": abs(float(row.get("Importe", 0) or 0) - expected["Importe"]) < 0.01,
        }
        result["checks"] = checks
        result["ok"] = all(checks.values())
        return result
    except Exception as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
        result["duration_seconds"] = round(time.time() - started, 3)
        return result


def _write_report_files(report_dir: Path, report: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(_json_safe(report), ensure_ascii=False, indent=2)
    (report_dir / "installation_selftest_report.json").write_text(
        json_text,
        encoding="utf-8",
    )

    lines = []
    lines.append(f"ALBARANES INSTALLATION SELFTEST - {'OK' if report.get('ok') else 'FAIL'}")
    lines.append(f"Report dir: {report_dir}")
    lines.append("")
    lines.append("[Environment]")
    env = report.get("environment", {})
    lines.append(f"Python: {env.get('python')}")
    lines.append(f"Executable: {env.get('sys_executable')}")
    lines.append(f"Platform: {env.get('platform')}")
    lines.append("")
    lines.append("[Tesseract]")
    tess = report.get("tesseract", {})
    lines.append(f"OK: {tess.get('ok')}")
    lines.append(f"Path: {(tess.get('resolve') or {}).get('path')}")
    if not tess.get("ok"):
        lines.append(f"Error: {(tess.get('resolve') or {}).get('error') or (tess.get('ocr') or {}).get('stderr')}")
    lines.append("")
    lines.append("[Optional OCR Engines]")
    optional = ((report.get("environment") or {}).get("optional_ocr") or {}).get("experimental_engines") or {}
    for name, info in optional.items():
        lines.append(
            f"{name}: installed={info.get('installed')} configured_enabled={info.get('configured_enabled')} status={info.get('status')}"
        )
    lines.append("")
    lines.append("[Pipeline]")
    pipe = report.get("pipeline", {})
    lines.append(f"OK: {pipe.get('ok')}")
    lines.append(f"Output: {pipe.get('output_xlsx')}")
    if pipe.get("checks"):
        lines.append(f"Checks: {pipe.get('checks')}")
    if not pipe.get("ok"):
        lines.append(f"Error: {pipe.get('error')}")
    lines.append("")
    lines.append("[Artifacts]")
    for artifact in report.get("artifacts", []):
        lines.append(f"- {artifact}")
    txt_text = "\n".join(lines)
    (report_dir / "installation_selftest_report.txt").write_text(txt_text, encoding="utf-8")

    packages = (report.get("environment") or {}).get("packages") or []
    with (report_dir / "packages.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["name", "ok", "version", "file", "error"])
        writer.writeheader()
        for pkg in packages:
            writer.writerow({key: pkg.get(key, "") for key in ("name", "ok", "version", "file", "error")})

    latest_dir = report_dir.parent
    try:
        (latest_dir / "ULTIMO_DIAGNOSTICO.txt").write_text(txt_text, encoding="utf-8")
        (latest_dir / "ULTIMO_DIAGNOSTICO.json").write_text(json_text, encoding="utf-8")
        (latest_dir / "ULTIMA_CARPETA_DIAGNOSTICO.txt").write_text(str(report_dir), encoding="utf-8")
    except Exception:
        pass


def run_installation_selftest(
    *,
    base_dir: Path,
    run_pipeline_fn: Callable[..., dict],
    config: dict | None = None,
    output_dir: Path | None = None,
    keep_artifacts: bool = True,
) -> dict:
    base_dir = Path(base_dir)
    report_dir = Path(output_dir) if output_dir else base_dir / "debug" / "installation_selftest" / _now_stamp()
    report_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "ok": False,
        "report_dir": str(report_dir),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keep_artifacts": keep_artifacts,
    }
    try:
        report["environment"] = _collect_environment(base_dir, config)
        report["tesseract"] = _test_tesseract(report_dir, config)
        report["pipeline"] = _test_pipeline(report_dir, run_pipeline_fn)
        report["ok"] = bool(report["tesseract"].get("ok") and report["pipeline"].get("ok"))
    except Exception as exc:
        report["fatal_error"] = repr(exc)
        report["fatal_traceback"] = traceback.format_exc()
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        report["artifacts"] = [str(path) for path in sorted(report_dir.rglob("*")) if path.is_file()]
        _write_report_files(report_dir, report)
        if not keep_artifacts:
            fixtures = report_dir / "fixtures"
            if fixtures.exists():
                shutil.rmtree(fixtures, ignore_errors=True)
    return report
