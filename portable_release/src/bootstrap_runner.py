"""Runner combinado: instala/actualiza si falta y ejecuta el parser."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

APP_NAME = "AlbaranesParserPortable"
FIRST_RUN_SENTINEL = ".first_run_complete"
PAYLOAD_VERSION = "1.10.0+20260428.tesseract-default-menu"
PAYLOAD_ZIP = "payload/app_payload.zip"
EXTERNAL_PACK = "payload/external_bin_pack.zip"
ALLOWED_BIN_DIRS = {
    "tesseract",
    "qpdf",
    "ghostscript",
    "pngquant",
    "unpaper",
    "ffmpeg",
    "gtk",
    "GTK3-Runtime Win64",
    "jbig2",
}


def _default_data_dir() -> Path:
    env = os.environ.get("ALBARANES_DATA_DIR")
    if env:
        return Path(env).expanduser()
    exe_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    portable_candidate = exe_dir / "albaranes_data"
    if portable_candidate.exists():
        return portable_candidate
    win_local = os.environ.get("LOCALAPPDATA")
    if win_local:
        return Path(win_local) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _default_user_data_dir() -> Path:
    env = os.environ.get("ALBARANES_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "AlbaranesParser" / "data"
    return Path.home() / ".albaranesparser" / "data"


def _installed_layout_dir() -> Path | None:
    exe_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    if (exe_dir / "app" / "main.py").exists() and (exe_dir / "external_bin").exists():
        return exe_dir
    return None


def _prepend_path(entries: Iterable[Path]) -> None:
    valid = [str(p) for p in entries if p.exists()]
    if not valid:
        return
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(valid + [current])


def _resource_path(rel_path: str) -> Path:
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


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            target = Path(member)
            if ".." in target.parts:
                raise ValueError(f"Ruta sospechosa en zip: {member}")
        zf.extractall(dest)


def _ensure_payload(code_dir: Path) -> bool:
    version_file = code_dir.parent / ".payload_version"
    current_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if current_version == PAYLOAD_VERSION and (code_dir / "main.py").exists():
        return False
    if code_dir.exists():
        shutil.rmtree(code_dir, ignore_errors=True)
    code_dir.mkdir(parents=True, exist_ok=True)
    payload_zip = _resource_path(PAYLOAD_ZIP)
    if not payload_zip.exists():
        raise FileNotFoundError(f"No se encontro el payload: {payload_zip}")
    _safe_extract(payload_zip, code_dir)
    version_file.write_text(PAYLOAD_VERSION, encoding="utf-8")
    return True


def _clean_external(ext_dir: Path) -> None:
    allow = {
        "tesseract",
        "qpdf",
        "ghostscript",
        "pngquant",
        "unpaper",
        "ffmpeg",
        "gtk",
        "GTK3-Runtime Win64",
        "jbig2",
    }
    if not ext_dir.exists():
        return
    for child in ext_dir.iterdir():
        if child.name in allow:
            continue
        if any(a.lower() == child.name.lower() for a in allow):
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except Exception:
                pass


def _ensure_external_bin(ext_dir: Path) -> bool:
    pack = _resource_path(EXTERNAL_PACK)
    if not pack.exists():
        print(f"[WARN] No se encontro {pack}.")
        return False
    tmp = Path(tempfile.mkdtemp())
    try:
        _safe_extract(pack, tmp)
        candidates = []
        for path in tmp.rglob("tesseract.exe"):
            candidates.append(path.parent.parent)
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
            if item.name not in ALLOWED_BIN_DIRS:
                continue
            target = ext_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        _clean_external(ext_dir)
        print(f"[INFO] external_bin desplegado en {ext_dir}")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _external_bin_ready(ext_dir: Path) -> bool:
    # Senal minima: carpeta existente y al menos un binario base.
    return (
        ext_dir.exists()
        and (ext_dir / "tesseract" / "tesseract.exe").exists()
        and (ext_dir / "qpdf" / "bin" / "qpdf.exe").exists()
    )


def _copy_self_runner(data_dir: Path) -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        exe_path = Path(sys.executable).resolve()
        target = data_dir / "AlbaranesParser.exe"
        shutil.copy2(exe_path, target)
    except Exception:
        pass


def _main() -> int:
    installed_dir = _installed_layout_dir()
    if installed_dir is not None:
        install_dir = installed_dir
        data_dir = _default_user_data_dir()
        code_dir = install_dir / "app"
        ext_dir = install_dir / "external_bin"
        if not _external_bin_ready(ext_dir):
            print(f"[ERROR] external_bin no esta instalado en {ext_dir}")
            return 1
        if not _is_writable(data_dir):
            print(f"[ERROR] No se pudo escribir en {data_dir}")
            return 1
        os.environ.setdefault("ALBARANES_INSTALL_DIR", str(install_dir))
        os.environ.setdefault("ALBARANES_DATA_DIR", str(data_dir))
        os.environ.setdefault("ALBARANES_EXTERNAL_BIN", str(ext_dir))
        _prepend_path(
            [
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
            ]
        )
        os.chdir(data_dir)
        try:
            import importlib

            sys.path.insert(0, str(code_dir))
            main_mod = importlib.import_module("main")
            if not hasattr(main_mod, "main"):
                raise AttributeError("main.py no expone main()")
            main_mod.main()
            return 0
        except SystemExit as ex:
            return int(ex.code or 0)
        except Exception as exc:
            print(f"[FATAL] Error lanzando la aplicacion: {exc}", file=sys.stderr)
            return 1

    data_dir = _default_data_dir()
    code_dir = data_dir / "app"
    ext_dir = data_dir / "external_bin"
    marker = data_dir / FIRST_RUN_SENTINEL

    had_marker = marker.exists()
    has_main = (code_dir / "main.py").exists()
    needs_bootstrap = (not had_marker) or (not has_main)

    has_external_pack = _resource_path(EXTERNAL_PACK).exists()

    if needs_bootstrap:
        print(f"[INFO] Preparando instalacion en {data_dir}...")

    if not _is_writable(data_dir):
        print(f"[ERROR] No se pudo escribir en {data_dir}")
        return 1

    payload_updated = _ensure_payload(code_dir)
    if needs_bootstrap or payload_updated or not _external_bin_ready(ext_dir):
        if has_external_pack:
            _ensure_external_bin(ext_dir)
    else:
        _clean_external(ext_dir)

    if not _external_bin_ready(ext_dir):
        print("[ERROR] external_bin no esta instalado en esta maquina.")
        print("[ERROR] Ejecuta primero AlbaranesInstaller.exe en esta misma carpeta.")
        return 1

    if needs_bootstrap or payload_updated:
        marker.write_text("ok", encoding="utf-8")
        _copy_self_runner(data_dir)
        if needs_bootstrap and payload_updated:
            print("[INFO] Instalacion completada.")
        elif payload_updated:
            print("[INFO] Aplicacion actualizada en instalacion existente.")

    os.environ.setdefault("ALBARANES_DATA_DIR", str(data_dir))
    os.environ.setdefault("ALBARANES_EXTERNAL_BIN", str(ext_dir))

    _prepend_path(
        [
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
        ]
    )

    os.chdir(data_dir)
    if needs_bootstrap:
        print("[INFO] Primera instalacion completada, iniciando el parser...")
    try:
        import importlib

        sys.path.insert(0, str(code_dir))
        main_mod = importlib.import_module("main")
        if not hasattr(main_mod, "main"):
            raise AttributeError("main.py no expone main()")
        main_mod.main()
        return 0
    except SystemExit as ex:
        return int(ex.code or 0)
    except Exception as exc:
        print(f"[FATAL] Error lanzando la aplicacion: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
