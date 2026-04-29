"""Construye los artefactos portables (payload, pack de parsers y spec de PyInstaller).

Se deja listo:
- payload/app_payload.zip   -> codigo + parsers + herramientas
- payload/external_bin_pack.zip (copiado desde external_bin/pack.zip)
- artifacts/parsers_pack.zip -> solo parsers, para actualizaciones rapidas
- albaranes_portable.spec    -> spec para `pyinstaller --clean albaranes_portable.spec`
"""
from __future__ import annotations

import shutil
import sys
import zipfile
import json
from pathlib import Path
from typing import Iterable

PORTABLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PORTABLE_DIR.parent
PAYLOAD_DIR = PORTABLE_DIR / "payload"
ARTIFACTS_DIR = PORTABLE_DIR / "artifacts"
PAYLOAD_ZIP = PAYLOAD_DIR / "app_payload.zip"
PARSERS_PACK = ARTIFACTS_DIR / "parsers_pack.zip"
EXTERNAL_PACK_SRC = REPO_ROOT / "external_bin" / "pack_clean.zip"
EXTERNAL_PACK_DST = PAYLOAD_DIR / "external_bin_pack.zip"
SPEC_RUNNER = PORTABLE_DIR / "albaranes_runner.spec"
SPEC_INSTALLER = PORTABLE_DIR / "albaranes_installer.spec"
APP_VERSION = "1.10.0"
BUILD_ID = "20260428.1000"
PAYLOAD_VERSION = "1.10.0+20260428.tesseract-default-menu"

CORE_FILES = [
    "main.py",
    "config.py",
    "common.py",
    "debugkit.py",
    "settings_manager.py",
]

TOOL_FILES = [
    "albaranes_tool/__init__.py",
    "albaranes_tool/ocr_stage.py",
    "albaranes_tool/gui_app.py",
    "albaranes_tool/selftest.py",
]

RUNNER_DEPENDENCIES = [
    "pandas",
    "numpy",
    "pdfplumber",
    "cv2",
    "PIL",
    "pypdfium2",
    "tkinter",
]

RUNNER_EXE = PORTABLE_DIR / "dist" / "AlbaranesParser.exe"


def _valid_parser_files(parser_dir: Path) -> list[Path]:
    out: list[Path] = []
    for path in parser_dir.glob("*.py"):
        name = path.name.lower()
        if "backup" in name or name.endswith(".bak"):
            continue
        out.append(path)
    return out


def _zip_files(zip_path: Path, pairs: Iterable[tuple[Path, str]]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("VERSION", PAYLOAD_VERSION)
        zf.writestr(
            "VERSION.json",
            json.dumps(
                {
                    "app_name": "Albaranes Parser",
                    "app_id": "AlbaranesParser",
                    "app_version": APP_VERSION,
                    "build_id": BUILD_ID,
                    "payload_version": PAYLOAD_VERSION,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        for src, arc in pairs:
            zf.write(src, arcname=arc)


def build_payload() -> Path:
    files: list[tuple[Path, str]] = []
    for rel in CORE_FILES + TOOL_FILES:
        src = REPO_ROOT / rel
        if not src.exists():
            raise FileNotFoundError(f"No se encuentra {src}")
        files.append((src, rel.replace("\\", "/")))

    parser_dir = REPO_ROOT / "parsers"
    for parser in _valid_parser_files(parser_dir):
        files.append((parser, f"parsers/{parser.name}"))

    _zip_files(PAYLOAD_ZIP, files)
    print(f"[OK] Payload generado: {PAYLOAD_ZIP}")
    return PAYLOAD_ZIP


def build_parsers_pack() -> Path:
    parser_dir = REPO_ROOT / "parsers"
    files = [(p, p.name) for p in _valid_parser_files(parser_dir)]
    _zip_files(PARSERS_PACK, files)
    print(f"[OK] Pack de parsers generado: {PARSERS_PACK}")
    return PARSERS_PACK


def copy_external_pack() -> Path | None:
    if not EXTERNAL_PACK_SRC.exists():
        print(f"[WARN] No se encontro {EXTERNAL_PACK_SRC} (se omitira en el bundle).")
        return None
    EXTERNAL_PACK_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXTERNAL_PACK_SRC, EXTERNAL_PACK_DST)
    print(f"[OK] Copiado external_bin pack: {EXTERNAL_PACK_DST}")
    return EXTERNAL_PACK_DST


def _build_spec(
    spec_path: Path,
    entry_script: str,
    exe_name: str,
    include_payload: bool,
    include_external: bool,
    console: bool,
    hint_dependencies: list[str] | None = None,
) -> Path:
    deps = hint_dependencies or []
    datas: list[str] = []
    if include_payload:
        datas.append(f"(str(payload_dir / 'app_payload.zip'), 'payload')")
    if include_external:
        datas.append(f"(str(payload_dir / 'external_bin_pack.zip'), 'payload')")
    if exe_name == "AlbaranesInstaller" and RUNNER_EXE.exists():
        datas.append(f"(str(here / 'dist' / 'AlbaranesParser.exe'), 'payload')")

    collect_list = ",\n    ".join(f"'{mod}'" for mod in deps)
    datas_list = ", ".join(datas) if datas else ""
    collect_loop = ""
    if deps:
        collect_loop = f"""
for mod in [{collect_list}]:
    mod_datas, mod_bins, mod_hidden = collect_all(mod)
    datas += mod_datas
    binaries += mod_bins
    hiddenimports += mod_hidden
"""
    spec = f"""# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all

here = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
payload_dir = here / "payload"
block_cipher = None

datas = [
    {datas_list}
]

binaries = []
hiddenimports = [
    {collect_list}
]
{collect_loop}

a = Analysis(
    ['src/{entry_script}'],
    pathex=[str(here / 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{exe_name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console={str(console)},
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
"""
    spec_path.write_text(spec, encoding="utf-8")
    print(f"[OK] Spec escrita en {spec_path}")
    return spec_path


def main() -> int:
    payload = build_payload()
    parsers_pack = build_parsers_pack()
    external = copy_external_pack()
    _build_spec(
        SPEC_INSTALLER,
        entry_script="bootstrap_installer.py",
        exe_name="AlbaranesInstaller",
        include_payload=True,
        include_external=bool(external),
        console=False,
        hint_dependencies=[],
    )
    _build_spec(
        SPEC_RUNNER,
        entry_script="bootstrap_runner.py",
        exe_name="AlbaranesParser",
        include_payload=True,
        include_external=False,
        console=False,
        hint_dependencies=RUNNER_DEPENDENCIES,
    )

    print("\nSiguiente paso para generar los .exe (requiere PyInstaller en el entorno activo):")
    print(f"  pyinstaller --clean {SPEC_INSTALLER.name}")
    print(f"  pyinstaller --clean {SPEC_RUNNER.name}")
    print("Quedaran en portable_release/dist/AlbaranesInstaller.exe y AlbaranesParser.exe\n")
    print("Para actualizar solo los parsers en otra maquina:")
    print(f"  - Copia {parsers_pack} y descomprime sobre %LOCALAPPDATA%/AlbaranesParserPortable/app/parsers")
    print("    o sobre la carpeta 'albaranes_data/app/parsers' junto al .exe si usas modo portable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
