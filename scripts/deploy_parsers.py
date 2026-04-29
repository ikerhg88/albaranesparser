"""
Pequeña utilidad para desplegar parsers y core en otra instalación.

Uso:
    python scripts/deploy_parsers.py --target "C:/ruta/destino"
    python scripts/deploy_parsers.py            # abrirá un selector de carpeta
    python scripts/deploy_parsers.py --dry-run  # solo muestra qué copiaría

Qué copia:
    - Carpeta `parsers/` (solo .py, ignora __pycache__ y backups *_backup_*.py)
    - common.py, main.py, config.py, settings_manager.py, debugkit.py
    - albaranes_tool/
    - requirements.txt y README_codex.md
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:  # pragma: no cover
    tk = None
    filedialog = None


ROOT = Path(__file__).resolve().parents[1]

CORE_FILES = [
    "common.py",
    "main.py",
    "config.py",
    "debugkit.py",
    "settings_manager.py",
    "requirements.txt",
    "README_codex.md",
]

PACKAGE_DIRS = [
    "albaranes_tool",
]


def select_folder() -> Path:
    if tk is None or filedialog is None:
        raise RuntimeError("Tkinter no disponible; usa --target")
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title="Selecciona carpeta de instalación destino")
    if not path:
        raise SystemExit("Operación cancelada.")
    return Path(path)


def copy_file(src: Path, dst_dir: Path, dry_run: bool):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dry_run:
        print(f"[dry-run] copiar {src} -> {dst}")
    else:
        shutil.copy2(src, dst)
        print(f"copiado {src} -> {dst}")


def copy_parsers(src_dir: Path, dst_dir: Path, dry_run: bool):
    for path in src_dir.rglob("*.py"):
        rel = path.relative_to(src_dir)
        if "__pycache__" in rel.parts:
            continue
        if "backup" in path.stem.lower():
            continue
        target = dst_dir / rel
        if dry_run:
            print(f"[dry-run] copiar {path} -> {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def copy_package_dir(src_dir: Path, dst_dir: Path, dry_run: bool):
    for path in src_dir.rglob("*.py"):
        rel = path.relative_to(src_dir)
        if "__pycache__" in rel.parts:
            continue
        target = dst_dir / rel
        if dry_run:
            print(f"[dry-run] copiar {path} -> {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def main():
    parser = argparse.ArgumentParser(description="Actualiza parsers y core en otra carpeta de instalación.")
    parser.add_argument("--target", help="Carpeta destino donde se copiarán los ficheros.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra lo que copiaría.")
    args = parser.parse_args()

    target_dir = Path(args.target) if args.target else select_folder()
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)

    # Copiar core
    for fname in CORE_FILES:
        src = ROOT / fname
        if src.exists():
            copy_file(src, target_dir, args.dry_run)
        else:
            print(f"[aviso] {fname} no encontrado en origen, se omite.")

    # Copiar parsers
    copy_parsers(ROOT / "parsers", target_dir / "parsers", args.dry_run)

    # Copiar paquetes auxiliares requeridos por OCR/parsers.
    for package in PACKAGE_DIRS:
        src_pkg = ROOT / package
        if src_pkg.exists():
            copy_package_dir(src_pkg, target_dir / package, args.dry_run)
        else:
            print(f"[aviso] {package} no encontrado en origen, se omite.")

    print("Completado." if not args.dry_run else "Dry-run completado.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
