# Puesta en marcha en Windows

Este proyecto usa OCRmyPDF y python-doctr con varias utilidades externas. Para mantener todo autocontenido, se ha preparado la carpeta `external_bin/` en la raiz del repositorio. Copia dentro de ella los binarios indicados a continuacion y ajusta `config.py` solo si cambias las rutas.

## 1. Dependencias de Python
> Nota: `pip install ocrmypdf` (incluido en `requirements.txt`) instala el paquete Python, pero no los ejecutables externos que OCRmyPDF necesita en Windows. Las secciones siguientes detallan como anadirlos de forma portable.


1. Instala Python 3.11 o superior (con `pip`).
2. Dentro del entorno del proyecto, instala las librerias:
   ```powershell
   pip install -r requirements.txt
   ```
3. python-doctr necesita PyTorch. El fichero `requirements.txt` ya incluye `torch`, `torchvision` y `torchaudio`.
   - En la mayoria de entornos bastara con:
     ```powershell
     pip install -r requirements.txt
     ```
   - Si algun wheel no esta disponible en tu indice por defecto, repite la instalacion usando el indice oficial de PyTorch:
     ```powershell
     pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
     ```

## 2. Binarios externos (carpeta `external_bin/`)
> El script `install_simple.bat` lanza automaticamente `python scripts/setup_external_bins.py` para descargar o actualizar pngquant, ffmpeg y unpaper. Ejecutalo tras clonar (o cuando quieras refrescar estos binarios) para mantenerlos al dia.

| Herramienta      | Uso en OCRmyPDF                     | Descarga recomendada                                                | Carpeta objetivo                     |
|------------------|-------------------------------------|---------------------------------------------------------------------|--------------------------------------|
| Tesseract        | Reconocimiento de texto principal   | https://github.com/UB-Mannheim/tesseract/wiki                       | `external_bin/tesseract/`            |
| Ghostscript      | Renderizado PDF                     | https://ghostscript.com/releases/gsdnld.html                        | `external_bin/ghostscript/bin/`      |
| QPDF             | Manipulacion de PDFs                | https://github.com/qpdf/qpdf/releases (zip para Windows)            | `external_bin/qpdf/bin/`             |
| pngquant         | Optimizacion ligera (`--optimize 1`) | https://pngquant.org/pngquant-windows.zip                           | `external_bin/pngquant/`             |
| (Opcional) ffmpeg| Requisito de unpaper                | https://www.gyan.dev/ffmpeg/builds/ (ZIP "essentials")              | `external_bin/ffmpeg/`               |
| (Opcional) unpaper | Limpieza de fondo (`clean=True`) | https://github.com/unpaper/unpaper/releases                         | `external_bin/unpaper/` (si se usa)  |

### Pasos sugeridos

1. **Tesseract**: instala la version 5.3.x para Windows (instalador UB Mannheim). Durante la instalacion marca el paquete de idioma **Spanish (spa)** y luego copia todo el contenido de `Tesseract-OCR` a `external_bin/tesseract/` para tener `external_bin/tesseract/tesseract.exe`.
2. **Ghostscript**: descarga el instalador oficial (`gs100**w64.exe`). Tras instalar, copia la carpeta `bin` resultante a `external_bin/ghostscript/bin/`. Necesitamos `gswin64c.exe` disponible alli.
3. **QPDF**: descarga el ZIP (`qpdf-*.zip`), extrae y copia la subcarpeta `bin` en `external_bin/qpdf/bin/`. Verifica que `qpdf.exe` queda dentro.
4. **pngquant**: extrae `pngquant.exe` y copialo a `external_bin/pngquant/`.
5. (Opcional) **ffmpeg**: descarga el paquete ZIP "essentials" (64-bit) desde https://www.gyan.dev/ffmpeg/builds/, extrae la carpeta `bin` completa y colocala en `external_bin/ffmpeg/bin/`.
6. (Opcional) **unpaper**: descarga el release oficial (`unpaper-*-windows.zip`) en https://github.com/unpaper/unpaper/releases, extrae `unpaper.exe` y las DLL asociadas (libbz2-1.dll, libwinpthread-1.dll, zlib1.dll). Copia todos esos archivos a `external_bin/unpaper/`. Unpaper invoca ffmpeg para entrada/salida, por lo que asegurate de tener `ffmpeg.exe` accesible (ver paso anterior).
7. Revisa que cada carpeta contenga el `.exe` correspondiente; si cambias la ruta, actualiza `config.py`.

> Prefieres instalar los binarios de forma global?
> - Con **winget** (PowerShell con privilegios de administrador):  
>   `winget install -e --id Python.Python.3.11`  
>   `winget install -e --id UB-Mannheim.TesseractOCR`  
>   Luego descarga e instala Ghostscript manualmente desde https://ghostscript.com/releases/gsdnld.html.  
> - Con **Chocolatey**:  
>   `choco install python3`  
>   `choco install --pre tesseract`  
>   `choco install pngquant` (opcional)  
>   Descarga e instala Ghostscript desde su instalador oficial.
> En ambos casos deberas asegurarte de que Ghostscript, QPDF y los demas binarios esten presentes; la opcion de carpeta `external_bin/` suele ser mas facil de trasladar entre equipos.

## 3. Configuracion (`config.py`)

La seccion `OCR_CONFIG["ocrmypdf"]` queda preparada para buscar en `external_bin/`:

