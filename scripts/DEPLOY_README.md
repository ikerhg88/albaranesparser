# Deploy parsers/core en otra máquina

## 1) Requisitos
- Python 3.11+ en la máquina origen.
- PyInstaller instalado (`python -m pip install --user pyinstaller`).

## 2) Generar el ejecutable
Desde la raíz del repo:
```bash
scripts\build_deploy_exe.bat
```
Salida: `dist\deploy_parsers.exe`.

## 3) Uso del ejecutable
En la máquina destino:
```
deploy_parsers.exe
```
- Pedirá seleccionar la carpeta de instalación destino.
- Copia: `parsers/` (sin backups), `common.py`, `main.py`, `config.py`, `settings_manager.py`, `requirements.txt`, `README_codex.md`.
- Tambien copia `debugkit.py` y `albaranes_tool/`, necesarios para OCR y diagnostico.

## 3.1) Prueba tras instalar
En la maquina destino, desde la carpeta instalada:
```bash
python main.py --self-test
```
Si se usa el ejecutable portable:
```bash
AlbaranesParser.exe --self-test
```
El informe queda en `debug/installation_selftest/<timestamp>/` e incluye prueba de Tesseract, PDF sintetico, Excel de salida y reporte JSON/TXT.

Flags (si se usa el .py en vez de .exe):
- `--target "C:/ruta/destino"` para especificar carpeta.
- `--dry-run` para ver qué copiaría.

## 4) Flujo semanal sugerido
1. Actualizar parsers y pasar tests.
2. `scripts\build_deploy_exe.bat`
3. Llevar `dist\deploy_parsers.exe` a la máquina destino y ejecutarlo eligiendo la carpeta instalada.
