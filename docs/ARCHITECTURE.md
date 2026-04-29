# Arquitectura

## Flujo Principal

1. `main.py` recoge entrada, configuracion y modo de ejecucion.
2. `collect_pdfs()` localiza PDFs.
3. `precheck()` cuenta paginas y prepara resumen inicial.
4. `process_pdf()` procesa pagina a pagina:
   - extrae texto base con `pdfplumber`;
   - decide si debe aplicar OCR automatico;
   - detecta proveedor;
   - despacha al parser del proveedor;
   - normaliza campos criticos.
5. `run_pipeline()` consolida items, errores, trazas y Excel final.

## Componentes

- `main.py`: orquestacion, normalizacion, CLI, consolidacion Excel.
- `config.py`: defaults de OCR, debug, reglas de `SuPedidoCodigo` y workflow.
- `common.py`: utilidades compartidas para parsers.
- `debugkit.py`: helpers de trazas.
- `settings_manager.py`: configuracion persistente de usuario.
- `albaranes_tool/gui_app.py`: GUI Tk.
- `albaranes_tool/ocr_stage.py`: renderizado/preprocesado y OCR Tesseract.
- `albaranes_tool/selftest.py`: diagnostico reproducible de instalacion.
- `parsers/*.py`: logica especifica por proveedor.

## Parsers

Cada parser debe:

- detectar cabecera y lineas del proveedor sin hardcodear paginas;
- devolver items con columnas canonicas;
- evitar inferir datos que no aparecen en el documento;
- mantener reglas locales al proveedor siempre que sea posible.

Campos criticos usados en regresion:

- `Proveedor`
- `AlbaranNumero`
- `SuPedidoCodigo`
- `Importe`

## OCR

El OCR se aplica como complemento, no como sustituto global del texto embebido.

La configuracion actual evita forzar OCR sobre todo el documento porque puede empeorar importes en documentos que ya tienen texto fiable. El modo recomendado es automatico con Tesseract.

## Persistencia

En ejecucion instalada:

- programa: ruta elegida por el instalador;
- datos/debug/config de trabajo: `%LOCALAPPDATA%\AlbaranesParser\data`;
- configuracion GUI: `%APPDATA%\AlbaranesParser\config.json`.

Esta separacion permite actualizar sin borrar datos del usuario.

## Salidas

Salida principal:

- Excel maestro indicado por `--out` o elegido en GUI.

Salidas auxiliares:

- `albaranes_errores.txt`
- `albaranes_errores.xlsx`
- `debug/`
- trazas OCR y diagnosticos cuando debug/self-test estan activos.
