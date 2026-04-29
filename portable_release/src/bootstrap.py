"""Lanzador portable para Albaranes Parser.

Se encarga de:
- Extraer el payload de codigo/parsers al directorio de datos (persistente).
- Extraer los binarios externos (Tesseract, qpdf, Ghostscript...) desde el pack incluido.
- Ajustar `sys.path` y el directorio de trabajo para que todo funcione tanto congelado (.exe) como en modo script.

El entrypoint de PyInstaller debe ser este fichero.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

# --- Dependencias para PyInstaller (no se ejecutan en runtime) ---
# PyInstaller solo ve este script; para que arrastre las libs pesadas
# declaramos imports falsos dentro de este bloque.
if False:  # pragma: no cover
    import pandas  # noqa: F401
    import numpy  # noqa: F401
    import pdfplumber  # noqa: F401
    import ocrmypdf  # noqa: F401
    import torch  # noqa: F401
    import torchvision  # noqa: F401
    import torchaudio  # noqa: F401
    import cv2  # noqa: F401
    import PIL  # noqa: F401
    import pypdfium2  # noqa: F401
    import doctr  # noqa: F401


APP_NAME = "AlbaranesParserPortable"
PAYLOAD_VERSION = "2026-02-19-fix16"
PAYLOAD_ZIP = "payload/app_payload.zip"
EXTERNAL_PACK = "payload/external_bin_pack.zip"
FIRST_RUN_SENTINEL = ".first_run_complete"


def _resource_path(rel_path: str) -> Path:
    """Ruta a un recurso empacado (funciona en .exe y en modo script)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel_path


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _default_data_dir() -> Path:
    env = os.environ.get("ALBARANES_DATA_DIR")
    if env:
        return Path(env).expanduser()

    exe_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    portable_candidate = exe_dir / "albaranes_data"
    if _is_writable(portable_candidate):
        return portable_candidate

    win_local = os.environ.get("LOCALAPPDATA")
    if win_local:
        candidate = Path(win_local) / APP_NAME
        if _is_writable(candidate):
            return candidate

    fallback = Path.home() / f".{APP_NAME.lower()}"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            target = Path(member)
            if ".." in target.parts:
                raise ValueError(f"Ruta sospechosa en zip: {member}")
        zf.extractall(dest)


def _ensure_payload(code_dir: Path) -> None:
    version_file = code_dir.parent / ".payload_version"
    current_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if current_version == PAYLOAD_VERSION and (code_dir / "main.py").exists():
        return

    if code_dir.exists():
        shutil.rmtree(code_dir, ignore_errors=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    payload_zip = _resource_path(PAYLOAD_ZIP)
    if not payload_zip.exists():
        raise FileNotFoundError(f"No se encontro el payload: {payload_zip}")
    _safe_extract(payload_zip, code_dir)
    version_file.write_text(PAYLOAD_VERSION, encoding="utf-8")


def _ensure_external_bin(ext_dir: Path) -> None:
    if (ext_dir / "tesseract").exists() and (ext_dir / "ghostscript").exists():
        return
    pack = _resource_path(EXTERNAL_PACK)
    if not pack.exists():
        print(f"[WARN] No se encontro {pack}. Usa external_bin existente si lo tienes cerca del .exe.")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        _safe_extract(pack, tmp)
        # Identifica la primera carpeta que contenga tesseract.exe o qpdf/ghostscript
        candidates = []
        for path in tmp.rglob("tesseract.exe"):
            candidates.append(path.parent.parent)  # external_bin/tesseract
        for path in tmp.rglob("qpdf.exe"):
            candidates.append(path.parent.parent)
        for path in tmp.rglob("gswin64c.exe"):
            candidates.append(path.parent.parent)
        root = None
        for cand in candidates:
            if (cand / "tesseract").exists() or (cand / "qpdf").exists() or (cand / "ghostscript").exists():
                root = cand
                break
        if root is None and (tmp / "external_bin").exists():
            root = tmp / "external_bin"
        if root is None:
            root = tmp

        if ext_dir.exists():
            shutil.rmtree(ext_dir, ignore_errors=True)
        ext_dir.mkdir(parents=True, exist_ok=True)

        for item in root.iterdir():
            target = ext_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        print(f"[INFO] external_bin desplegado en {ext_dir}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prepend_path(entries: Iterable[Path]) -> None:
    valid = [str(p) for p in entries if p.exists()]
    if not valid:
        return
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(valid + [current])


def _bootstrap() -> int:
    data_dir = _default_data_dir()
    code_dir = data_dir / "app"
    ext_dir = data_dir / "external_bin"

    data_dir.mkdir(parents=True, exist_ok=True)
    _ensure_payload(code_dir)
    _ensure_external_bin(ext_dir)

    first_run_marker = data_dir / FIRST_RUN_SENTINEL
    if not first_run_marker.exists():
        first_run_marker.write_text("ok", encoding="utf-8")
        print(f"[INFO] Instalacion inicial completada en {data_dir}")
        print("[INFO] Vuelve a ejecutar el .exe para comenzar a procesar PDFs.")
        return 0

    sys.path.insert(0, str(code_dir))
    os.chdir(data_dir)

    _prepend_path([
        ext_dir / "tesseract",
        ext_dir / "tesseract" / "tessdata",
        ext_dir / "qpdf" / "bin",
        ext_dir / "ghostscript" / "bin",
        ext_dir / "pngquant",
        ext_dir / "unpaper",
        ext_dir / "ffmpeg" / "bin",
        ext_dir / "gtk" / "bin",
        ext_dir / "GTK3-Runtime Win64" / "bin",
        ext_dir / "jbig2",
    ])

    os.environ.setdefault("ALBARANES_DATA_DIR", str(data_dir))
    os.environ.setdefault("ALBARANES_EXTERNAL_BIN", str(ext_dir))

    try:
        import importlib

        main_mod = importlib.import_module("main")
        if not hasattr(main_mod, "main"):
            raise AttributeError("main.py no expone main()")
        main_mod.main()
        return 0
    except SystemExit as ex:
        return int(ex.code or 0)
    except Exception as exc:  # pragma: no cover - solo runtime
        print(f"[FATAL] Error lanzando la aplicacion: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_bootstrap())
