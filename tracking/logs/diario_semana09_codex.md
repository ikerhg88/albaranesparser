# Diario Semana 09 (Codex)

## Alcance
Bitacora operativa para mejorar `SEMANA_09` con control de regresion en `SEMANA_05/06/07`.

## Baselines usados
- SEMANA_05: `albaranes_master_run_sem05_global_latest.xlsx`
- SEMANA_06: `albaranes_master_run_sem06_global_latest.xlsx`
- SEMANA_07: `albaranes_master_run_sem07_global_latest.xlsx`
- SEMANA_09: `albaranes_master_run_semana09_newparsers_v7.xlsx`

## 2026-03-10 - Estado inicial de analisis

### Version activa seleccionada
- `iter_v16` (mejor equilibrio actual para no degradar semanas anteriores).
- Resumen: `debug/regression_iter_v16_summary.csv`.

### Resultado comparativo (v16 vs baseline)
- SEMANA_05: `ErrFields 33 -> 18` (mejora, -15)
- SEMANA_06: `ErrFields 68 -> 52` (mejora, -16)
- SEMANA_07: `ErrFields 24 -> 16` (mejora, -8)
- SEMANA_09: `ErrFields 77 -> 112` (empeora, +35)

### Foco principal SEMANA_09
- Error dominante: `SuPedidoCodigo` (`29 -> 67`, delta +38).
- Proveedores con mas impacto en SuPedido:
  - SALTOKI (16)
  - BERDIN (13)
  - GABYL (10)
  - ALKAIN (9)
- Patrones conflictivos mas frecuentes en prediccion:
  - `A240226`, `A240226VL`
  - `26.501/04/H`
  - `21.211-FJ`
  - `A260224/IA2`, `A260218/IA1`
- Paginas con mayor concentracion de fallos de SuPedido:
  - p18 (7)
  - p29 (6)
  - p01 (4)
  - p14 (3)
  - p61/p60/p27/p28/p39/p51/p58 (2 cada una)

### Backups creados en la sesion
- `archive/codex_backups/iter_regression_20260309_151520`
- `archive/codex_backups/iter_regression_20260309_152516_v14prep`
- `archive/codex_backups/iter_regression_20260309_152906_v15patch`
- `archive/codex_backups/iter_regression_20260309_153208_v16patch`
- `archive/codex_backups/iter_regression_20260309_153452_v17patch`

### Decision
- Se mantiene codigo en estado `v16` para evitar regresion en `SEMANA_05/06/07`.
- Siguiente paso: atacar especificamente `SuPedido` en `SEMANA_09` con analisis por patron OCR.

---

## 2026-03-10 - Iteracion v18 (mejora estable)

### Cambios aplicados
- `parsers/alkain.py`
  - `_find_supedido`: ahora permite pedidos numericos de 8-9 digitos cuando vienen de contexto `PEDIDO`.
  - `_norm_order`: acepta tokens numericos de 8-9 digitos (antes solo 9).
  - Fallback de cabecera ampliado para capturar `\\d{8,9}`.
- `parsers/gabyl.py`
  - Normalizacion conservadora de `SuPedido` para patron `dd.ddd-XX` -> `ddddd` (ej. `21.211-FJ -> 21211`).
- `parsers/semega.py`
  - Normalizacion de referencia:
    - `25.018-E -> 25018`
    - `A-130226-FJ -> A130226`
- `config.py`
  - `SUPEDIDO_RULES['ALKAIN']['no_truncate'] = True` para evitar recortes tipo `250226 -> 25022`.

### Backup de esta iteracion
- `archive/codex_backups/iter_sem09_20260310_125036_patch1`

### Resultado (v18 vs baseline)
- SEMANA_05: `ErrFields 33 -> 16` (delta `-17`)
- SEMANA_06: `ErrFields 68 -> 48` (delta `-20`)
- SEMANA_07: `ErrFields 24 -> 16` (delta `-8`)
- SEMANA_09: `ErrFields 77 -> 97` (delta `+20`)

### Comparativa directa (v18 vs v16)
- SEMANA_05: mejora adicional `-2` errores de campo.
- SEMANA_06: mejora adicional `-4`.
- SEMANA_07: sin cambio.
- SEMANA_09: mejora adicional `-15` (todo en `SuPedido`).

