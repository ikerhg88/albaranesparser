# Release Y Despliegue

## Versionado

El instalador Windows actual usa:

- `APP_VERSION`
- `BUILD_ID`
- `PAYLOAD_VERSION`

Estos valores se definen en:

```text
portable_release/build_portable.py
portable_release/src/bootstrap_installer.py
portable_release/src/bootstrap_runner.py
```

Al subir version, mantenerlos sincronizados.

## Build De Release

Desde la raiz:

```powershell
python -m py_compile main.py config.py albaranes_tool\gui_app.py albaranes_tool\selftest.py
python main.py --self-test --self-test-out debug\installation_selftest\pre_release
python portable_release\build_portable.py
```

Compilar runner:

```powershell
cd portable_release
python -m PyInstaller --clean albaranes_runner.spec
```

Regenerar payload para que el instalador embeba el runner recien construido:

```powershell
cd ..
python portable_release\build_portable.py
```

Compilar instalador:

```powershell
cd portable_release
python -m PyInstaller --clean albaranes_installer.spec
```

## Smoke Test Del Instalador

Ejemplo:

```powershell
$install = "D:\Albaranes\Albaranes_Parser\debug\installer_smoke\install"
$data = "D:\Albaranes\Albaranes_Parser\debug\installer_smoke\data"
Remove-Item (Split-Path $install -Parent) -Recurse -Force -ErrorAction SilentlyContinue
Start-Process portable_release\dist\AlbaranesInstaller.exe -ArgumentList @("--silent","--install-dir",$install,"--no-desktop-shortcut","--no-start-menu") -Wait
$env:ALBARANES_DATA_DIR = $data
Start-Process "$install\AlbaranesParser.exe" -ArgumentList @("--self-test","--self-test-out","debug\installed_selftest") -Wait
powershell.exe -ExecutionPolicy Bypass -File "$install\uninstall.ps1"
```

Validar:

- instalador exit 0;
- `app/`, `external_bin/`, `AlbaranesParser.exe`, `VERSION.json` presentes;
- self-test exit 0;
- uninstall elimina carpeta temporal.

## Publicacion De Artefactos

Copiar artefactos finales a `dist/` con sello:

```text
AlbaranesInstaller_<stamp>.exe
AlbaranesParser_<stamp>.exe
deploy_parsers_<stamp>.exe
parsers_pack_<stamp>.zip
RELEASE_NOTES_<stamp>.txt
```

No subir `dist/` a Git. Para releases publicos, usar GitHub Releases o almacenamiento externo.

## Actualizacion En Produccion

Ejecutar el instalador nuevo sobre la misma ruta. Se actualizan codigo y binarios, no los datos de usuario.

No borrar:

- `%LOCALAPPDATA%\AlbaranesParser\data`
- `%APPDATA%\AlbaranesParser\config.json`
