@echo off
REM Empaqueta el actualizador en un exe portátil.
REM Requisitos: pyinstaller instalado (pip install --user pyinstaller).

set SRC=scripts\deploy_parsers.py
set NAME=deploy_parsers

python -m PyInstaller --onefile --clean --name %NAME% %SRC%

echo.
echo Resultado esperado: dist\%NAME%.exe