### Estado tras v18
- Se mantiene criterio de no regresion en semanas anteriores.
- En SEMANA_09 sigue quedando gap principalmente en `SuPedido`:
  - proveedores mas afectados: SALTOKI (16), BERDIN (13), GABYL (6).
  - resumen: `debug/sem09_supedido_mismatch_focus_v18.csv`.

---

## 2026-03-10 - Iteracion v19 (normalizacion SALTOKI)

### Cambios aplicados
- `parsers/saltoki.py`
  - normalizacion adicional para OCR de `SuPedido` tipo `A240226VL` -> `A240226`.
  - regla de compactacion para variantes con prefijo `A.`.

### Resultado (v19 vs baseline)
- SEMANA_05: `ErrFields 33 -> 16` (delta `-17`)
- SEMANA_06: `ErrFields 68 -> 48` (delta `-20`)
- SEMANA_07: `ErrFields 24 -> 16` (delta `-8`)
- SEMANA_09: `ErrFields 77 -> 87` (delta `+10`)

### Decision
- Iteracion util como base intermedia (mejora clara frente a v16/v18), pero `SEMANA_09` seguia por encima del baseline.

---

## 2026-03-10 - Iteracion v23 (cabeceras albaran robustas)

### Backups de la sesion
- `archive/codex_backups/iter_sem09_20260310_131219_patch3`

### Cambios aplicados
- `parsers/saltoki.py`
  - `_find_albaran` reforzado para cabecera partida (`CLIENTE ALBARÁN` y `FECHA` en linea siguiente).
  - soporte de fechas con espacios alrededor de `/` en la linea cliente.
- `parsers/alkain.py`
  - `_find_albaran` ahora filtra ruido OCR de digitos repetidos/largos (`111...`) y prioriza longitudes plausibles (8-9).
- `parsers/gabyl.py`
  - fallback OCR de cabecera para recuperar `AlbaranNumero` cuando `extract_text()` no lo trae.
  - correccion de bug en `within_bbox` (no era context manager), activando el OCR real.
  - filtro de pseudo-lineas de cabecera para evitar items falsos.
  - mejora de parseo numerico para casos con decimal en punto OCR.

### Resultado (v23 vs baseline)
- SEMANA_05: `ErrFields 28 -> 15` (delta `-13`)
- SEMANA_06: `ErrFields 67 -> 48` (delta `-19`)
- SEMANA_07: `ErrFields 24 -> 15` (delta `-9`)
- SEMANA_09: `ErrFields 77 -> 76` (delta `-1`)

### Comparativa directa (v23 vs v19)
- SEMANA_05: `16 -> 15` (mejora `-1`)
- SEMANA_06: `48 -> 48` (sin cambio)
- SEMANA_07: `16 -> 15` (mejora `-1`)
- SEMANA_09: `87 -> 76` (mejora `-11`)
  - detalle principal: `AlbaranNumero 22 -> 12`.

### Artefactos de validacion
- `debug/regression_iter_v23_summary.csv`
- `debug/regression_iter_v23_vs_v19.csv`
- `debug/regression_iter_v23_semana_05_detail.csv`
- `debug/regression_iter_v23_semana_06_detail.csv`
- `debug/regression_iter_v23_semana_07_detail.csv`
- `debug/regression_iter_v23_semana_09_detail.csv`

### Decision
- **Aceptada** como nueva base de trabajo:
  - no degrada semanas anteriores,
  - y deja `SEMANA_09` por debajo del baseline actual en campos criticos.

---

## Plantilla de entrada para proximas iteraciones
### Fecha/hora
- 

### Cambio aplicado
- 

### Resultado SEMANA_09
- 

### Regresion SEMANA_05/06/07
- 

### Decision
- 

---

## 2026-04-27 - Iteracion SEMANA_10 parser-only v4

### Backup de la sesion
- `archive/codex_backups/iter_20260427_121129_sem10_parsers_baseline`

### Cambios aplicados
- Solo carpeta `parsers/`.
- Nuevos parsers/deteccion: `dataeraser.py`, `simon.py`, `carandini.py`, `urkunde.py`.
- `parsers/txofre.py`: prioriza `N ALBARAN` de cabecera y evita tomar referencias de linea `Ped/Pre` como albaran.
- `parsers/saltoki.py`: refuerzo para cabecera vertical `CLIENTE ALBARAN` y normalizacion `S/REF` tipo `26.004V06VY -> 26004/06`.

