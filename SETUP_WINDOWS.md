# Instalacion En Windows

## Opcion Recomendada: Instalador

Usa el instalador generado en `dist/`:

```text
AlbaranesInstaller_<version>.exe
```

El instalador:

- pide carpeta de instalacion;
- instala la aplicacion, parsers y binarios OCR integrados;
- crea `VERSION.json` e `install_metadata.json`;
- registra desinstalacion en Windows para el usuario actual;
- crea accesos directos opcionales;
- conserva datos y configuracion entre actualizaciones.

Modo silencioso:

```powershell
AlbaranesInstaller.exe --silent --install-dir "C:\Users\%USERNAME%\AppData\Local\Programs\AlbaranesParser"
```

## Separacion Programa/Datos

La carpeta elegida en el instalador contiene el programa:

```text
<install_dir>\
  AlbaranesParser.exe
  app\
  external_bin\
  VERSION.json
  install_metadata.json
  uninstall.ps1
```

Los datos de trabajo se guardan fuera de la carpeta de programa:

```text
%LOCALAPPDATA%\AlbaranesParser\data
```

La configuracion de usuario se guarda en:

```text
%APPDATA%\AlbaranesParser\config.json
```

Esto permite actualizar el programa sin borrar configuracion, caches, informes ni salidas del usuario.

## Ejecutar Desde Codigo Fuente

Requisitos:

- Windows 10/11
- Python 3.11+
- Tesseract disponible en `external_bin/tesseract/tesseract.exe` o en `PATH`

Instalar dependencias Python:

```powershell
python -m pip install -r requirements.txt
```

Lanzar GUI:

```powershell
python main.py
```

Modo batch:

```powershell
python main.py --in "D:\PDFs" --out "D:\salida\albaranes_master.xlsx" --no-ui
```

Diagnostico:

```powershell
python main.py --self-test
```

## OCR Soportado

El motor OCR soportado en la distribucion actual es Tesseract.

Configuracion por defecto:

- OCR automatico;
- Tesseract activo;
- preprocesado activado;
- `psm=11`;
- sin segunda pasada OCR.

OCRmyPDF y Doctr no se consideran opciones operativas de produccion en esta version y no aparecen en la GUI. El codigo conserva soporte interno experimental con `enabled=false`; las dependencias viven en `requirements-ocr-experimental.txt` para pruebas comparativas, no para instalacion normal.

## Actualizaciones

Ejecuta un instalador nuevo sobre la misma ruta de instalacion. Se reemplaza:

- `app/`
- `external_bin/`
- `AlbaranesParser.exe`
- metadatos de version

No se borra:

- `%LOCALAPPDATA%\AlbaranesParser\data`
- `%APPDATA%\AlbaranesParser\config.json`
- salidas del usuario externas a la carpeta de programa

## Desinstalacion

Desde Windows, usa la entrada de desinstalacion de `Albaranes Parser`.

Tambien puedes ejecutar:

```powershell
powershell.exe -ExecutionPolicy Bypass -File "<install_dir>\uninstall.ps1"
```

La desinstalacion elimina la carpeta del programa y accesos directos. No elimina automaticamente la carpeta de datos del usuario.
