from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_SECTION = "SETUP_WINDOWS.md#dependencias-gtk-y-weasyprint"

DLLS = [
    "libgobject-2.0-0.dll",
    "libglib-2.0-0.dll",
    "libpango-1.0-0.dll",
    "libcairo-2.dll",
]


def _candidate_paths() -> list[Path]:
    paths = []
    ext_bin = PROJECT_ROOT / "external_bin"
    if ext_bin.exists():
        paths.append(ext_bin)
        specific = ("gtk", "gtk\\bin", "weasyprint", "weasyprint\\bin")
        for sub in specific:
            folder = ext_bin / sub
            paths.append(folder)
        for child in ext_bin.iterdir():
            if child.is_dir():
                paths.append(child)
                paths.append(child / "bin")
    env_path = os.environ.get("PATH", "")
    if env_path:
        for chunk in env_path.split(os.pathsep):
            if chunk:
                paths.append(Path(chunk))
    return paths


def _find_dll(dll_name: str) -> Path | None:
    for folder in _candidate_paths():
        try:
            candidate = folder / dll_name
        except TypeError:
            continue
        if candidate.exists():
            return candidate
    found = shutil.which(dll_name)
    return Path(found) if found else None


def main() -> int:
    missing = {}
    for dll in DLLS:
        resolved = _find_dll(dll)
        if not resolved:
            missing[dll] = None
    if not missing:
        print("[INFO] Dependencias GTK/WeasyPrint detectadas.")
        return 0

    print("[WARN] No se han encontrado todas las bibliotecas nativas necesarias para Doctr/WeasyPrint.")
    print("       Faltan: " + ", ".join(missing.keys()))
    print("       Sigue las instrucciones en {} para instalar el runtime de GTK/WeasyPrint.".format(DOC_SECTION))
    print("       (El instalador continuará, pero OCR/WeasyPrint puede fallar hasta completar ese paso).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
