"""Instalador Windows con asistente de ruta, versionado y registro HKCU."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import winreg
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

APP_NAME = "Albaranes Parser"
APP_ID = "AlbaranesParser"
APP_VERSION = "1.10.0"
BUILD_ID = "20260428.1000"
PAYLOAD_VERSION = "1.10.0+20260428.tesseract-default-menu"
PAYLOAD_ZIP = "payload/app_payload.zip"
EXTERNAL_PACK = "payload/external_bin_pack.zip"
EMBEDDED_RUNNER = "payload/AlbaranesParser.exe"
FIRST_RUN_SENTINEL = ".install_complete"

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


def _resource_path(rel_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel_path


def _default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Programs" / APP_ID
    return Path.home() / APP_ID


def _default_user_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_ID / "data"
    return Path.home() / f".{APP_ID.lower()}" / "data"


def _log_line(log_path: Path, msg: str) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


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


def _read_payload_metadata() -> dict:
    payload_zip = _resource_path(PAYLOAD_ZIP)
    try:
        with zipfile.ZipFile(payload_zip, "r") as zf:
            return json.loads(zf.read("VERSION.json").decode("utf-8"))
    except Exception:
        return {
            "app_name": APP_NAME,
            "app_id": APP_ID,
            "app_version": APP_VERSION,
            "build_id": BUILD_ID,
            "payload_version": PAYLOAD_VERSION,
        }


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


def _ensure_external_bin(ext_dir: Path) -> bool:
    pack = _resource_path(EXTERNAL_PACK)
    if not pack.exists():
        raise FileNotFoundError(f"No se encontro {pack}")
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
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _deploy_runner_exe(install_dir: Path) -> bool:
    target = install_dir / "AlbaranesParser.exe"
    embedded = _resource_path(EMBEDDED_RUNNER)
    if embedded.exists():
        shutil.copy2(embedded, target)
        return True
    sibling = Path(sys.executable).resolve().with_name("AlbaranesParser.exe") if getattr(sys, "frozen", False) else Path("AlbaranesParser.exe")
    if sibling.exists():
        shutil.copy2(sibling, target)
        return True
    return False


def _run_powershell(script: str) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _create_shortcut(link_path: Path, target: Path, workdir: Path, description: str, arguments: str = "") -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    ps = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{str(link_path).replace("'", "''")}')
$Shortcut.TargetPath = '{str(target).replace("'", "''")}'
$Shortcut.Arguments = '{arguments.replace("'", "''")}'
$Shortcut.WorkingDirectory = '{str(workdir).replace("'", "''")}'
$Shortcut.Description = '{description.replace("'", "''")}'
$Shortcut.Save()
"""
    _run_powershell(ps)


def _start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
    return Path.home() / "Start Menu" / APP_NAME


def _desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def _write_uninstaller(install_dir: Path) -> Path:
    uninstall = install_dir / "uninstall.ps1"
    start_menu = _start_menu_dir()
    desktop_link = _desktop_dir() / f"{APP_NAME}.lnk"
    content = f"""
$ErrorActionPreference = 'SilentlyContinue'
Remove-Item -LiteralPath '{str(start_menu).replace("'", "''")}' -Recurse -Force
Remove-Item -LiteralPath '{str(desktop_link).replace("'", "''")}' -Force
Remove-Item -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}' -Recurse -Force
Start-Sleep -Milliseconds 300
Remove-Item -LiteralPath '{str(install_dir).replace("'", "''")}' -Recurse -Force
"""
    uninstall.write_text(content, encoding="utf-8")
    return uninstall


