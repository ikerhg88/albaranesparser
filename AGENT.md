# AGENT.md - Metodo de trabajo Codex (Semana 09)

## Objetivo
Mejorar la extraccion de `SEMANA_09` sin introducir hardcodes por documento/pagina y sin degradar el resto de semanas.

## Principios
- Nada hardcodeado por PDF, pagina o albaran.
- Cambios genericos y trazables.
- Siempre backup antes de tocar codigo.
- Siempre validacion despues de cada iteracion.
- Mantener registro en diario.
- Toda release compilada se publica en `d:\Albaranes\Albaranes_Parser\dist`.

## Flujo obligatorio por iteracion
1. Crear backup en `archive/codex_backups/iter_YYYYMMDD_HHMMSS_*`.
2. Aplicar cambios minimos en parser/core.
3. Validar sintaxis (`python -m py_compile main.py`).
4. Ejecutar:
   - `SEMANA_09` (objetivo principal).
   - `SEMANA_05`, `SEMANA_06`, `SEMANA_07` (control de regresion).
5. Calcular diferencias de campos criticos:
   - `Proveedor`
   - `AlbaranNumero`
   - `SuPedidoCodigo`
   - `Importe`
6. Guardar resumen en `debug/regression_iter_vXX_summary.csv`.
7. Registrar en diario:
   - cambios realizados
   - resultados
   - decision (se acepta/no se acepta la iteracion)

## Criterio de aceptacion
- No empeorar `SEMANA_05/06/07` en errores de campos criticos frente al baseline acordado.
- Reducir errores de `SEMANA_09` frente al baseline actual.
- Si hay tradeoff, documentar explicitamente que campo mejora y cual empeora.

## Convencion de outputs
- `Albaranes_Pruebas/SEMANA_05/albaranes_master_run_sem05_iter_vXX.xlsx`
- `Albaranes_Pruebas/SEMANA_06/albaranes_master_run_sem06_iter_vXX.xlsx`
- `Albaranes_Pruebas/SEMANA_07/albaranes_master_run_sem07_iter_vXX.xlsx`
- `Albaranes_Pruebas/SEMANA_09/albaranes_master_run_semana09_iter_vXX.xlsx`

## Publicacion de releases
- Carpeta oficial de publicacion: `d:\Albaranes\Albaranes_Parser\dist`.
- Los binarios se publican con sello de version/fecha para evitar sobreescrituras.
- Artefactos minimos por release:
  - `AlbaranesInstaller_YYYYMMDD_HHMMSS.exe`
  - `AlbaranesParser_YYYYMMDD_HHMMSS.exe`
  - `parsers_pack_YYYYMMDD_HHMMSS.zip`
  - `RELEASE_NOTES_YYYYMMDD_HHMMSS.txt`

## Metodologia tecnica para SuPedido (foco actual)
- Priorizar normalizacion por patrones generales OCR.
- Evitar decisiones por proveedor salvo reglas de negocio estables y justificadas.
- Distinguir claramente:
  - preservacion de sufijos validos
  - compactacion de ruido OCR
- Medir impacto por proveedor y por patron conflictivo antes de consolidar.
- En comparativas historicas, `SuPedidoCodigo` se evalua con equivalencia canonica de compactacion/sufijos para no contar como regresion diferencias ya resueltas por normalizacion (`25.625-01/E` ~= `25625/01`, `25035/23` ~= `25035`, `A260107/IA2` ~= `A260107`).
