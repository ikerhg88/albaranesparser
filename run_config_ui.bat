@echo off
setlocal
call .venv\Scripts\activate.bat
set "PROJ_DIR=%~dp0"
set "GTK_RUNTIME_DIR="
set "GTK_RUNTIME_BASE="
for /d %%G in ("%PROJ_DIR%external_bin\*") do (
    if exist "%%~G\bin\libgobject-2.0-0.dll" (
        set "GTK_RUNTIME_BASE=%%~G"
        set "GTK_RUNTIME_DIR=%%~G\bin"
        goto after_gtk_scan
    )
)
:after_gtk_scan
if defined GTK_RUNTIME_DIR (
    set "PATH=%GTK_RUNTIME_DIR%;%PATH%"
    if exist "%GTK_RUNTIME_BASE%\lib\girepository-1.0" (
        set "GI_TYPELIB_PATH=%GTK_RUNTIME_BASE%\lib\girepository-1.0"
    )
    if exist "%GTK_RUNTIME_BASE%\lib" (
        set "GTK_PATH=%GTK_RUNTIME_BASE%"
    )
)

REM Abre la GUI de configuracion y sale (no procesa PDFs)
python main.py --config-ui
