"""Aplica un paquete de parsers (zip) sobre el directorio de datos."""
from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from pathlib import Path

APP_NAME = "AlbaranesParserPortable"


def default_data_dir() -> Path:
    env = os.environ.get("ALBARANES_DATA_DIR")
    if env:
        return Path(env).expanduser()
    win_local = os.environ.get("LOCALAPPDATA")
    if win_local:
        return Path(win_local) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def apply_pack(pack_path: Path, target_dir: Path) -> None:
    if not pack_path.exists():
        raise FileNotFoundError(f"No se encontro el pack: {pack_path}")
    tmp_dir = target_dir.parent / ".tmp_parsers"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(pack_path, "r") as zf:
            zf.extractall(tmp_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in tmp_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, target_dir / item.name)
        print(f"[OK] Parsers actualizados en {target_dir}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Actualiza los parsers desde un zip")
    ap.add_argument("pack", nargs="?", help="Ruta del zip (por defecto artifacts/parsers_pack.zip)")
    ap.add_argument("--target", help="Directorio de destino (app/parsers dentro de datos)")
    args = ap.parse_args()

    base = default_data_dir()
    target = Path(args.target) if args.target else base / "app" / "parsers"
    pack = Path(args.pack) if args.pack else Path(__file__).resolve().parents[1] / "artifacts" / "parsers_pack.zip"

    apply_pack(pack, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
