# Desarrollo De Parsers

## Principios

- No hardcodear paginas, PDFs ni valores del master.
- Crear reglas por proveedor, basadas en texto o geometria verificable del documento.
- Mantener cambios acotados al parser cuando el problema sea especifico del proveedor.
- Usar normalizacion global solo cuando aplique a varios proveedores.
- Documentar excepciones cuando el master contiene datos manuales que no aparecen en el documento.

## Campos Criticos

Comparar siempre:

- `Proveedor`
- `AlbaranNumero`
- `SuPedidoCodigo`
- `Importe`

Para `SuPedidoCodigo`, aplicar comparacion canonica de compactacion/limpieza antes de contar errores.

## Flujo De Iteracion

1. Ejecutar semana objetivo.
2. Comparar contra master corregido.
3. Agrupar errores por proveedor, pagina y campo.
4. Revisar texto base/OCR/debug de la pagina.
5. Parchear solo si el valor aparece o puede inferirse por patron general del proveedor.
6. Compilar y repetir.
7. Si mejora, ejecutar semanas de control.
8. Registrar resultados en `tracking/logs/`.

## Comandos Base

```powershell
python main.py --in Albaranes_Pruebas\SEMANA_10 --out Albaranes_Pruebas\SEMANA_10\albaranes_master_run.xlsx --no-ui
```

Comparador usado por Codex:

```powershell
python C:\Users\ikerh\.codex\skills\albaranes-iterar-parsers\scripts\compare_week.py `
  --expected Albaranes_Pruebas\SEMANA_10\albaranes_master_corregido.xlsx `
  --actual Albaranes_Pruebas\SEMANA_10\albaranes_master_run.xlsx `
  --tag SEMANA_10_iter
```

## Debug

Revisar:

- `debug/parser_<proveedor>/`
- `debug/pages/`
- columnas `OcrStage`, `OcrPipeline`, `OcrTriggered`, `TriggerReason` en salidas Excel cuando esten disponibles.

## Aceptacion

Un parche es aceptable si:

- reduce errores reales;
- no empeora semanas de control;
- no introduce datos inventados;
- no depende de una pagina concreta;
- mantiene o mejora estabilidad global.
