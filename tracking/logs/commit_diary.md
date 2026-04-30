# Diario Por Commit

Este archivo resume cada commit de `main` con intencion, cambios, validacion e impacto.
Debe actualizarse antes de cerrar cualquier commit nuevo.

### a3d17e8 - Initial import of Albaranes Parser

- Fecha: 2026-04-29T07:38:35+02:00
- Autor: codexikerhg
- Tipo: importacion inicial
- Resumen: primera subida del proyecto a GitHub con parsers, pipeline principal, GUI, self-test, scripts de despliegue, tests y historico operativo existente.
- Validacion: revision de alcance antes del commit para excluir `.venv`, `debug`, `dist`, `Albaranes_Pruebas`, binarios y artefactos generados mediante `.gitignore`.
- Impacto/Riesgo: establece la linea base versionada; no cambia comportamiento funcional respecto al estado local previo.
- Archivos:
  - `.gitignore`
  - `AGENT.md`
  - `README.md`
  - `README_codex.md`
  - `SETUP_WINDOWS.md`
  - `albaranes_tool/__init__.py`
  - `albaranes_tool/gui_app.py`
  - `albaranes_tool/ocr_stage.py`
  - `albaranes_tool/selftest.py`
  - `common.py`
  - `config.py`
  - `debugkit.py`
  - `install_simple.bat`
  - `main.py`
  - `parsers/__init__.py`
  - `parsers/_vendor_simple.py`
  - `parsers/adarra.py`
  - `parsers/aelvasa.py`
  - `parsers/alkain.py`
  - `parsers/araiz.py`
  - `parsers/artesolar.py`
  - `parsers/bacolsa.py`
  - `parsers/balantxa.py`
  - `parsers/basmodec.py`
  - `parsers/berdin.py`
  - `parsers/carandini.py`
  - `parsers/clc.py`
  - `parsers/dataeraser.py`
  - `parsers/efecto_led.py`
  - `parsers/elektra.py`
  - `parsers/elicetxe.py`
  - `parsers/gabyl.py`
  - `parsers/generic.py`
  - `parsers/juper.py`
  - `parsers/leycolan.py`
  - `parsers/lux_may.py`
  - `parsers/saltoki.py`
  - `parsers/semega.py`
  - `parsers/simon.py`
  - `parsers/txofre.py`
  - `parsers/urkunde.py`
  - `portable_release/README.md`
  - `portable_release/build_portable.py`
  - `portable_release/src/bootstrap.py`
  - `portable_release/src/bootstrap_installer.py`
  - `portable_release/src/bootstrap_runner.py`
  - `portable_release/tools/apply_parsers_pack.py`
  - `requirements.txt`
  - `run.bat`
  - `run_config_ui.bat`
  - `scripts/DEPLOY_README.md`
  - `scripts/audit_missing_lines.py`
  - `scripts/build_deploy_exe.bat`
  - `scripts/check_native_libs.py`
  - `scripts/compare_missing_extras.py`
  - `scripts/deploy_parsers.py`
  - `scripts/regression_sem05.py`
  - `scripts/setup_external_bins.py`
  - `settings_manager.py`
  - `tests/test_common.py`
  - `tests/test_parsers_alkain.py`
  - `tests/test_parsers_balantxa.py`
  - `tests/test_parsers_berdin.py`
  - `tests/test_parsers_elicetxe.py`
  - `tests/test_parsers_juper.py`
  - `tests/test_parsers_txofre.py`
  - `tracking/logs/diario_mejoras.md`
  - `tracking/logs/diario_semana09_codex.md`
  - `tracking/logs/policy_log.md`


### dddd7ac - Document project workflow and parser context

- Fecha: 2026-04-29T08:10:45+02:00
- Autor: codexikerhg
- Tipo: documentacion y correccion menor
- Resumen: documenta arquitectura, OCR, release, GitHub, desarrollo de parsers y contexto operativo para agentes. Ajusta Elicetxe para no inventar importe cuando una linea trae precio `0,000` sin importe real.
- Validacion: `python -m py_compile ...` correcto; `python -m pytest` con 21 tests pasados.
- Impacto/Riesgo: mejora mantenibilidad y deja el repo preparado para iteraciones futuras. Riesgo funcional bajo y acotado a Elicetxe.
- Archivos:
  - `AGENTS.md`
  - `README.md`
  - `SETUP_WINDOWS.md`
  - `docs/ARCHITECTURE.md`
  - `docs/GITHUB_WORKFLOW.md`
  - `docs/OCR_AND_DIAGNOSTICS.md`
  - `docs/PARSER_DEVELOPMENT.md`
  - `docs/RELEASE_AND_DEPLOYMENT.md`
  - `parsers/elicetxe.py`
  - `portable_release/README.md`


### 076a1e8 - Classify optional OCR engines as experimental

- Fecha: 2026-04-30T07:52:38+02:00
- Autor: codexikerhg
- Tipo: politica de dependencias OCR
- Resumen: clasifica OCRmyPDF y Doctr como motores experimentales opcionales, los saca de dependencias base y actualiza self-test/documentacion para reportar su estado sin tratarlos como fallo.
- Validacion: `python -m py_compile ...` correcto; `python -m pytest` con 21 tests pasados; `python main.py --self-test` OK con Tesseract operativo y OCRmyPDF/Doctr como `not_installed`.
- Impacto/Riesgo: reduce peso y fragilidad de instalacion normal. Mantiene codigo experimental disponible via `requirements-ocr-experimental.txt`.
- Archivos:
  - `AGENTS.md`
  - `README.md`
  - `SETUP_WINDOWS.md`
  - `albaranes_tool/selftest.py`
  - `docs/OCR_AND_DIAGNOSTICS.md`
  - `requirements-ocr-experimental.txt`
  - `requirements.txt`