```python
OCR_CONFIG = {
    "cache_dir": "debug/ocr_cache",
    "ocrmypdf": {
        "enabled": True,
        "language": "spa+eng",
        "optimize": 0,
        "skip_text": True,
        "clean": False,
        "remove_background": False,
        "tesseract_cmd": "external_bin/tesseract/tesseract.exe",
        "binary_paths": [
            "external_bin/pngquant",
            "external_bin/qpdf/bin",
            "external_bin/ghostscript/bin",
            "external_bin/unpaper",
            "external_bin/ffmpeg/bin",
        ],
    },
    # ...
}
```

Ajusta las rutas si decides colocar los binarios en otro sitio. Si un directorio no existe, el codigo mostrara un aviso y seguira sin anadirlo al `PATH`.

## 4. Verificaciones rapidas

Despues de copiar los binarios:

```powershell
# Desde PowerShell, en la raiz del proyecto
./external_bin/tesseract/tesseract.exe --version
./external_bin/qpdf/bin/qpdf.exe --version
./external_bin/ghostscript/bin/gswin64c.exe --version
./external_bin/pngquant/pngquant.exe --version
```

Luego, desde tu entorno Python:
```powershell
python -c "import ocrmypdf, pathlib; print('ocrmypdf', ocrmypdf.__version__)"
```

Si todos responden correctamente, puedes ejecutar el extractor y OCRmyPDF utilizara esos binarios sin necesidad de modificar el `PATH` global del sistema.

## 5. Notas adicionales

- Si activas `clean` o `remove_background`, asegurate de anadir la ruta de `unpaper` a `binary_paths` o instalarlo globalmente.
- python-doctr puede aprovechar GPU si tienes CUDA funcionando; actualiza `config.py` (`use_gpu=True`) y asegurate de instalar PyTorch con soporte CUDA.
- Asegurate de que Tesseract tenga instalados los datos de idioma que uses (por defecto se espera `spa`; puedes anadir `eng` u otros desde el instalador o copiando los ficheros `.traineddata`).
- Cuando actualices alguno de los binarios, bastara con reemplazar los archivos en `external_bin/`.
- Para simplificar despliegues en otras maquinas, documenta el contenido de `external_bin/` segun las licencias correspondientes.

## 6. Dependencias GTK y WeasyPrint

Doctr (via `pygobject`) y WeasyPrint necesitan las bibliotecas de GTK/Pango/Cairo en Windows. Sin ellas veras avisos como:

```
[WARN][OCR] cannot load library 'libgobject-2.0-0'
WeasyPrint could not import some external libraries...
```

### Opcion recomendada (GTK Runtime portable)

1. Descarga el **GTK3 Runtime 64-bit** desde la pagina oficial del mantenedor:  
   https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases (elige la version mas reciente `gtk3-runtime-*-win64.exe`).
2. Ejecuta el instalador con la opcion **Custom** y define como carpeta destino algo portable dentro de `external_bin/`, por ejemplo `external_bin\GTK3-Runtime Win64`. La estructura resultante deberia ser similar a la captura (`bin`, `etc`, `gtk3-runtime`, `lib`, ...).
   - Si prefieres linea de comandos silenciosa:  
     ```
     gtk3-runtime-*.exe /VERYSILENT /NORESTART /DIR="D:\ProgramasLoyola\gtk3-runtime"
     ```
3. No es obligatorio renombrar la carpeta: tanto `run.bat` como `scripts/check_native_libs.py` buscan automaticamente cualquier subcarpeta bajo `external_bin` que contenga `libgobject-2.0-0.dll` en su `bin`. Si prefieres una ruta explicita, puedes copiar (o hacer un enlace simbólico) a `external_bin/gtk/bin`, quedando:
   ```
   external_bin/
     gtk/
       bin/
         libgobject-2.0-0.dll
         libglib-2.0-0.dll
         libcairo-2.dll
         libpango-1.0-0.dll
         ...
   ```
4. Al ejecutar `run.bat` se añadira automaticamente la primera carpeta `...\bin` que contenga `libgobject-2.0-0.dll` al `PATH` del proceso, por lo que no es necesario modificar el PATH global. Si quieres que otras herramientas usen GTK fuera del proyecto, entonces sí conviene añadir esa carpeta permanentemente.
5. Verifica la instalacion:
   ```powershell
   where libgobject-2.0-0.dll
   ```

### Alternativa: instalacion global via MSYS2

1. Instala MSYS2 desde https://www.msys2.org/.
2. Abre una consola `MSYS2 MSYS` y ejecuta:
   ```bash
   pacman -Syu
   pacman -S mingw-w64-x86_64-gtk3 mingw-w64-x86_64-pango mingw-w64-x86_64-cairo
   ```
3. Copia los `.dll` desde `C:\msys64\mingw64\bin\` a `external_bin\gtk\bin` o añade esa carpeta al `PATH`.

### Integracion con el instalador

- `install_simple.bat` lanza `python scripts\check_native_libs.py` para comprobar si `libgobject-2.0-0.dll`, `libpango-1.0-0.dll`, etc. estan accesibles.
- Si falta alguno, el script mostrara un aviso apuntando a esta seccion, pero la instalacion continuara para que puedas completar el paso manualmente.

> Referencias oficiales:  
> - https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation  
> - https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#troubleshooting  


