from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DIARY_PATH = Path("tracking/logs/commit_diary.md")
DIARY_ONLY_PATHS = {DIARY_PATH.as_posix(), str(DIARY_PATH)}
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _commits() -> list[dict[str, str]]:
    fmt = FIELD_SEP.join(["%H", "%h", "%ad", "%an", "%s"]) + RECORD_SEP
    raw = _git(["log", "--date=iso-strict", f"--pretty=format:{fmt}", "--reverse"])
    commits: list[dict[str, str]] = []
    for record in raw.split(RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) != 5:
            continue
        full, short, date, author, subject = parts
        commits.append(
            {
                "full": full,
                "short": short,
                "date": date,
                "author": author,
                "subject": subject,
            }
        )
    return commits


def _changed_files(commit: str) -> list[str]:
    raw = _git(["show", "--pretty=format:", "--name-only", commit])
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _is_diary_only_commit(commit: str) -> bool:
    files = _changed_files(commit)
    return bool(files) and all(path.replace("\\", "/") in DIARY_ONLY_PATHS for path in files)


def _existing_text(path: Path) -> str:
    if not path.exists():
        return (
            "# Diario Por Commit\n\n"
            "Este archivo resume cada commit de `main` con intencion, cambios, validacion e impacto.\n"
            "Debe actualizarse antes de cerrar cualquier commit nuevo.\n\n"
        )
    return path.read_text(encoding="utf-8")


def _entry(commit: dict[str, str]) -> str:
    files = _changed_files(commit["full"])
    files_block = "\n".join(f"  - `{path}`" for path in files) if files else "  - Sin cambios de fichero detectados"
    return (
        f"### {commit['short']} - {commit['subject']}\n\n"
        f"- Fecha: {commit['date']}\n"
        f"- Autor: {commit['author']}\n"
        "- Tipo: pendiente de clasificar\n"
        "- Resumen: pendiente de completar\n"
        "- Validacion: pendiente de completar\n"
        "- Impacto/Riesgo: pendiente de completar\n"
        "- Archivos:\n"
        f"{files_block}\n\n"
    )


def update_diary(path: Path) -> tuple[int, list[str]]:
    text = _existing_text(path)
    commits = _commits()
    missing = [
        commit
        for commit in commits
        if f"### {commit['short']} -" not in text and not _is_diary_only_commit(commit["full"])
    ]
    if not missing:
        return 0, []

    additions = "\n".join(_entry(commit) for commit in missing)
    path.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + additions, encoding="utf-8")
    return len(missing), [commit["short"] for commit in missing]


def check_diary(path: Path) -> tuple[bool, list[str]]:
    text = _existing_text(path)
    missing = [
        commit["short"]
        for commit in _commits()
        if f"### {commit['short']} -" not in text and not _is_diary_only_commit(commit["full"])
    ]
    return not missing, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantiene tracking/logs/commit_diary.md con una entrada por commit.")
    parser.add_argument("--check", action="store_true", help="Falla si falta algun commit en el diario.")
    parser.add_argument("--path", default=str(DIARY_PATH), help="Ruta del diario Markdown.")
    args = parser.parse_args()

    path = Path(args.path)
    if args.check:
        ok, missing = check_diary(path)
        if ok:
            print(f"OK: diario completo en {path}")
            return 0
        print("Faltan commits en el diario: " + ", ".join(missing), file=sys.stderr)
        return 1

    count, added = update_diary(path)
    if count:
        print(f"Anadidas {count} entradas: {', '.join(added)}")
    else:
        print(f"OK: no faltan entradas en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