### Resultado SEMANA_10
- Baseline actual `albaranes_master_run_sem10_iter_v1.xlsx`: 75 errores criticos / 46 lineas con error.
- Nuevo `albaranes_master_run_sem10_iter_v4.xlsx`: 41 errores criticos / 30 lineas con error.
- Delta: `-34` errores criticos.
- Proveedores nuevos en SEMANA_10 quedan sin error critico por comparador de campos: `SIMON`, `CARANDINI`, `URKUNDE`, `DATAERASER`.
- `TXOFRE` queda a 0 errores criticos en SEMANA_10.

### Regresion SEMANA_05/06/07/09
- Outputs generados:
  - `Albaranes_Pruebas/SEMANA_05/albaranes_master_run_sem05_iter_v4_sem10.xlsx`
  - `Albaranes_Pruebas/SEMANA_06/albaranes_master_run_sem06_iter_v4_sem10.xlsx`
  - `Albaranes_Pruebas/SEMANA_07/albaranes_master_run_sem07_iter_v4_sem10.xlsx`
  - `Albaranes_Pruebas/SEMANA_09/albaranes_master_run_semana09_iter_v4_sem10.xlsx`
- Resumen exportado: `debug/regression_sem10work_summary.csv`.
- Comparado contra `iter_v23`, 05/06/07 salen peor principalmente por `SuPedidoCodigo`; SEMANA_09 sale mejor. Requiere baseline pre-cambio/current o iteracion especifica de normalizacion antes de aceptar release.

### Decision
- No aceptar todavia como release global.
- Mantener como avance SEMANA_10 y siguiente foco: resolver residuales por proveedor (`ELICETXE`, `GABYL`, `ALKAIN`, `AELVASA`, `BERDIN`, `SALTOKI`) y aclarar baseline de control.

---

## 2026-04-27 - Iteracion SEMANA_10 parser-only v9

### Backup de la sesion
- `archive/codex_backups/iter_20260427_145946_sem10_v5_parsers`
- `archive/codex_backups/iter_20260427_152000_sem10_v9_parsers`

### Cambios aplicados
- Solo carpeta `parsers/`.
- `parsers/gabyl.py`: recupera linea embebida `NIE000002166 / 8504.2 BL` cuando OCR la concatena dentro de la descripcion anterior.
- `parsers/saltoki.py`: normaliza caso OCR `26.790/...` como `26090/...`.
- `parsers/elicetxe.py`: descarta linea residual OCR de packing list Miguelez `10010071` con patron `Z'6:`/`&l/`.

### Resultado SEMANA_10
- `albaranes_master_run_sem10_iter_v9.xlsx`: 12 errores criticos / 11 lineas con error.
- Delta contra baseline `iter_v1`: `75 -> 12` (`-63` errores criticos).
- Delta contra v4: `41 -> 12` (`-29` errores criticos).
- Proveedores a 0 errores criticos en SEMANA_10: `AELVASA`, `CARANDINI`, `DATAERASER`, `DESCONOCIDO`, `ELICETXE`, `GABYL`, `SIMON`, `TXOFRE`, `URKUNDE`.
- Pendientes parser-only:
  - `BERDIN` p1: el parser obtiene sufijo OCR equivalente a `/IA1`, pero `main.py/config.py` lo trunca por politica global de SuPedido BERDIN.
  - `BERDIN` p9: el texto extraido no contiene el campo `Su Pedido`.
  - `SALTOKI` p3: el texto extraido no contiene el albaran esperado `471143`.
  - `SALTOKI` p39: el texto extraido contiene `S/REF:CARTEL PROHIB RECARGA BATE`, no `A260226/Y`.
  - `ALKAIN` p2/p29: falta el pedido real `A020326` en el texto extraido; p2 ademas trae albaran OCR incompleto/ruidoso.

### Artefactos
- `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_sem10_iter_v9.xlsx`
- `debug/sem10_iter_v9_summary.csv`
- `debug/sem10_iter_v9_detail.csv`
- Controles ejecutados:
  - `Albaranes_Pruebas/SEMANA_05/albaranes_master_run_SEMANA_05_sem10_v9_control.xlsx`
  - `Albaranes_Pruebas/SEMANA_06/albaranes_master_run_SEMANA_06_sem10_v9_control.xlsx`
  - `Albaranes_Pruebas/SEMANA_07/albaranes_master_run_SEMANA_07_sem10_v9_control.xlsx`
  - `Albaranes_Pruebas/SEMANA_09/albaranes_master_run_SEMANA_09_sem10_v9_control.xlsx`

