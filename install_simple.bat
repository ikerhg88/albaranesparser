@echo off
setlocal
where py >nul 2>nul || (echo No se encuentra 'py'. Instala Python 3.11 con el Launcher. & pause & exit /b 1)
py -3.11 -m venv .venv || (echo Error creando .venv & pause & exit /b 1)
call .venv\Scripts\activate.bat || (echo No se pudo activar .venv & pause & exit /b 1)
python -m pip install --upgrade pip
set TORCH_EXTRA_INDEX=https://download.pytorch.org/whl/cpu
echo Instalando dependencias (PyPI + %TORCH_EXTRA_INDEX%)...
pip install --extra-index-url %TORCH_EXTRA_INDEX% -r requirements.txt || (echo Error instalando dependencias & pause & exit /b 1)
pip show python-doctr >nul 2>nul || (
    echo Reinstalando python-doctr...
    pip install --extra-index-url %TORCH_EXTRA_INDEX% "python-doctr[torch]==0.8.1" || (echo Error instalando python-doctr & pause & exit /b 1)
)
python scripts\setup_external_bins.py
python scripts\check_native_libs.py
echo Instalacion OK. Usa run.bat para ejecutar.
pause

