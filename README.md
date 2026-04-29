# Albaranes Parser

Extractor multiproveedor de albaranes en PDF para generar un Excel maestro normalizado. El proyecto combina parsers por proveedor, OCR con Tesseract, GUI Windows, modo batch, diagnostico de instalacion y herramientas de release.

## Estado Actual

- Version de release Windows: `1.10.0`
- OCR operativo por defecto: `Tesseract`, modo automatico, `psm=11`
- OCRmyPDF y Doctr no se muestran en la GUI ni se activan por defecto
- Instalador Windows con ruta elegible, versionado y desinstalador
- Datos/configuracion separados del programa para permitir actualizaciones sin borrar ajustes

## Uso Rapido

GUI:

```powershell
python main.py
```

Batch:

```powershell
python main.py --in "D:\ruta\a\pdfs" --out "D:\salida\albaranes_master.xlsx" --no-ui
```

Diagnostico de instalacion/OCR:

```powershell
python main.py --self-test
```

El diagnostico genera informe en `debug/installation_selftest/<timestamp>/` y tambien accesos a ultimo informe en `debug/installation_selftest/ULTIMO_DIAGNOSTICO.txt`.

## Documentacion

- [Arquitectura](docs/ARCHITECTURE.md)
- [OCR y diagnostico](docs/OCR_AND_DIAGNOSTICS.md)
- [Instalacion en Windows](SETUP_WINDOWS.md)
- [Release y despliegue](docs/RELEASE_AND_DEPLOYMENT.md)
- [Publicacion en GitHub](docs/GITHUB_WORKFLOW.md)
- [Operacion con Codex](AGENTS.md)

## Estructura

- `main.py`: pipeline principal, CLI, normalizacion y orquestacion.
- `parsers/`: parsers por proveedor.
- `albaranes_tool/`: GUI, OCR y self-test.
- `portable_release/`: instalador y runner Windows.
- `scripts/`: utilidades auxiliares.
- `tests/`: pruebas unitarias disponibles.
- `tracking/logs/`: historico operativo de decisiones y releases.

## Pruebas

```powershell
python -m py_compile main.py config.py albaranes_tool\gui_app.py albaranes_tool\selftest.py portable_release\build_portable.py portable_release\src\bootstrap_installer.py portable_release\src\bootstrap_runner.py
python -m pytest
```

Para validar una instalacion completa:

```powershell
python main.py --self-test
```

## Release Windows

```powershell
python portable_release\build_portable.py
cd portable_release
python -m PyInstaller --clean albaranes_runner.spec
cd ..
python portable_release\build_portable.py
cd portable_release
python -m PyInstaller --clean albaranes_installer.spec
```

Los ejecutables finales se copian manualmente desde `portable_release/dist/` a `dist/` con sello de version.

## Datos No Versionados

No se suben a Git: PDFs de prueba, excels generados, `debug/`, `dist/`, `build/`, `external_bin/`, `.venv/`, temporales, releases y configuracion local. Revisa `.gitignore` antes de cualquier commit grande.