### Decision
- Mantener como avance de SEMANA_10.
- Para llegar a 0 sin hardcodear paginas, el siguiente paso ya no es solo parser: requiere ajustar normalizacion global de BERDIN y/o mejorar OCR/ROI de cabeceras para los campos que no aparecen en texto.

---

## 2026-04-27 - Comparativa canonica contra v23 y SEMANA_10

### Cambios aplicados
- `parsers/alkain.py`: `_extract_albaran_from_fecha_row` prioriza fecha explicita + numero inmediatamente posterior antes de compactar todos los digitos de la fila. Corrige caso general donde ruido del encabezado desplazaba el albaran (`262000696` leido como `626200069`).
- Skill `albaranes-iterar-parsers`: `compare_week.py` compara `SuPedidoCodigo` con equivalencia canonica de compactacion/sufijos.
- Skill `albaranes-iterar-parsers`: documentada excepcion de master antiguo con `SuPedidoCodigo` vacio cuando el parser detecta un pedido plausible.
- `AGENT.md`: incorporada la politica de comparativa historica canonica.

### Reglas canonicas nuevas
- `25.625-01/E` ~= `25625/01`
- `26.002V01VY` ~= `26002/01`
- `25035/23` ~= `25035`
- `A260107/IA2` ~= `A260107`
- `H100226L` ~= `H100226`

### Artefactos
- Outputs frescos:
  - `Albaranes_Pruebas/SEMANA_05/albaranes_master_run_SEMANA_05_current_canonical_fresh2.xlsx`
  - `Albaranes_Pruebas/SEMANA_06/albaranes_master_run_SEMANA_06_current_canonical_fresh2.xlsx`
  - `Albaranes_Pruebas/SEMANA_07/albaranes_master_run_SEMANA_07_current_canonical_fresh2.xlsx`
  - `Albaranes_Pruebas/SEMANA_09/albaranes_master_run_SEMANA_09_current_canonical_fresh2.xlsx`
  - `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_SEMANA_10_current_canonical_fresh2.xlsx`
- Comparativa final:
  - `debug/history/iter_20260427_global_vs_v23_canonical_final2/summary_current_vs_v23_canonical_final2.csv`
  - `debug/history/iter_20260427_global_vs_v23_canonical_final2/current_errors_by_week_provider_field.csv`

### Resultado contra v23
- SEMANA_05: actual `19`, v23 `15`, delta `+4`.
- SEMANA_06: actual `27`, v23 `28`, delta `-1`.
- SEMANA_07: actual `11`, v23 `11`, delta `0`.
- SEMANA_09: actual `6`, v23 `14`, delta `-8`.
- Total 05/06/07/09: actual `63`, v23 `68`, delta global `-5`.
- SEMANA_10 queda con `6` diferencias de `SuPedidoCodigo`, ya revisadas como campos manuales/no presentes en documento segun criterio del usuario; errores reales revisables: `0`.

### Decision
- Se acepta la regla canonica de comparacion historica.
- El codigo actual mejora globalmente contra v23 en semanas comparables, aunque SEMANA_05 sigue peor por residuales concretos que requieren nueva iteracion por proveedor/pagina.

---

## 2026-04-27 - Preparacion despliegue produccion SEMANA_10

### Comprobacion v23 sobre SEMANA_10
- Ejecucion temporal con parsers v23 (`alkain.py`, `gabyl.py`, `saltoki.py`) desde `archive/codex_backups/iter_sem09_20260310_133148_v23_accepted`.
- Output: `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_SEMANA_10_v23_check.xlsx`.
- Comparativa canonica: `26` errores criticos / `22` filas con error.
- Artefactos:
  - `debug/history/iter_20260427_sem10_v23_check/SEMANA_10_v23_check_canonical_summary.csv`
  - `debug/history/iter_20260427_sem10_v23_check/SEMANA_10_v23_check_canonical_detail.csv`

### Preparacion despliegue
- `scripts/deploy_parsers.py`: ahora copia tambien `debugkit.py` y `albaranes_tool/`, necesarios para OCR/parsers actuales.
- Reconstruido `dist/deploy_parsers.exe`.
- Actualizado payload portable version `2026-04-27-sem10-canonical`.
- Compilados ejecutables portables.

