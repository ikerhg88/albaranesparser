# Albaranes Parser - Agent Context

## Project Goal

Albaranes Parser extracts structured delivery-note data from supplier PDFs and writes Excel outputs for comparison against corrected masters. The project is maintained through parser iterations, regression checks by week, and Windows release builds.

## Current Baseline

- Release line: `1.10.0`.
- Default OCR strategy: automatic Tesseract OCR with `psm=11` when text extraction is insufficient.
- OCRmyPDF and Doctr are intentionally not exposed in the GUI because they were not reliable in the tested Windows setup.
- Do not hardcode page numbers, delivery-note numbers, supplier-specific one-off values, or master corrections. Prefer reusable parser rules, normalization, and OCR cleanup.

## Important Paths

- `main.py`: CLI processing entry point.
- `albaranes_tool/gui_app.py`: Windows GUI.
- `albaranes_tool/selftest.py`: installation and OCR diagnostics.
- `parsers/`: supplier parsers.
- `tests/`: focused parser and common utility tests.
- `portable_release/`: Windows portable and installer build scripts.
- `docs/`: architecture, OCR, release, GitHub, and parser workflow documentation.

## Non-Versioned Data

Keep generated, private, and heavy artifacts out of Git:

- `Albaranes_Pruebas/`
- `debug/`
- `dist/`
- `build/`
- `archive/`
- `external_bin/`
- `*.pdf`, `*.xlsx`, generated CSVs, and local settings files.

The `.gitignore` already covers these paths. Check `git status --short` before committing.

## Verification Commands

Run these before committing parser or release changes:

```powershell
python -m py_compile main.py config.py albaranes_tool\gui_app.py albaranes_tool\selftest.py portable_release\build_portable.py portable_release\src\bootstrap_installer.py portable_release\src\bootstrap_runner.py
python -m pytest
```

For installer changes, also run a silent install/self-test/uninstall smoke in a temporary folder.

## Parser Iteration Rules

- Compare current outputs against corrected masters using normalized values.
- Report residual errors by provider, field, detected value, expected value, PDF, and page.
- Treat compactation/suffix/cleanup-equivalent values as non-errors when the rule is general and applied consistently.
- Preserve cross-week stability: SEMANA_10 improvements must not regress SEMANA_05, SEMANA_06, SEMANA_07, or SEMANA_09.
- Prefer small supplier-local parser changes unless a shared utility is clearly needed.

## GitHub Workflow

Remote:

```powershell
git remote -v
```

Expected repository:

```text
git@github.com:ikerhg88/albaranesparser.git
```

Use intentional commits with clear messages. Do not commit generated releases or customer PDFs.
