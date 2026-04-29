from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pdfplumber
from PIL import Image, ImageOps


def _project_root() -> Path:
    env_dir = os.environ.get("ALBARANES_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _project_root()


def _win_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    kwargs: dict = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startup
    return kwargs


@dataclass
class OCRArtifacts:
    pdf_path: Path
    text_by_page: Dict[int, str]
    stages: List[str]


def _render_pdf_to_images(pdf_in: Path, dpi: int) -> List[Image.Image]:
    images: List[Image.Image] = []
    with pdfplumber.open(str(pdf_in)) as pdf:
        for page in pdf.pages:
            pil_img = page.to_image(resolution=dpi).original.convert("L")
            images.append(pil_img)
    return images


def _otsu_threshold(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.flatten(), minlength=256)
    total = gray.size
    sum_total = np.dot(np.arange(256), histogram)
    sum_background = 0.0
    weight_background = 0.0
    max_var = -1.0
    threshold = 0
    for t in range(256):
        weight_background += histogram[t]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += t * histogram[t]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        var_between = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = t
    return threshold


def _deskew_image(image: Image.Image) -> Image.Image:
    arr = np.array(image)
    coords = np.column_stack(np.where(arr < 128))
    if coords.size == 0:
        return image
    cov = np.cov(coords, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    principal = eigenvectors[:, np.argmax(eigenvalues)]
    angle = math.degrees(math.atan2(principal[0], principal[1]))
    if abs(angle) < 0.1:
        return image
    return image.rotate(angle, expand=True, fillcolor=255)


def _preprocess_image(image: Image.Image, *, binarize: bool, deskew: bool) -> Image.Image:
    img = ImageOps.autocontrast(image.convert("L"))
    if binarize:
        arr = np.array(img)
        threshold = _otsu_threshold(arr)
        binary = (arr > threshold).astype(np.uint8) * 255
        img = Image.fromarray(binary)
    if deskew:
        img = _deskew_image(img)
    return img


def _prepare_images_for_ocr(pdf_in: Path, preprocess_cfg: dict) -> List[Image.Image]:
    dpi = int(preprocess_cfg.get("dpi", 300) or 300)
    binarize = bool(preprocess_cfg.get("binarize", True))
    deskew = bool(preprocess_cfg.get("deskew", True))
    base_images = _render_pdf_to_images(pdf_in, dpi)
    if not preprocess_cfg.get("enabled", True):
        return [img.convert("L") for img in base_images]
    return [_preprocess_image(img, binarize=binarize, deskew=deskew) for img in base_images]


def _resolve_executable(path: str | None, default_name: str | None, label: str, required: bool = False) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    if candidate.is_dir():
        if default_name:
            candidate = candidate / default_name
        else:
            print(f"[WARN][OCR] {label}: la ruta {candidate} es un directorio.")
            return None
    if not candidate.exists():
        msg = f"No se encontro {label} en: {candidate}"
        if required:
            raise RuntimeError(msg)
        print(f"[WARN][OCR] {msg}")
        return None
    return str(candidate)


def _resolve_tesseract_path(tesseract_cmd: str | None) -> str:
    exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    resolved = _resolve_executable(tesseract_cmd, exe_name, "Tesseract")
    if resolved:
        return resolved
    found = shutil.which(exe_name)
    if found:
        return str(Path(found))
    raise RuntimeError(
        "No se encontro 'tesseract' en el PATH. Instala Tesseract OCR o configura "
        "OCR_CONFIG['ocrmypdf']['tesseract_cmd'] con la ruta correspondiente."
    )


@contextmanager
def _temporary_env(var: str, value: str):
    prev = os.environ.get(var)
    os.environ[var] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = prev


def _normalize_bin_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    norm: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.is_file():
            candidate = candidate.parent
        if not candidate.exists():
            print(f"[WARN][OCR] Ruta de binario no encontrada: {candidate}")
            continue
        resolved = str(candidate)
        if resolved not in seen:
            norm.append(resolved)
            seen.add(resolved)
    return norm


@contextmanager
def _temporary_path_dirs(dirs: list[str]):
    if not dirs:
        yield
        return
    existing = [d for d in dirs if Path(d).exists()]
    if not existing:
        yield
        return
    prev = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(existing + [prev])
    try:
        yield
    finally:
        os.environ["PATH"] = prev


def ensure_searchable(pdf_in: Path | str, cache_dir: Path | str, lang: str = "spa+eng",
                      optimize: int = 2, skip_text: bool = True, clean: bool = False,
                      remove_background: bool = False, tesseract_cmd: str | None = None,
                      binary_paths: list[str] | None = None) -> Path:
    """Genera un PDF con capa de texto usando OCRmyPDF."""
    try:
        import ocrmypdf  # type: ignore
        try:
            from ocrmypdf.exceptions import MissingDependencyError  # type: ignore
        except Exception:  # pragma: no cover - fallback segun version
            MissingDependencyError = Exception  # type: ignore[assignment]
    except ImportError as exc:
        raise RuntimeError("OCRmyPDF no esta instalado (pip install ocrmypdf).") from exc

    pdf_in = Path(pdf_in)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    out_path = cache_dir / pdf_in.name
    if out_path.exists() and out_path.stat().st_mtime >= pdf_in.stat().st_mtime:
        return out_path

    tesseract_path = _resolve_tesseract_path(tesseract_cmd)
    def _run(clean_flag: bool, remove_flag: bool):
        ocrmypdf.ocr(
            str(pdf_in),
            str(out_path),
            language=lang,
            rotate_pages=True,
            deskew=True,
            clean=clean_flag,
            remove_background=remove_flag,
            optimize=optimize,
            skip_text=skip_text,
            progress_bar=False,
        )

    extra_dirs = _normalize_bin_paths(binary_paths)

    with ExitStack() as stack:
        stack.enter_context(_temporary_env("OCRMYPDF_TESSERACT", tesseract_path))
        stack.enter_context(_temporary_path_dirs(extra_dirs))
        try:
            _run(clean, remove_background)
        except MissingDependencyError as exc:  # type: ignore[misc]
            if clean or remove_background:
                print(f"[WARN][OCR] Faltan dependencias para clean/remove_background ({exc}); reintentando sin limpieza.")
                _run(False, False)
            else:
                raise
    return out_path


def ensure_doctr_text(pdf_in: Path | str, cache_dir: Path | str, images: List[Image.Image],
                      detector: str, recognizer: str, use_gpu: bool) -> Dict[int, str]:
    """Reconoce texto por pagina usando python-doctr con preprocesado previo."""
    pdf_in = Path(pdf_in)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"{pdf_in.stem}_doctr.json"
    pdf_mtime = pdf_in.stat().st_mtime

    if cache_file.exists():
        try:
            with cache_file.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if (
                payload.get("source_mtime", 0) >= pdf_mtime
                and payload.get("detector") == detector
                and payload.get("recognizer") == recognizer
            ):
                pages = payload.get("pages", [])
                return {idx + 1: text for idx, text in enumerate(pages) if text}
        except Exception:
            pass

    try:
        from doctr.io import DocumentFile  # type: ignore
        from doctr.models import ocr_predictor  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-doctr no esta instalado (pip install python-doctr[torch]).") from exc

    predictor = ocr_predictor(det_arch=detector, reco_arch=recognizer, pretrained=True)

    if use_gpu:
        try:
            predictor = predictor.cuda()  # type: ignore[attr-defined]
        except Exception:
            predictor = predictor.cpu()  # type: ignore[attr-defined]
    else:
        predictor = predictor.cpu()  # type: ignore[attr-defined]

    page_texts: Dict[int, str] = {}
    processed_pages: List[str] = []

    for page_idx, pil_img in enumerate(images or [], start=1):
        pil_rgb = pil_img.convert("RGB")
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                pil_rgb.save(tmp, format="PNG")
            document = DocumentFile.from_images([str(tmp_path)])
            result = predictor(document)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        exported = result.export()
        page_data = exported.get("pages", [])
        if not page_data:
            processed_pages.append("")
            continue
        blocks = page_data[0].get("blocks", [])
        lines: List[str] = []
        for block in blocks:
            for line in block.get("lines", []):
                words = [word.get("value", "") for word in line.get("words", []) if word.get("value")]
                if words:
                    lines.append(" ".join(words))
        page_text = "\n".join(lines)
        processed_pages.append(page_text)
        if page_text:
            page_texts[page_idx] = page_text

    payload = {
        "source_mtime": pdf_mtime,
        "detector": detector,
        "recognizer": recognizer,
        "pages": processed_pages,
    }
    with cache_file.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return page_texts


def _merge_ocr_variants(primary: str, secondary: str) -> str:
    base = (primary or "").strip()
    alt = (secondary or "").strip()
    if not base:
        return alt
    if not alt or alt in base:
        return base
    lines: List[str] = [ln.strip() for ln in base.splitlines() if ln.strip()]
    seen = set(lines)
    for ln in alt.splitlines():
        clean = ln.strip()
        if not clean or clean in seen:
            continue
        lines.append(clean)
        seen.add(clean)
    return "\n".join(lines)


def ensure_tesseract_text(pdf_in: Path | str, cache_dir: Path | str,
                          images: List[Image.Image], language: str,
                          oem: int, psm: int, cmd: str | None,
                          secondary_psm: int | None = None) -> Dict[int, str]:
    pdf_in = Path(pdf_in)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"{pdf_in.stem}_tesseract.json"
    pdf_mtime = pdf_in.stat().st_mtime

    if cache_file.exists():
        try:
            with cache_file.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if (
                payload.get("source_mtime", 0) >= pdf_mtime
                and payload.get("language") == language
                and int(payload.get("oem", -1)) == int(oem)
                and int(payload.get("psm", -1)) == int(psm)
                and payload.get("secondary_psm") == secondary_psm
            ):
                pages = payload.get("pages", [])
                return {idx + 1: text for idx, text in enumerate(pages) if text}
        except Exception:
            pass

    tess_path = _resolve_tesseract_path(cmd or None)
    page_texts: Dict[int, str] = {}
    collected: List[str] = []

    def _run_tesseract(tmp_path: Path, psm_value: int) -> str:
        proc = subprocess.run(
            [
                tess_path,
                str(tmp_path),
                "stdout",
                "-l",
                language,
                "--oem",
                str(oem),
                "--psm",
                str(psm_value),
            ],
            capture_output=True,
            text=False,
            check=False,
            **_win_subprocess_kwargs(),
        )
        stdout = proc.stdout.decode("utf-8", "ignore") if proc.stdout else ""
        return stdout.strip()

    for page_idx, pil_img in enumerate(images or [], start=1):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            pil_img.save(tmp_path, format="PNG")
        try:
            primary_text = _run_tesseract(tmp_path, int(psm))
            text = primary_text
            if secondary_psm is not None and int(secondary_psm) != int(psm):
                secondary_text = _run_tesseract(tmp_path, int(secondary_psm))
                text = _merge_ocr_variants(primary_text, secondary_text)
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        collected.append(text)
        if text:
            page_texts[page_idx] = text

    payload = {
        "source_mtime": pdf_mtime,
        "language": language,
        "oem": oem,
        "psm": psm,
        "secondary_psm": secondary_psm,
        "pages": collected,
    }
    with cache_file.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return page_texts


def apply_ocr_pipeline(pdf_path: Path | str, config: dict | None) -> OCRArtifacts:
    """Aplica las etapas activas sobre el PDF y devuelve artefactos para el parser."""
    pdf_path = Path(pdf_path)
    if not config:
        return OCRArtifacts(pdf_path=pdf_path, text_by_page={}, stages=[])

    cache_dir = Path(config.get("cache_dir") or "debug/ocr_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    current_path = pdf_path
    stages_run: List[str] = []
    text_by_page: Dict[int, str] = {}

    ocrmypdf_cfg = config.get("ocrmypdf") or {}
    if ocrmypdf_cfg.get("enabled"):
        try:
            stage_dir = cache_dir / "ocrmypdf"
            current_path = ensure_searchable(
                current_path,
                stage_dir,
                lang=ocrmypdf_cfg.get("language", "spa+eng"),
                optimize=int(ocrmypdf_cfg.get("optimize", 2)),
                skip_text=bool(ocrmypdf_cfg.get("skip_text", True)),
                clean=bool(ocrmypdf_cfg.get("clean", False)),
                remove_background=bool(ocrmypdf_cfg.get("remove_background", False)),
                tesseract_cmd=ocrmypdf_cfg.get("tesseract_cmd"),
                binary_paths=ocrmypdf_cfg.get("binary_paths"),
            )
            stages_run.append("ocrmypdf")
        except Exception as exc:
            print(f"[WARN][OCR] Fallo ocrmypdf en {pdf_path.name}: {exc}")

    images: List[Image.Image] | None = None
    doctr_cfg = config.get("doctr") or {}
    tess_cfg = config.get("tesseract") or {}
    preprocess_cfg = config.get("preprocess") or {}

    if doctr_cfg.get("enabled") or tess_cfg.get("enabled"):
        try:
            images = _prepare_images_for_ocr(current_path, preprocess_cfg)
        except Exception as exc:
            print(f"[WARN][OCR] Fallo preparando imagenes para {pdf_path.name}: {exc}")
            images = []

    if doctr_cfg.get("enabled"):
        try:
            stage_dir = cache_dir / "doctr"
            doctr_text = ensure_doctr_text(
                current_path,
                stage_dir,
                images or [],
                detector=str(doctr_cfg.get("detector", "db_resnet50")),
                recognizer=str(doctr_cfg.get("recognizer", "crnn_vgg16_bn")),
                use_gpu=bool(doctr_cfg.get("use_gpu", False)),
            )
            if doctr_text:
                text_by_page.update(doctr_text)
            stages_run.append("doctr")
        except Exception as exc:
            print(f"[WARN][OCR] Fallo Doctr en {pdf_path.name}: {exc}")

    if tess_cfg.get("enabled"):
        try:
            stage_dir = cache_dir / "tesseract"
            tess_text = ensure_tesseract_text(
                current_path,
                stage_dir,
                images or [],
                language=str(tess_cfg.get("language", "spa+eng")),
                oem=int(tess_cfg.get("oem", 1)),
                psm=int(tess_cfg.get("psm", 6)),
                cmd=tess_cfg.get("cmd") or ocrmypdf_cfg.get("tesseract_cmd"),
                secondary_psm=(
                    int(tess_cfg["secondary_psm"])
                    if tess_cfg.get("secondary_psm") is not None
                    else None
                ),
            )
            for page_idx, content in tess_text.items():
                existing = text_by_page.get(page_idx, "")
                if len(content) > len(existing):
                    text_by_page[page_idx] = content
            stages_run.append("tesseract")
        except Exception as exc:
            print(f"[WARN][OCR] Fallo Tesseract en {pdf_path.name}: {exc}")

    return OCRArtifacts(pdf_path=current_path, text_by_page=text_by_page, stages=stages_run)
