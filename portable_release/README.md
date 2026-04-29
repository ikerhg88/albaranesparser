# Albaranes Parser (portable)

Este subproyecto genera un bundle autocontenido en un solo `.exe`, con parsers y binarios externos empaquetados. Se monta todo en una carpeta de datos persistente, de forma que los parsers se puedan actualizar copiando ficheros sin recompilar el exe.

## Flujo de build
1) Desde la raiz del repo:
```powershell
python portable_release/build_portable.py
```
Esto crea:
- `payload/app_payload.zip`: codigo + parsers + utilidades.
- `payload/external_bin_pack.zip`: copia de `external_bin/pack.zip` (si existe).
- `artifacts/parsers_pack.zip`: pack de parsers para desplegar por separado.
- `albaranes_portable.spec`: spec listo para PyInstaller.

2) Generar el `.exe` (requiere PyInstaller y las deps instaladas):
```powershell
cd portable_release
pyinstaller --clean albaranes_portable.spec
```
El ejecutable queda en `portable_release/dist/AlbaranesParserPortable.exe`.

## Como funciona el .exe
- Entry point: `src/bootstrap.py`.
- Directorio de datos por defecto:
  - Si el `.exe` es escribible: `./albaranes_data/`.
  - Si no: `%LOCALAPPDATA%/AlbaranesParserPortable/` (o `~/.albaranesparserportable` en *nix).
- En la primera ejecucion:
  - Extrae `payload/app_payload.zip` en `<datos>/app` (incluye `main.py`, `config.py`, `parsers/`, `albaranes_tool/`).
  - Extrae `payload/external_bin_pack.zip` en `<datos>/external_bin` (usa el pack del repo; si no existe, puedes colocar manualmente un `external_bin/` junto al exe o en `<datos>`).
  - Ajusta `PATH` para Tesseract, qpdf, Ghostscript, pngquant, ffmpeg, unpaper.
- Prueba de instalacion:
  - Desde consola: `AlbaranesParser.exe --self-test`
  - Genera `debug/installation_selftest/<timestamp>/installation_selftest_report.json` y `.txt`, junto con PDF/imagen de prueba y Excel resultante.
  - Verifica Tesseract, idiomas OCR, paquetes Python principales y pipeline real contra un PDF sintetico.
- El proceso se ejecuta desde `<datos>` para que caches y ficheros de salida se queden alli (`debug/`, Excels, etc.).
- Puedes sobreescribir la carpeta de datos con `ALBARANES_DATA_DIR`.

## Actualizar parsers sin recompilar
- Copia el contenido de `artifacts/parsers_pack.zip` sobre `<datos>/app/parsers`.
- O usa el helper:
```powershell
python portable_release/tools/apply_parsers_pack.py  # usa artifacts/parsers_pack.zip por defecto
```
Puedes pasar `--target` si quieres otra ruta (por ejemplo una unidad USB).

## Notas / supuestos
- Los scripts de debug con rutas absolutas no se incluyen en el payload; solo el codigo necesario para ejecutar.
- El pack `external_bin/pack.zip` del repo se asume portable (Tesseract, Ghostscript, qpdf, pngquant, ffmpeg, unpaper). Si cambian versiones, sustituye el pack y reejecuta `build_portable.py`.
- Para distribucion limpia, conserva solo `dist/AlbaranesParserPortable.exe` (opcionalmente junto a `albaranes_data/` si quieres modo 100% portable sin tocar `%LOCALAPPDATA%`).
