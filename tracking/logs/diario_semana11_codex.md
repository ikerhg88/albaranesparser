# Diario SEMANA_11 Codex

## 2026-04-30 - Nuevos proveedores y reduccion de errores

### Baseline

- Entrada: `Albaranes_Pruebas/SEMANA_11`.
- PDF: `14-04-26 SEM 11.pdf`.
- Master corregido: `albaranes_master_corregido.xlsx`.
- Run inicial: `albaranes_master_run_sem11_baseline.xlsx`.
- Comparacion inicial: 51 errores criticos en 32 filas.

### Proveedores Nuevos

- `HILTI`: parser nuevo `parsers/hilti.py`.
- `ESMERALDA`: parser nuevo `parsers/esmeralda.py`.
- `AUTOMATION24`: parser nuevo `parsers/automation24.py`.

### Cambios Aplicados

- Deteccion: retirado `943557900` como alias de BERDIN porque es telefono del cliente y causaba falsos positivos.
- GABYL: aliases OCR (`GABVL`, `6ABVL`) y fallback con `Total neto` si la linea OCR no es parseable.
- SIMON: packing list con numero de bulto antes del codigo.
- LEYCOLAN: parser multilinea para articulos sin importe.
- TXOFRE: codigos alfabeticos y reconstruccion `R.C.` + fecha.
- ELEKTRA: `S/Pedido` tipo `H260226` y `A100326/H [WEB]`.
- ALKAIN: pedido corto `26.001` tras linea de articulo.
- SALTOKI: lineas solo-cantidad sin inventar precio/importe, salvo albaran de una sola linea.
- SEMEGA: precios por 100 unidades y cantidad real cuando aparece un numero descriptivo antes de cantidad.
- BERDIN: primera columna textual en cabecera `Su Pedido`.
- ELICETXE: importe `0,00` cuando precio `0` no trae importe explicito.
- Configuracion: reglas `SuPedidoCodigo` para `HILTI` y pedidos textuales cortos de `BERDIN`.

### Evolucion SEMANA_11

| Iteracion | Errores criticos | Filas con error |
|---|---:|---:|
| baseline | 51 | 32 |
| iter1 | 34 | 22 |
| iter2 | 18 | 18 |
| iter3 | 5 | 5 |
| iter4 | 4 | 4 |
| iter5 | 2 | 2 |
| iter6 | 1 | 1 |

### Residual Final

| Proveedor | Pagina | Campo | Detectado | Esperado | Decision |
|---|---:|---|---:|---:|---|
| BERDIN | 53 | Importe | 19.64 | 58.91 | No parcheado: el PDF muestra linea y pie con `19,64`; `58,91` parece correccion manual no soportada por evidencia del documento. |

### Controles

| Semana | Errores criticos | Filas con error |
|---|---:|---:|
| SEMANA_05 | 13 | 10 |
| SEMANA_06 | 27 | 12 |
| SEMANA_07 | 11 | 8 |
| SEMANA_09 | 7 | 4 |
| SEMANA_10 | 6 | 6 |
| SEMANA_11 | 1 | 1 |

### Artefactos

- `debug/sem11_iter6_summary.csv`
- `debug/sem11_iter6_detail.csv`
- `Albaranes_Pruebas/SEMANA_11/albaranes_master_run_sem11_iter6.xlsx`
- `debug/control_semana_05_sem11_changes_summary.csv`
- `debug/control_semana_06_sem11_changes_summary.csv`
- `debug/control_semana_07_sem11_changes_summary.csv`
- `debug/control_semana_09_sem11_changes_summary.csv`
- `debug/control_semana_10_sem11_changes_summary.csv`

### Validacion

- `python -m py_compile main.py config.py parsers/*.py`
- `python -m pytest`: 21 passed.
- Runs y comparativas de SEMANA_05, SEMANA_06, SEMANA_07, SEMANA_09, SEMANA_10 y SEMANA_11.