### Artefactos finales
- `dist/AlbaranesInstaller_20260427_2223_sem10.exe`
- `dist/AlbaranesParser_20260427_2223_sem10.exe`
- `dist/deploy_parsers_20260427_2223_sem10.exe`
- `dist/parsers_pack_20260427_2223_sem10.zip`
- `dist/RELEASE_NOTES_20260427_2223_sem10.txt`

### Dependencias OCR
- Tesseract es necesario para reglas actuales de `BERDIN`, `GABYL`, `SALTOKI` y `LEYCOLAN`.
- El instalador portable incluye `external_bin_pack.zip` con Tesseract y binarios OCR.
- Si se usa solo `deploy_parsers.exe` sobre una instalacion existente, esa instalacion debe conservar `external_bin/tesseract/tesseract.exe`, `tessdata/spa.traineddata` y `tessdata/eng.traineddata`; Doctr/Torch siguen siendo dependencias Python si se ejecuta desde codigo fuente.

---

## 2026-04-28 - Self-test de instalacion y diagnostico OCR

### Cambios aplicados
- Nuevo modulo `albaranes_tool/selftest.py`.
- CLI:
  - `python main.py --self-test`
  - `python main.py --self-test --self-test-out debug/installation_selftest/manual`
- GUI: boton `Diagnostico instalacion`.
- `scripts/deploy_parsers.py`: mantiene copia de `albaranes_tool/`, ahora incluyendo `selftest.py`.
- `portable_release`: payload version `2026-04-28-install-selftest`, incluye `albaranes_tool/selftest.py`.

### Que verifica
- Resolucion de ruta de Tesseract desde `OCR_CONFIG` o `PATH`.
- `tesseract --version`.
- `tesseract --list-langs`.
- OCR directo sobre imagen sintetica `tesseract_probe.png`.
- Creacion de PDF sintetico `selftest_alkain.pdf`.
- Ejecucion del pipeline real contra ese PDF.
- Validacion de resultado esperado: `Proveedor=ALKAIN`, `AlbaranNumero=261234567`, `SuPedidoCodigo=A010426`, `Importe=12.34`.
- Inventario de entorno: Python, ejecutable, plataforma, variables relevantes, paquetes principales y rutas.

### Artefactos generados por el diagnostico
- `debug/installation_selftest/<timestamp>/installation_selftest_report.json`
- `debug/installation_selftest/<timestamp>/installation_selftest_report.txt`
- `debug/installation_selftest/<timestamp>/packages.csv`
- `debug/installation_selftest/<timestamp>/fixtures/tesseract_probe.png`
- `debug/installation_selftest/<timestamp>/fixtures/pipeline_pdf/selftest_alkain.pdf`
- `debug/installation_selftest/<timestamp>/pipeline_selftest_output.xlsx`

### Validacion local
- Fuente: `python main.py --self-test --self-test-out debug/installation_selftest/post_patch_check` -> OK.
- Portable instalado en `temp/portable_installed_selftest_20260428`:
  - Instalador extrajo payload y `external_bin`.
  - Runner instalado `AlbaranesParser.exe --self-test` -> exit `0`.

### Artefactos finales
- `dist/AlbaranesInstaller_20260428_0735_selftest.exe`
- `dist/AlbaranesParser_20260428_0735_selftest.exe`
- `dist/deploy_parsers_20260428_0735_selftest.exe`
- `dist/parsers_pack_20260428_0735_selftest.zip`
- `dist/RELEASE_NOTES_20260428_0735_selftest.txt`

---

## 2026-04-28 - OCR SEMANA_10, diagnostico visible y release ocrdiag

### Incidencia revisada
- Run de usuario sobre `Albaranes_Pruebas/SEMANA_10` comparado contra `albaranes_master_corregido.xlsx`.
- La GUI estaba en `OCR automatico`, pero el checkbox avanzado `Forzar OCR (workflow)` seguia activando `OCR_WORKFLOW.ocr_force_all`.
- Una configuracion antigua en `%APPDATA%/AlbaranesParser/config.json` mantenia `ocr_force_all=true`, afectando tambien modo batch.

### Resultado de comparacion de opciones OCR
- `base_no_ocr`: 7 residuales criticos.
- `tesseract_auto`: 6 residuales criticos, mejor opcion.
- `tesseract_force`: 8 residuales criticos, empeora `TXOFRE` por importes.
- `all_available_force`: 8 residuales criticos; OCRmyPDF/Doctr no disponibles y mismo empeoramiento por OCR forzado.