def _register_uninstall(install_dir: Path, metadata: dict) -> None:
    uninstall = _write_uninstaller(install_dir)
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, str(metadata.get("app_version") or APP_VERSION))
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Albaranes Parser")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'powershell.exe -ExecutionPolicy Bypass -File "{uninstall}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _install(install_dir: Path, *, desktop_shortcut: bool = True, start_menu: bool = True) -> tuple[bool, Path]:
    install_dir = install_dir.expanduser().resolve()
    log_path = install_dir / "logs" / "installer.log"
    _log_line(log_path, "[INFO] Inicio instalador")
    code_dir = install_dir / "app"
    ext_dir = install_dir / "external_bin"
    marker = install_dir / FIRST_RUN_SENTINEL
    metadata = _read_payload_metadata()

    if not _is_writable(install_dir):
        raise PermissionError(f"No se puede escribir en {install_dir}")

    _log_line(log_path, f"Version: {metadata}")
    _log_line(log_path, f"Instalando en {install_dir}")
    payload_updated = _ensure_payload(code_dir)
    _ensure_external_bin(ext_dir)
    if not _deploy_runner_exe(install_dir):
        raise FileNotFoundError("No se encontro AlbaranesParser.exe embebido ni junto al instalador")

    metadata.update(
        {
            "install_dir": str(install_dir),
            "user_data_dir": str(_default_user_data_dir()),
            "installed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    (install_dir / "install_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (install_dir / "VERSION.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    marker.write_text("ok", encoding="utf-8")

    runner = install_dir / "AlbaranesParser.exe"
    uninstall = _write_uninstaller(install_dir)
    if start_menu:
        menu = _start_menu_dir()
        _create_shortcut(menu / f"{APP_NAME}.lnk", runner, install_dir, APP_NAME)
        _create_shortcut(
            menu / "Desinstalar Albaranes Parser.lnk",
            Path("powershell.exe"),
            install_dir,
            "Desinstalar Albaranes Parser",
            f'-ExecutionPolicy Bypass -File "{uninstall}"',
        )
    if desktop_shortcut:
        _create_shortcut(_desktop_dir() / f"{APP_NAME}.lnk", runner, install_dir, APP_NAME)
    _register_uninstall(install_dir, metadata)
    _log_line(log_path, "[OK] Instalacion completada")
    return payload_updated, log_path


def _ask_install_options(initial_dir: Path) -> tuple[Path, bool, bool] | None:
    root = tk.Tk()
    root.title(f"Instalar {APP_NAME}")
    root.geometry("640x260")
    root.resizable(False, False)
    result: dict[str, object] = {}
    path_var = tk.StringVar(value=str(initial_dir))
    desktop_var = tk.BooleanVar(value=True)
    start_var = tk.BooleanVar(value=True)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=f"{APP_NAME} {APP_VERSION}", font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Selecciona la carpeta donde instalar el programa. Los datos de trabajo se guardaran en tu perfil de usuario.",
    ).pack(anchor="w", pady=(6, 12))
    row = ttk.Frame(frame)
    row.pack(fill="x")
    ttk.Entry(row, textvariable=path_var).pack(side="left", fill="x", expand=True)

    def browse() -> None:
        selected = filedialog.askdirectory(initialdir=path_var.get() or str(initial_dir), title="Carpeta de instalacion")
        if selected:
            path_var.set(selected)

    ttk.Button(row, text="Examinar", command=browse).pack(side="left", padx=(8, 0))
    ttk.Checkbutton(frame, text="Crear acceso directo en el escritorio", variable=desktop_var).pack(anchor="w", pady=(14, 0))
    ttk.Checkbutton(frame, text="Crear acceso en menu Inicio", variable=start_var).pack(anchor="w")
    buttons = ttk.Frame(frame)
    buttons.pack(side="bottom", fill="x", pady=(18, 0))

    def install() -> None:
        result["path"] = Path(path_var.get())
        result["desktop"] = bool(desktop_var.get())
        result["start"] = bool(start_var.get())
        root.destroy()

    ttk.Button(buttons, text="Cancelar", command=root.destroy).pack(side="right")
    ttk.Button(buttons, text="Instalar", command=install).pack(side="right", padx=(0, 8))
    root.mainloop()
    if "path" not in result:
        return None
    return result["path"], bool(result["desktop"]), bool(result["start"])


def _main() -> int:
    parser = argparse.ArgumentParser(description=f"Instalador de {APP_NAME}")
    parser.add_argument("--install-dir", default="", help="Ruta de instalacion")
    parser.add_argument("--silent", action="store_true", help="Instalar sin asistente")
    parser.add_argument("--no-desktop-shortcut", action="store_true")
    parser.add_argument("--no-start-menu", action="store_true")
    args = parser.parse_args()

    try:
        if args.silent:
            install_dir = Path(args.install_dir) if args.install_dir else _default_install_dir()
            desktop = not args.no_desktop_shortcut
            start = not args.no_start_menu
        else:
            options = _ask_install_options(Path(args.install_dir) if args.install_dir else _default_install_dir())
            if options is None:
                return 1
            install_dir, desktop, start = options
        _, log_path = _install(install_dir, desktop_shortcut=desktop, start_menu=start)
        if args.silent:
            print(f"[OK] Instalacion completada en {install_dir}")
            print(f"Log de instalacion: {log_path}")
        else:
            messagebox.showinfo(APP_NAME, f"Instalacion completada en:\n{install_dir}\n\nLog:\n{log_path}")
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        fallback_log = _default_install_dir() / "logs" / "installer_error.log"
        _log_line(fallback_log, f"[ERROR] {exc}\n{tb}")
        try:
            messagebox.showerror(APP_NAME, f"Instalacion fallida:\n{exc}\n\nLog:\n{fallback_log}")
        except Exception:
            print(f"[ERROR] Instalacion fallida. Revisa {fallback_log}")
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
