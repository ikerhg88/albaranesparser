# Albaranes Parser

Extractor multiproveedor de albaranes en PDF con parsers por proveedor, OCR con Tesseract y herramientas de diagnostico/regresion.

## Uso rapido

```powershell
python main.py --in "ruta\a\pdfs" --out "albaranes_master.xlsx" --no-ui
```

GUI:

```powershell
python main.py
```

Diagnostico de instalacion/OCR:

```powershell
python main.py --self-test
```

## Estructura

- `main.py`: pipeline principal.
- `parsers/`: parsers por proveedor.
- `albaranes_tool/`: OCR, GUI y self-test.
- `portable_release/`: scripts para generar instalador/runner Windows.
- `scripts/`: utilidades auxiliares.
- `tests/`: pruebas automatizadas disponibles.

## Notas

Los PDFs de pruebas, excels generados, builds, binarios externos, diagnosticos y releases no se versionan en Git. Se regeneran localmente cuando hace falta.