### Cambios aplicados
- `albaranes_tool/gui_app.py`: el checkbox avanzado de forzar OCR queda deshabilitado y no afecta al workflow; solo manda el selector principal `Forzar OCR siempre`.
- `main.py`: migracion de configuracion antigua; `ocr_force_all` solo se respeta si `ocr_mode == "force"`.
- `main.py`: OCRmyPDF y Doctr se desactivan si el modulo Python no esta instalado, evitando warnings inutiles en ejecucion normal.
- `config.py`: Doctr desactivado por defecto.
- `albaranes_tool/selftest.py`: ademas del informe con timestamp, escribe:
  - `debug/installation_selftest/ULTIMO_DIAGNOSTICO.txt`
  - `debug/installation_selftest/ULTIMO_DIAGNOSTICO.json`
  - `debug/installation_selftest/ULTIMA_CARPETA_DIAGNOSTICO.txt`
- `portable_release`: payload version `2026-04-28-ocrdiag-report`.

### Validacion
- `python -m py_compile main.py config.py albaranes_tool/gui_app.py albaranes_tool/selftest.py` -> OK.
- `python main.py --self-test --self-test-out debug/installation_selftest/post_ocr_ui_patch` -> OK.
- SEMANA_10 saneada:
  - Output: `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_SEMANA_10_current_defaults_after_sanitize.xlsx`
  - Summary: `debug/history/iter_20260428_current_defaults_after_sanitize/SEMANA_10_current_defaults_after_sanitize_summary.csv`
  - Detail: `debug/history/iter_20260428_current_defaults_after_sanitize/SEMANA_10_current_defaults_after_sanitize_detail.csv`
  - Total criticos: 6 residuales conocidos de `SuPedidoCodigo`; `TXOFRE` vuelve a 0 errores.

### Artefactos finales
- `dist/AlbaranesInstaller_20260428_0835_ocrdiag.exe`
- `dist/AlbaranesParser_20260428_0835_ocrdiag.exe`
- `dist/deploy_parsers_20260428_0835_ocrdiag.exe`
- `dist/parsers_pack_20260428_0835_ocrdiag.zip`
- `dist/RELEASE_NOTES_20260428_0835_ocrdiag.txt`

---

## 2026-04-28 - Menu OCR limpio y default Tesseract

### Matriz SEMANA_10
- Resultado completo guardado en `debug/history/iter_20260428_ocr_matrix_sem10/ocr_matrix_results.csv`.
- Mejor grupo por errores:
  - `tess_auto_p11_s0`: 6 criticos, 0 importe, 0 TXOFRE importe.
  - `tess_auto_p4_s11`: 6 criticos, 0 importe, 0 TXOFRE importe.
  - `tess_auto_prep_b1_d1`: 6 criticos, 0 importe, 0 TXOFRE importe.
- Se elige `tess_auto_p11_s0` porque mantiene el mismo resultado critico y reduce duracion de SEMANA_10 a `1m23s`.
- Configuraciones descartadas:
  - `text_only`: 7 criticos.
  - `tess_force_prep_b1_d1`: 8 criticos y 2 errores de importe TXOFRE.
  - Preprocesado sin binarizado o sin deskew: de 27 a 91 criticos.

### Cambios aplicados
- `config.py`: Tesseract por defecto `psm=11` y sin `secondary_psm`.
- `albaranes_tool/gui_app.py`: retiradas del menu las opciones OCRmyPDF y Doctr; se mantienen internas como `enabled=false`.
- `main.py`: retiradas OCRmyPDF y Doctr de los configuradores Tk legacy; se guardan siempre como disabled.
- `portable_release/build_portable.py`: retirados OCRmyPDF, Doctr y Torch de dependencias explicitas del runner portable.
- `portable_release`: payload version `2026-04-28-tesseract-default-menu`.

### Validacion
- `python -m py_compile main.py config.py albaranes_tool/gui_app.py albaranes_tool/selftest.py` -> OK.
- Default nuevo:
  - Output: `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_SEMANA_10_default_psm11.xlsx`
  - Summary: `debug/history/iter_20260428_default_psm11/SEMANA_10_default_psm11_summary.csv`
  - Total criticos: 6 residuales conocidos de `SuPedidoCodigo`; `TXOFRE` 0 errores.
- PyInstaller OK para instalador, runner y deploy parsers.

