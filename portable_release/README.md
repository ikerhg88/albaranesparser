# Portable Release

Herramientas para generar el runner y el instalador Windows de Albaranes Parser.

## Componentes

- `src/bootstrap_runner.py`: ejecutable `AlbaranesParser.exe`.
- `src/bootstrap_installer.py`: instalador grafico/silencioso.
- `build_portable.py`: genera payloads, packs y specs PyInstaller.
- `tools/apply_parsers_pack.py`: actualiza parsers en una instalacion existente.

## Layout Instalado

El instalador crea:

```text
<install_dir>\
  AlbaranesParser.exe
  app\
  external_bin\
  VERSION.json
  install_metadata.json
  uninstall.ps1
```

Los datos de usuario no se guardan en `install_dir`; se guardan en:

```text
%LOCALAPPDATA%\AlbaranesParser\data
```

## Versionado

Actualizar en paralelo:

- `APP_VERSION`
- `BUILD_ID`
- `PAYLOAD_VERSION`

Archivos:

- `build_portable.py`
- `src/bootstrap_installer.py`
- `src/bootstrap_runner.py`

## Build

Desde la raiz:

```powershell
python portable_release\build_portable.py
cd portable_release
python -m PyInstaller --clean albaranes_runner.spec
cd ..
python portable_release\build_portable.py
cd portable_release
python -m PyInstaller --clean albaranes_installer.spec
```

La segunda ejecucion de `build_portable.py` es importante: permite que el instalador embeba el runner recien compilado.

## Instalacion Silenciosa

```powershell
AlbaranesInstaller.exe --silent --install-dir "C:\Users\%USERNAME%\AppData\Local\Programs\AlbaranesParser"
```

Opciones:

- `--no-desktop-shortcut`
- `--no-start-menu`

## Validacion

Ejecutar self-test desde la instalacion:

```powershell
AlbaranesParser.exe --self-test
```

El reporte queda bajo la carpeta de datos del usuario o en la ruta definida por `ALBARANES_DATA_DIR`.
