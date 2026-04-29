"""Descarga y prepara binarios portables requeridos por OCRmyPDF en Windows."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent


TARGETS = [
    {
        "name": "pngquant",
        "url": "https://pngquant.org/pngquant-windows.zip",
        "dest": ROOT / "external_bin" / "pngquant",
        "checks": [
            ROOT / "external_bin" / "pngquant" / "pngquant.exe",
        ],
    },
    {
        "name": "ffmpeg",
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "dest": ROOT / "external_bin" / "ffmpeg",
        "checks": [
            ROOT / "external_bin" / "ffmpeg" / "bin" / "ffmpeg.exe",
            ROOT / "external_bin" / "ffmpeg" / "bin" / "ffprobe.exe",
        ],
    },
    {
        "name": "unpaper",
        "url": "https://github.com/unpaper/unpaper/releases/download/v7.0/unpaper-7.0-windows.zip",
        "dest": ROOT / "external_bin" / "unpaper",
        "checks": [
            ROOT / "external_bin" / "unpaper" / "unpaper.exe",
            ROOT / "external_bin" / "unpaper" / "libbz2-1.dll",
            ROOT / "external_bin" / "unpaper" / "libwinpthread-1.dll",
            ROOT / "external_bin" / "unpaper" / "zlib1.dll",
        ],
    },
]


def clean_directory(dest: Path) -> None:
    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        return
    for item in dest.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except FileNotFoundError:
                pass


def copy_contents(src_root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src_root.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def ensure_checks(target: dict) -> None:
    dest = target["dest"]
    for expected in target.get("checks", []):
        if expected.exists():
            continue
        found = next(dest.rglob(expected.name), None)
        if not found:
            continue
        expected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, expected)


def missing_checks(target: dict) -> list[Path]:
    checks = target.get("checks") or []
    return [p for p in checks if not p.exists()]


def download_and_prepare(target: dict) -> None:
    name = target["name"]
    dest: Path = target["dest"]

    missing_before = missing_checks(target)
    if not missing_before:
        print(f"[OK] {name} ya presente.")
        return

    try:
        print(f"[SETUP] Descargando {name} ...")
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            archive_path = tmpdir / "package.zip"
            urlretrieve(target["url"], archive_path)

            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmpdir)
            try:
                archive_path.unlink()
            except FileNotFoundError:
                pass
            clean_directory(dest)

            extracted_items = [item for item in tmpdir.iterdir()]
            if not extracted_items:
                raise RuntimeError("Archivo ZIP vacio o no esperado")

            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                src_root = extracted_items[0]
            else:
                src_root = tmpdir

            copy_contents(src_root, dest)

        ensure_checks(target)
    except Exception as exc:
        print(f"[WARN] No se pudo preparar {name}: {exc}")
        return

    remaining = missing_checks(target)
    if remaining:
        print(f"[WARN] {name} incompleto. Faltan: {', '.join(str(p) for p in remaining)}")
    else:
        print(f"[OK] {name} listo en {dest}")


def main() -> int:
    os.makedirs(ROOT / "external_bin", exist_ok=True)
    for target in TARGETS:
        download_and_prepare(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