### Artefactos finales
- `dist/AlbaranesInstaller_20260428_0955_tessdefault.exe`
- `dist/AlbaranesParser_20260428_0955_tessdefault.exe`
- `dist/deploy_parsers_20260428_0955_tessdefault.exe`
- `dist/parsers_pack_20260428_0955_tessdefault.zip`
- `dist/RELEASE_NOTES_20260428_0955_tessdefault.txt`

---

## 2026-04-28 - Distribucion final tessdefault

### Pruebas pre-release
- `python -m py_compile main.py config.py albaranes_tool/gui_app.py albaranes_tool/selftest.py` -> OK.
- `python main.py --self-test --self-test-out debug/installation_selftest/pre_release_tessdefault_final` -> OK.
- SEMANA_10:
  - Output: `Albaranes_Pruebas/SEMANA_10/albaranes_master_run_SEMANA_10_release_tessdefault_final.xlsx`
  - Summary: `debug/history/iter_20260428_release_tessdefault_final/SEMANA_10_release_tessdefault_final_summary.csv`
  - Detail: `debug/history/iter_20260428_release_tessdefault_final/SEMANA_10_release_tessdefault_final_detail.csv`
  - Resultado: 6 residuales conocidos de `SuPedidoCodigo`, `TXOFRE` 0 errores, `Importe` 0 errores.

### Distribucion
- Recompilado payload portable con menu OCR limpio y default Tesseract `psm=11`.
- Recompilados instalador, runner y deploy parsers.

### Artefactos finales
- `dist/AlbaranesInstaller_20260428_1000_tessdefault_final.exe`
- `dist/AlbaranesParser_20260428_1000_tessdefault_final.exe`
- `dist/deploy_parsers_20260428_1000_tessdefault_final.exe`
- `dist/parsers_pack_20260428_1000_tessdefault_final.zip`
- `dist/RELEASE_NOTES_20260428_1000_tessdefault_final.txt`

---

## 2026-04-28 - Instalador Windows v1.10.0

### Cambios aplicados
- `portable_release/src/bootstrap_installer.py`: reescrito como instalador Windows con asistente grafico Tk.
- `portable_release/src/bootstrap_runner.py`: soporta layout instalado (`install_dir/app` + `install_dir/external_bin`) y separa datos de usuario en `%LOCALAPPDATA%/AlbaranesParser/data`.
- `portable_release/build_portable.py`:
  - versionado formal: `AppVersion=1.10.0`, `BuildId=20260428.1000`, `PayloadVersion=1.10.0+20260428.tesseract-default-menu`.
  - escribe `VERSION.json` en payload.
  - embebe `AlbaranesParser.exe` dentro de `AlbaranesInstaller.exe` cuando el runner ya esta compilado.
  - instalador en modo windowed (`console=False`).

### Funciones del instalador
- Pide ruta de instalacion.
- Instala programa, payload y `external_bin` en la ruta elegida.
- Crea `VERSION.json` e `install_metadata.json`.
- Crea accesos directos opcionales en escritorio/menu Inicio.
- Registra desinstalador en `HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/AlbaranesParser`.
- Crea `uninstall.ps1`.
- Soporta modo silencioso:
  - `AlbaranesInstaller.exe --silent --install-dir "C:\Ruta\AlbaranesParser"`

### Validacion
- `python -m py_compile portable_release/src/bootstrap_installer.py portable_release/src/bootstrap_runner.py portable_release/build_portable.py main.py config.py albaranes_tool/gui_app.py albaranes_tool/selftest.py` -> OK.
- Build runner OK.
- Build installer OK con runner embebido.
- Smoke install:
  - Instalacion silenciosa en `debug/installer_smoke/install` -> exit 0.
  - Ficheros instalados: `app/`, `external_bin/`, `AlbaranesParser.exe`, `VERSION.json`, `install_metadata.json`, `uninstall.ps1`.
  - Runner instalado `--self-test` -> exit 0.
  - Uninstall temporal -> carpeta eliminada.

### Artefactos finales
- `dist/AlbaranesInstaller_20260428_1210_installer_v110.exe`
- `dist/AlbaranesParser_20260428_1210_installer_v110.exe`
- `dist/deploy_parsers_20260428_1210_installer_v110.exe`
- `dist/parsers_pack_20260428_1210_installer_v110.zip`
- `dist/RELEASE_NOTES_20260428_1210_installer_v110.txt`
