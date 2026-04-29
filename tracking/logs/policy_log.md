# Politica de mejoras parsers OCR -> Excel
- Prohibido hardcodear valores por albaran, codigo o pagina. No overrides ni ifs especificos.
- Cambios minimos, impacto maximo: priorizar normalizacion, heuristicas generales y validaciones.
- Separacion: OCR/preprocesado, segmentacion, deteccion de proveedor, extraccion, normalizacion, validacion, export.
- Validar con datos: comparar run vs corregido; clasificar errores (OCR, parsing, normalizacion, mapeo, ambiguedad).
- Observabilidad: guardar texto OCR, tokens, candidatos y decisiones en debug (debugkit si disponible).
- Deteccion de parser: senales robustas por proveedor; registro de parsers como plugins.
- Validacion/autocorreccion: no inventar; marcar baja confianza y trazabilidad en ParseWarn.
- Metricas: porcentaje de lineas correctas por proveedor en cada run; guardar en `tracking/metrics/control_metrics.csv`.
- Pruebas: cada fix debe tener test que falle antes y pase despues; usar pytest.

## Estructura de carpetas (baseline)
- `Albaranes_Pruebas/`: datasets activos (PDFs, OCR, GT corregidos) por semana/proveedor.
- `parsers/`, `tests/`, `scripts/`: codigo de parsers, tests y tooling core.
- `tracking/metrics|logs|rules`: control_metrics.csv, bitacora/politicas, resumen de reglas por parser.
- `temp/`: artefactos temporales y debug puntual.
- `archive/other_tools/`: herramientas auxiliares no core; `archive/review_semana05/` historico de runs previos.
- `debug/`: salidas de depuracion recientes por parser.
- `OLD/`: material legado que no se toca.
