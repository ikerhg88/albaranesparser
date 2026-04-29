
# Albaranes Parser — Codex Ready

Este proyecto está preparado para ejecutarse en **Python 3.11** y trabajar cómodamente desde **VS Code** (con Copilot/Codex).
Incluye:
- Detección robusta por proveedor (lazy-import y trazas).
- Parsers más tolerantes (Saltoki multilínea; rescue mode en Aelvasa/Berdin).
- Informes de errores para el administrativo.

## Requisitos
- Python 3.11
- `pip install -r requirements.txt`

## Ejecutar
- **Windows**: `run.bat` ó `python main.py` (se abrirá selector si no pasas ruta).
- **VS Code**: abre la carpeta, presiona **F5** (configuración *Run main.py*).

## Configuracion numerica
- Ajusta `NUMERIC_RULES` en `config.py` para activar o desactivar la corrección automática de descuentos y los avisos sobre importes inconsistentes.
- El campo `importe_tolerance` controla la tolerancia (en euros) entre el importe detectado y el recalculado antes de generar el aviso.

## Pipeline OCR híbrido
- La ejecución base analiza siempre el texto embebido y sólo cuando la densidad de caracteres o el número de líneas cae por debajo de los umbrales definidos en `OCR_HEURISTICS` vuelve a lanzar Doctr/Tesseract.
- `OCR_CONFIG["preprocess"]` gobierna el render a 300 DPI, la binarización y el deskew previos al OCR. Puedes desactivar cada paso ajustando sus flags.
- `OCR_CONFIG["doctr"]` y `OCR_CONFIG["tesseract"]` se combinan: Doctr genera el texto estructurado y Tesseract refuerza cabeceras/códigos cortos (siempre con `--oem 1 --psm 6`).
- Si instalas Tesseract manualmente, apunta la ruta en `OCR_CONFIG["tesseract"]["cmd"]` (por defecto reutiliza la de ocrmypdf).
- Siempre puedes forzar el OCR en todas las páginas habilitando `OCR_WORKFLOW["ocr_force_all"]`.

## Pruebas rápidas
He incluido la carpeta `AlbaranesPrueba/` con PDFs de ejemplo. Selecciónala cuando el programa te pida la carpeta.

## Qué revisar
- Si alguna página queda con `ParseWarn = rescue_mode` o `fallback_no_parse`, el detalle ya aparece en los Excels y en `albaranes_errores.xlsx`.
- Para afinar un parser, abre su fichero en `parsers/` y ejecuta con F5 con *breakpoints* en `parse_page`.

¡Buen trabajo!
