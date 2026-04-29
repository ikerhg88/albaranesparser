# OCR Y Diagnostico

## Configuracion Recomendada

Default actual:

- `OCR automatico`
- Tesseract activo
- preprocesado activo
- `psm=11`
- sin `secondary_psm`
- `ocr_force_all=false`

Esta configuracion fue elegida tras comparar combinaciones en `SEMANA_10`: mantiene el minimo de errores criticos conocido y evita regresiones de importe.

## Motores OCR

Operativo:

- Tesseract

No operativo en esta version:

- OCRmyPDF
- Doctr

Por eso no aparecen en el menu de la GUI. Las claves internas siguen existiendo en `config.py` con `enabled=false` por compatibilidad con configuraciones antiguas.

## Diagnostico De Instalacion

Ejecutar:

```powershell
python main.py --self-test
```

O desde instalacion:

```powershell
AlbaranesParser.exe --self-test
```

Comprueba:

- ruta de Tesseract;
- `tesseract --version`;
- idiomas disponibles;
- OCR de imagen sintetica;
- PDF sintetico de prueba;
- pipeline real contra ese PDF;
- presencia/version de paquetes Python relevantes.

Archivos generados:

```text
debug/installation_selftest/<timestamp>/installation_selftest_report.txt
debug/installation_selftest/<timestamp>/installation_selftest_report.json
debug/installation_selftest/<timestamp>/packages.csv
debug/installation_selftest/<timestamp>/pipeline_selftest_output.xlsx
debug/installation_selftest/ULTIMO_DIAGNOSTICO.txt
debug/installation_selftest/ULTIMO_DIAGNOSTICO.json
debug/installation_selftest/ULTIMA_CARPETA_DIAGNOSTICO.txt
```

## Interpretacion

Un self-test OK significa que Tesseract y el pipeline basico funcionan. No significa que todos los proveedores historicos tengan cero discrepancias contra masters manuales.

Para discrepancias reales, usar comparacion de semana contra `albaranes_master_corregido.xlsx` y revisar detalle por proveedor, pagina y campo.

## Reglas Operativas

- No activar `Forzar OCR siempre` salvo prueba puntual.
- Si una pagina tiene texto embebido fiable, preferir texto base.
- Si OCR empeora importes o codigos, conservar default automatico.
- No hardcodear paginas ni valores de master.
