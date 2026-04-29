# main.py â€” extractor de albaranes multiproveedor con debug unificado y precheck
import argparse
import datetime
import math
import os
import re
import sys
import subprocess
import builtins
import unicodedata
import copy
import json
import logging
import threading
from collections import OrderedDict
from importlib.util import find_spec
from pathlib import Path
from types import MethodType
from settings_manager import load_settings, save_settings


def _patch_subprocess_no_console_windows() -> None:
    if os.name != "nt":
        return
    if getattr(subprocess, "_albaranes_no_console_patch", False):
        return

    original_popen = subprocess.Popen

    def _popen_hidden(*args, **kwargs):
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0) or 0) | int(create_no_window)
        startup = kwargs.get("startupinfo")
        if startup is None:
            startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
        return original_popen(*args, **kwargs)

    subprocess.Popen = _popen_hidden  # type: ignore[assignment]
    subprocess._albaranes_no_console_patch = True  # type: ignore[attr-defined]


_patch_subprocess_no_console_windows()

# ---- Ajustes OMP para evitar warnings al usar OCR/Doctr ----
# ---- Ajustes OMP para evitar warnings al usar OCR/Doctr ----
_OMP_ENV_DEFAULTS = {
    "OMP_NUM_THREADS": "1",
    "KMP_DEVICE_THREAD_LIMIT": "1",
    "KMP_TEAMS_THREAD_LIMIT": "1",
}
for _var, _val in _OMP_ENV_DEFAULTS.items():
    os.environ.setdefault(_var, _val)
os.environ.pop("KMP_ALL_THREADS", None)

import numpy as np
import pandas as pd
import pdfplumber
_FOOTER_KEYWORDS = ("NETO COMERCIAL", "TOTAL (EUR)", "TOTAL ALBARAN", "MUY IMPORTANTE", "HOJA")
_TABLE_HEADER_HINTS = ("POS", "CODIGO", "DESCRIP", "C.PEDIDA", "C.SERVIDA", "IMPORTE")

def _data_dir() -> Path:
    env_dir = os.environ.get("ALBARANES_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path(__file__).resolve().parent



_HOJA_RE = re.compile(r"HOJA\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_ALBARAN_FALLBACK_RE = re.compile(
    r"ALBAR[ÁA]N\s*(?:N[ÚU]M(?:ERO)?\s*[:\-]?\s*)?([A-Z0-9./\-]+)", re.IGNORECASE
)


class PipelineCancelled(Exception):
    """Raised when the user cancels the processing pipeline."""


def _register_windows_dlls():
    if os.name != "nt":
        return
    add_dir = getattr(os, "add_dll_directory", None)
    if add_dir is None:
        return
    base_dir = _data_dir()
    ext_bin = base_dir / "external_bin"
    candidates: set[Path] = set()
    env_hint = os.environ.get("GTK_RUNTIME_DIR")
    if env_hint:
        candidates.add(Path(env_hint))
    typelib_paths: set[str] = set()
    if ext_bin.exists():
        for child in ext_bin.iterdir():
            if not child.is_dir():
                continue
            candidates.add(child)
            candidates.add(child / "bin")
            girepo = child / "lib" / "girepository-1.0"
            if girepo.exists():
                typelib_paths.add(str(girepo))
    path_candidates = os.environ.get("PATH", "").split(os.pathsep)
    for entry in path_candidates:
        if entry:
            candidates.add(Path(entry))
    for folder in sorted(candidates):
        try:
            if not folder.exists():
                continue
            if not any((folder / name).exists() for name in ("libgobject-2.0-0.dll", "libpango-1.0-0.dll")):
                continue
            add_dir(str(folder))
        except (OSError, RuntimeError):
            continue
    if typelib_paths:
        existing = os.environ.get("GI_TYPELIB_PATH")
        merged = list(typelib_paths)
        if existing:
            merged.append(existing)
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(merged)


_register_windows_dlls()


def _normalize_df_types(df):
    import pandas as pd
    if df is None or len(df) == 0:
        return df
    num_cols = ["CantidadPedida","CantidadServida","CantidadPendiente",
                "UnidadesPor","PrecioUnitario","DescuentoPct","Importe",
                "SumaImportesLineas","NetoComercialPie","TotalAlbaranPie"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "ParseWarn" in df.columns:
        df["ParseWarn"] = df["ParseWarn"].astype("string")
    if "FechaAlbaran" in df.columns:
        df["FechaAlbaran"] = df["FechaAlbaran"].astype("string").str.strip()
    return df



def _extract_first(text: str, pats):
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            g = [g for g in m.groups() if g is not None]
            if g:
                return g[0].strip()
            return m.group(0).strip()
    return ""



_FALLBACK_ALBARAN_RE = re.compile(

    r"ALBARAN\s*(?:N(?:UM(?:ERO)?)?|N[º�o])?\s*[:#-]?\s*([A-Z0-9\-/]+)",

    re.IGNORECASE,

)



def _looks_like_albaran_value(token: str | None) -> bool:

    if not token:

        return False

    digits = sum(ch.isdigit() for ch in token)

    return digits >= 5



def _fallback_albaran_from_text(text: str) -> str:

    if not text:

        return ""

    ascii_text = _strip_diacritics(text)

    m = _FALLBACK_ALBARAN_RE.search(ascii_text)

    if m:

        candidate = m.group(1).strip()

        if _looks_like_albaran_value(candidate):

            return candidate

    m_digits = re.search(r"\b\d{6,}\b", ascii_text)

    if m_digits:

        candidate = m_digits.group(0)

        if _looks_like_albaran_value(candidate):

            return candidate

    return ""



def _make_fallback_item(text, proveedor, parser_id, page_num, pdf_name, meta=None):
    # Saca cabecera basica de la pagina para no perder campos criticos.
    from common import parse_date_es, to_float

    meta = meta or {}

    def _meta_float(*keys):
        for key in keys:
            val = meta.get(key)
            if val is None:
                continue
            try:
                num = float(val)
            except Exception:
                continue
            if not math.isnan(num):
                return num
        return None

    albaran = str(meta.get("AlbaranNumero") or "").strip()
    if not _looks_like_albaran_value(albaran):
        albaran = _extract_first(
            text,
            [
                r"ALBAR[AÃ]N\s*(?:N[Âºo]|NUM(?:ERO)?)?\s*[:#-]?\s*([A-Z0-9\-/]+)",
                r"ALB\.?\s*[:#-]?\s*([A-Z0-9\-/]+)",
            ],
        )
    if not _looks_like_albaran_value(albaran):
        fallback_token = _fallback_albaran_from_text(text)
        if _looks_like_albaran_value(fallback_token):
            albaran = fallback_token

    fecha = str(meta.get("FechaAlbaran") or "").strip()
    if not fecha:
        fecha = parse_date_es(text)

    su_pedido = str(meta.get("SuPedidoCodigo") or "").strip()
    if not su_pedido:
        su_pedido = _extract_first(
            text,
            [
                r"SU\s+PEDIDO\s*(?:N[Âºo]|NUM(?:ERO)?)?\s*[:#-]?\s*([A-Z0-9\-/]+)",
                r"N[Âºo]\s*PEDIDO\s*[:#-]?\s*([A-Z0-9\-/]+)",
                r"N[Âºo]\s*CLIENTE\s*[:#-]?\s*([A-Z]{0,3}\d{4,})",
            ],
        )

    importe = None
    text_up = _strip_diacritics(text or "").upper()
    meta_neto = _meta_float("NetoComercialPie")
    meta_total = _meta_float("TotalAlbaranPie")
    if meta_neto is not None and ("NETO COMERCIAL" in text_up or "TOTAL (EUR)" in text_up):
        importe = round(meta_neto, 2)
    elif meta_total is not None and ("TOTAL ALBARAN" in text_up or "IMPORTE TOTAL" in text_up):
        importe = round(meta_total, 2)
    else:
        m_sub = re.search(r"(?:AZPITOTALA|SUBTOTAL)[^0-9]{0,30}(\d{1,3}(?:\.\d{3})*,\d{2})", _strip_diacritics(text or ""), re.I)
        if m_sub:
            importe = to_float(m_sub.group(1))
        elif "NO PARSE" in text_up:
            importe = 0.0
    if importe is None:
        importe = 0.0

    return {
        "Proveedor": proveedor,
        "Parser": parser_id or "fallback",
        "AlbaranNumero": albaran,
        "FechaAlbaran": fecha,
        "SuPedidoCodigo": su_pedido,
        "Descripcion": "NO PARSE - revisar manualmente (fallback)",
        "CantidadPedida": None,
        "CantidadServida": None,
        "CantidadPendiente": None,
        "UnidadesPor": None,
        "PrecioUnitario": None,
        "DescuentoPct": None,
        "Importe": importe,
        "Pagina": page_num,
        "Pdf": pdf_name,
        "ParseWarn": "fallback_no_parse",
    }


def _page_missing_required(items, meta, required_fields):
    if not required_fields:
        return False
    meta = meta or {}
    provider = (meta.get("Proveedor") or "").upper()
    optional = OPTIONAL_REQUIRED_FIELDS.get(provider, set())

    def _value_ok(field, val):
        if val is None:
            return False
        if isinstance(val, str):
            if not val.strip():
                return False
            normalized = re.sub(r"\s+", "", val)
            min_len = CRITICAL_FIELD_MIN_LEN.get(field)
            if min_len and len(normalized) < min_len:
                return False
            return True
        if isinstance(val, float):
            return not math.isnan(val)
        return bool(val)

    for field in required_fields:
        if provider and field in optional:
            continue
        if _value_ok(field, meta.get(field)):
            continue
        field_ok = False
        for row in items or []:
            if _value_ok(field, row.get(field)):
                field_ok = True
                break
        if not field_ok:
            return True
    return False


# GUI opcional (solo para elegir rutas cuando no se pasan por CLI)
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import scrolledtext
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

from common import normalize_spaces
from parsers import detect_proveedor, get_parser_for
from parsers import generic as generic_parser  # Fallback
from config import (
    OCR_CONFIG,
    OCR_REQUIRED_FIELDS,
    OCR_WORKFLOW,
    OCR_DEBUG,
    PRECHECK_ENABLED,
    DEBUG_ENABLED,
    STOP_ON_ERROR,
    NUMERIC_RULES,
    OCR_HEURISTICS,
    SUPEDIDO_RULES,
    SUPEDIDO_TRUNCATED_ENABLED,
    TRACE_OUTPUT,
)  # configuración global
from debugkit import (
    dbg_page_text,
    dbg_detect_result,
    dbg_run_summary,
)
from albaranes_tool.ocr_stage import apply_ocr_pipeline

# ---------------- columnas canÃ³nicas ----------------
DETAIL_COLS = [
    "Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo",
    "Codigo",
    "Descripcion",
    "CantidadPedida", "CantidadServida", "CantidadPendiente", "CantidadFuente",
    "UnidadesPor",
    "PrecioUnitario", "PrecioFuente",
    "DescuentoPct", "DescuentoFuente",
    "Importe", "ImporteFuente",
    "Pagina", "Pdf", "ParseWarn", "OcrStage", "OcrPipeline", "ParseTrace",
]

META_COLS = [
    "Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo",
    "SumaImportesLineas", "NetoComercialPie", "TotalAlbaranPie", "OcrStage", "OcrPipeline",
]

DETAIL_STRING_COLS = {
    "Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo",
    "Codigo", "Descripcion", "Pdf", "ParseWarn", "OcrStage", "OcrPipeline",
    "CantidadFuente", "PrecioFuente", "DescuentoFuente", "ImporteFuente", "ParseTrace",
}
META_STRING_COLS = {
    "Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo",
    "Pdf", "OcrStage", "OcrPipeline"
}

CRITICAL_FIELD_MIN_LEN = {
    "SuPedidoCodigo": 6,
}

_NUMERIC_RULES_CFG = NUMERIC_RULES or {}
_ENFORCE_DISCOUNT_RULES = bool(_NUMERIC_RULES_CFG.get("enforce_discount_formula", False))
_DISCOUNT_TOLERANCE = float(_NUMERIC_RULES_CFG.get("importe_tolerance", 0.05))
_OCR_HEUR_CFG = OCR_HEURISTICS or {}
_OCR_DENSITY_THRESHOLD = float(_OCR_HEUR_CFG.get("density_threshold", 0.0008))
_OCR_MIN_CHARS = int(_OCR_HEUR_CFG.get("min_chars", 120))
_OCR_MIN_LINES = int(_OCR_HEUR_CFG.get("min_lines", 4))
_OCR_MIN_ENTROPY = float(_OCR_HEUR_CFG.get("min_entropy", 0.0))
_SUPEDIDO_VALID_MINLEN = 5


def _clean_supedido(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9./-]", "", str(value).upper())
    return cleaned.strip("/.-")


def _strip_supedido_suffix_noise(value: str | None) -> str:
    """Recorta ruido OCR de cola sin perder sufijos alfabeticos utiles."""
    if not value:
        return ""
    s = re.sub(r"\s+", "", str(value).upper())
    if not s:
        return ""

    # Correcciones OCR en tramos numericos.
    s = re.sub(r"(?<=\d)O(?=\d)", "0", s)
    s = re.sub(r"(?<=\d)[IL](?=\d)", "1", s)

    # Ej: A220126/L519325 -> A220126/L
    m = re.fullmatch(r"([AH]\d{6,8}/[A-Z]{1,4})\d{2,}", s)
    if m:
        return m.group(1)

    # Ej: 26.501/01/H519162 -> 26.501/01/H
    m = re.fullmatch(r"((?:\d{2}\.\d{3}|\d{5})[-/]\d{2,3}[-/][A-Z]{1,4})\d{2,}", s)
    if m:
        return m.group(1)

    return s


def _looks_alpha_suffixed_supedido(value: str | None) -> bool:
    if not value:
        return False
    s = re.sub(r"\s+", "", str(value).upper())
    if not s:
        return False
    return bool(
        re.fullmatch(r"[AH]\d{6,8}/[A-Z]{1,4}(?:\d{0,8})?", s)
        or re.fullmatch(r"[AH]\d{6,8}[A-Z]{1,4}", s)
        or re.fullmatch(r"(?:\d{2}\.\d{3}|\d{5})[-/]\d{2,3}[-/][A-Z]{1,4}(?:\d{0,8})?", s)
    )


def _force_compact_supedido(value: str | None, provider: str | None = None) -> bool:
    """Detecta variantes ruidosas que conviene compactar aunque tengan sufijos."""
    if not value:
        return False
    s = re.sub(r"\s+", "", str(value).upper())
    if not s:
        return False
    prov = (provider or "").upper()
    if prov == "BERDIN" and re.fullmatch(r"(?:[AH]\d{6,8}|\d{2}\.\d{3}|\d{5})/\d{2,3}/IA\d{0,3}", s):
        return True
    if re.fullmatch(r"[AH]-\d{2}/\d{2}/\d{2}", s):
        return True
    return False


def _truncate_supedido_code(value: str | None) -> str:
    """
    Normaliza/trunca SuPedido a formatos compactos:
    - A/H + 6-7 digitos (ej. A2600126, H110226)
    - 5 digitos o 5 digitos/2 digitos (ej. 26001, 26001/01)
    Nota: el sufijo alfabetico (/Y, /H, etc.) no se conserva en truncado.
    """
    if not value:
        return ""
    raw = str(value).upper().strip()
    if not raw:
        return ""
    s = re.sub(r"\s+", "", raw)
    s = s.replace("\\", "/").replace("_", "/").replace("-", "/")
    s = re.sub(r"/+", "/", s).strip("/")
    # OCR comun en bloques numericos
    s = re.sub(r"(?<=\d)[O](?=\d)", "0", s)
    s = re.sub(r"(?<=\d)[IL](?=\d)", "1", s)

    # Formato A/H + digitos (acepta sufijos OCR tipo ...L/-ROBISON, pero
    # conserva solo el bloque numerico principal).
    m = re.search(r"\b([AH])[./-]*([A-Z0-9]{6,16})(?=[^A-Z0-9]|$)", s)
    if m:
        pref = m.group(1)
        tail = m.group(2)
        md = re.match(r"\d{6,8}", tail)
        if md:
            return f"{pref}{md.group(0)}"
        # Fallback OCR: O/I/L confundidos dentro del bloque numerico.
        tail_norm = tail.replace("O", "0").replace("I", "1").replace("L", "1")
        md = re.match(r"\d{6,8}", tail_norm)
        if md:
            return f"{pref}{md.group(0)}"

    def _tail_two_digits(tail_raw: str | None) -> str | None:
        if not tail_raw:
            return None
        t = (
            tail_raw.upper()
            .replace("O", "0")
            .replace("I", "1")
            .replace("L", "1")
        )
        if not re.fullmatch(r"\d{1,3}", t):
            return None
        return t[-2:].rjust(2, "0")

    # Variante fusionada: 25.62501/E  ->  25625/01
    m = re.search(r"(?<!\d)(\d{2})\.(\d{5})(?:/([A-Z0-9]{1,4}))?(?!\d)", s)
    if m:
        core = f"{m.group(1)}{m.group(2)[:3]}"
        return f"{core}/{m.group(2)[3:5]}"

    # Formato obra: 2+3 digitos (con o sin separador) y bloque opcional numerico
    m = re.search(r"(?<!\d)(\d{2})[./-](\d{3})(?:/([A-Z0-9]{1,4}))?(?!\d)", s)
    if m:
        core = f"{m.group(1)}{m.group(2)}"
        tail = _tail_two_digits(m.group(3))
        return f"{core}/{tail}" if tail else core

    m = re.search(r"(?<!\d)(\d{5})(?:/([A-Z0-9]{1,4}))?(?!\d)", s)
    if m:
        core = m.group(1)
        tail = _tail_two_digits(m.group(2))
        return f"{core}/{tail}" if tail else core

    # Fallback: primer bloque de 5-7 digitos
    t = s.replace(".", "")
    m = re.search(r"(?<!\d)\d{5,7}(?!\d)", t)
    if m:
        d = m.group(0)
        if len(d) >= 7:
            return f"{d[:5]}/{d[5:7]}"
        return d[:5]
    return ""


def _normalize_supedido_field(container: dict | None, provider: str | None = None) -> None:
    if not container:
        return
    raw = container.get("SuPedidoCodigo")
    cleaned = _clean_supedido(raw)
    prov_key = (provider or container.get("Proveedor") or "").upper()
    raw_txt = normalize_spaces(str(raw or "")).upper()
    rules = SUPEDIDO_RULES.get(prov_key, SUPEDIDO_RULES.get("_default", {}))
    no_truncate = bool(rules.get("no_truncate", False))
    if prov_key == "TXOFRE":
        if re.search(r"\bLIS[ _-]*TELEFONO\b", raw_txt):
            cleaned = "LIS TELEFONO"
        elif re.search(r"\bTELEFONO[ _-]*LIS\b", raw_txt):
            cleaned = "TELEFONO LIS"
    elif cleaned:
        cleaned = _strip_supedido_suffix_noise(cleaned)
        m_compact = re.fullmatch(r"([AH])[-/](\d{2})/(\d{2})/(\d{2})", cleaned)
        if m_compact:
            cleaned = f"{m_compact.group(1)}{m_compact.group(2)}{m_compact.group(3)}{m_compact.group(4)}"

    if cleaned and bool(rules.get("strip_leading_one_6d", False)):
        digits_only = re.sub(r"\D", "", cleaned)
        if len(digits_only) == 6 and digits_only.startswith("1") and not re.search(r"[A-Z]", cleaned):
            cleaned = digits_only[1:]

    if SUPEDIDO_TRUNCATED_ENABLED and not no_truncate:
        has_alpha = any(ch.isalpha() for ch in cleaned)
        has_sep = any(ch in "/.-" for ch in cleaned)
        preserve_alpha_suffix = has_alpha and (has_sep or _looks_alpha_suffixed_supedido(cleaned))
        preserve_alpha_cfg = rules.get("preserve_alpha_suffix", None)
        if preserve_alpha_cfg is not None:
            preserve_alpha_suffix = preserve_alpha_suffix and bool(preserve_alpha_cfg)
        force_compact = _force_compact_supedido(cleaned, prov_key)
        if prov_key == "BERDIN" and re.fullmatch(r"[AH]\d{6,8}/IA1OCR", cleaned):
            cleaned = cleaned[:-3]
            preserve_alpha_suffix = True
            force_compact = False
        elif (
            prov_key == "BERDIN"
            and re.fullmatch(r"[AH]\d{6,8}/IA1", cleaned)
            and "berdin_bang_ia1" in str(container.get("ParseWarn") or "").lower()
        ):
            preserve_alpha_suffix = True
            force_compact = False
        if force_compact or (not preserve_alpha_suffix):
            truncated = _truncate_supedido_code(cleaned)
            if truncated:
                cleaned = truncated

    min_len = max(int(rules.get("min_length", _SUPEDIDO_VALID_MINLEN)), 1)
    min_digits = max(int(rules.get("min_digits", 2)), 0)
    require_alpha = bool(rules.get("require_alpha", False))
    allow_numeric = bool(rules.get("allow_numeric", False))

    if not cleaned or len(cleaned) < min_len:
        container["SuPedidoCodigo"] = ""
        return

    digits = sum(ch.isdigit() for ch in cleaned)
    letters = sum(ch.isalpha() for ch in cleaned)
    has_sep = any(ch in "/.-" for ch in cleaned)
    is_truncated_compact = bool(
        SUPEDIDO_TRUNCATED_ENABLED
        and re.fullmatch(r"(?:[AH]\d{6,7}|\d{5}(?:/\d{2})?)", cleaned)
    )

    if digits < min_digits:
        container["SuPedidoCodigo"] = ""
        return
    if require_alpha and letters == 0:
        container["SuPedidoCodigo"] = ""
        return
    if letters == 0 and not has_sep and not allow_numeric and not is_truncated_compact:
        container["SuPedidoCodigo"] = ""
        return

    container["SuPedidoCodigo"] = cleaned


def _normalize_key_token(value: object) -> str:
    token = normalize_spaces(str(value or "")).upper()
    if not token:
        return ""
    return re.sub(r"[^A-Z0-9]", "", token)


def _repair_crosspage_header_keys(rows: list[dict]) -> None:
    """Impute weak fallback headers from consistent peer rows in the same run."""
    if not rows:
        return

    by_provider_sup: dict[tuple[str, str], dict[str, int]] = {}
    by_provider_alb: dict[tuple[str, str], dict[str, int]] = {}
    provider_prefix_counts: dict[str, dict[str, int]] = {}

    def _is_phone_like_albaran(albaran: str) -> bool:
        digits = re.sub(r"\D", "", albaran or "")
        return len(digits) == 9 and digits.startswith(("943", "944", "945", "946", "947", "948", "949"))

    def _prefix2(albaran: str) -> str:
        digits = re.sub(r"\D", "", albaran or "")
        return digits[:2] if len(digits) >= 2 else ""

    for row in rows:
        prov = _normalize_key_token(row.get("Proveedor"))
        sup = _normalize_key_token(row.get("SuPedidoCodigo"))
        alb = normalize_spaces(str(row.get("AlbaranNumero") or "")).upper()
        if prov and sup and alb:
            key = (prov, sup)
            bucket = by_provider_sup.setdefault(key, {})
            bucket[alb] = bucket.get(alb, 0) + 1
        if prov and alb and sup:
            key2 = (prov, alb)
            bucket2 = by_provider_alb.setdefault(key2, {})
            bucket2[sup] = bucket2.get(sup, 0) + 1
        if prov and alb:
            pref = _prefix2(alb)
            if pref:
                pref_bucket = provider_prefix_counts.setdefault(prov, {})
                pref_bucket[pref] = pref_bucket.get(pref, 0) + 1

    dominant_prefix_by_provider: dict[str, tuple[str, int]] = {}
    for prov, pref_counts in provider_prefix_counts.items():
        if not pref_counts:
            continue
        dominant_prefix_by_provider[prov] = sorted(pref_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]

    best_albaran_by_sup: dict[tuple[str, str], str] = {}
    for key, counts in by_provider_sup.items():
        if not counts:
            continue
        prov_key, _sup_key = key
        ranked = sorted(
            counts.items(),
            key=lambda kv: (
                _is_phone_like_albaran(kv[0]),
                -kv[1],
                -provider_prefix_counts.get(prov_key, {}).get(_prefix2(kv[0]), 0),
                -len(re.sub(r"\D", "", kv[0])),
            ),
        )
        if len(ranked) == 1:
            best_albaran_by_sup[key] = ranked[0][0]
            continue
        top, second = ranked[0], ranked[1]
        prefer_top = top[1] >= (second[1] + 1)
        if (not prefer_top) and top[1] == second[1]:
            prefer_top = (not _is_phone_like_albaran(top[0])) and _is_phone_like_albaran(second[0])
        if prefer_top:
            best_albaran_by_sup[key] = ranked[0][0]

    best_sup_by_albaran: dict[tuple[str, str], str] = {}
    for key, counts in by_provider_alb.items():
        if not counts:
            continue
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        if len(ranked) == 1 or ranked[0][1] >= (ranked[1][1] + 1):
            best_sup_by_albaran[key] = ranked[0][0]

    for row in rows:
        prov = _normalize_key_token(row.get("Proveedor"))
        sup = _normalize_key_token(row.get("SuPedidoCodigo"))
        alb = normalize_spaces(str(row.get("AlbaranNumero") or "")).upper()
        warn = str(row.get("ParseWarn") or "")

        if prov and sup:
            target_alb = best_albaran_by_sup.get((prov, sup), "")
            if target_alb and target_alb != alb:
                current_digits = re.sub(r"\D", "", alb)
                current_prefix = _prefix2(alb)
                target_prefix = _prefix2(target_alb)
                current_count = by_provider_sup.get((prov, sup), {}).get(alb, 0)
                target_count = by_provider_sup.get((prov, sup), {}).get(target_alb, 0)
                dominant_prefix, dominant_hits = dominant_prefix_by_provider.get(prov, ("", 0))
                current_prefix_hits = provider_prefix_counts.get(prov, {}).get(current_prefix, 0)
                target_prefix_hits = provider_prefix_counts.get(prov, {}).get(target_prefix, 0)
                prefix_outlier = bool(
                    dominant_prefix
                    and dominant_hits >= 3
                    and current_prefix
                    and current_prefix != dominant_prefix
                    and current_prefix_hits <= 1
                )
                weak_current = (
                    "compact_rescue" in warn
                    or len(current_digits) < 7
                    or _is_phone_like_albaran(alb)
                    or prefix_outlier
                )
                stronger_target = target_count > current_count
                tie_break_target = (
                    target_count == current_count
                    and _is_phone_like_albaran(alb)
                    and not _is_phone_like_albaran(target_alb)
                )
                prefix_recover = (
                    target_count >= current_count
                    and target_prefix_hits > current_prefix_hits
                    and (
                        not dominant_prefix
                        or target_prefix == dominant_prefix
                    )
                )
                if weak_current and (stronger_target or tie_break_target or prefix_recover):
                    row["AlbaranNumero"] = target_alb
                    alb = target_alb

        if prov and alb:
            target_sup = best_sup_by_albaran.get((prov, alb), "")
            if target_sup and not sup:
                row["SuPedidoCodigo"] = target_sup


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


def _effective_quantity(row: dict) -> float:
    for key in ("CantidadServida", "CantidadPedida", "CantidadPendiente"):
        qty = _to_float(row.get(key))
        if qty and qty > 0:
            return qty
    return 1.0


def _normalize_numeric_row(row: dict) -> None:
    if not _ENFORCE_DISCOUNT_RULES:
        return
    stage = (row.get("OcrStage") or "").lower()
    default_source = "ocr" if "ocr" in stage else "base"

    def _ensure_source(key: str, value) -> None:
        col = f"{key}Fuente"
        if not row.get(col):
            row[col] = default_source if value is not None else ""

    price = _to_float(row.get("PrecioUnitario"))
    discount = _to_float(row.get("DescuentoPct"))
    importe = _to_float(row.get("Importe"))
    qty = _effective_quantity(row)

    _ensure_source("Precio", price)
    _ensure_source("Descuento", discount)
    _ensure_source("Importe", importe)
    _ensure_source("Cantidad", qty if qty else None)

    existing_warn = row.get("ParseWarn") or ""
    warn_tokens = [token for token in existing_warn.split(";") if token]
    warn_set = set(warn_tokens)

    trace = {
        "precio": {
            "source": row.get("PrecioFuente") or default_source,
            "original": price,
            "status": "missing" if price is None else "ok",
        },
        "descuento": {
            "source": row.get("DescuentoFuente") or default_source,
            "original": discount,
            "status": "missing" if discount is None else "ok",
        },
        "importe": {
            "source": row.get("ImporteFuente") or default_source,
            "original": importe,
            "status": "missing" if importe is None else "ok",
        },
        "cantidad": {
            "source": row.get("CantidadFuente") or default_source,
            "value": qty,
        },
    }

    # Recupera Codigo perdido para SALTOKI si está embebido al inicio de la descripción
    if (row.get("Proveedor") == "SALTOKI") and _is_missing_value(row.get("Codigo")):
        desc = row.get("Descripcion") or ""
        m_code = re.match(r"\s*([A-Z0-9]{6,})\b", desc)
        if m_code:
            row["Codigo"] = m_code.group(1)
            row["Descripcion"] = desc[len(m_code.group(0)):].lstrip(" -")
            trace["codigo_recovered"] = {"from_desc": True}

    def _add_token(token: str) -> None:
        if token and token not in warn_set:
            warn_tokens.append(token)
            warn_set.add(token)

    if importe is not None and importe < 0:
        _add_token("importe_negativo")
        trace["importe"]["status"] = "negative"

    if discount is not None:
        if discount < 0:
            _add_token("discount_negative")
            trace["descuento"]["status"] = "negative"
        elif discount >= 100:
            _add_token("discount_overflow")
            _add_token("discount_recheck")
            trace["descuento"]["status"] = "overflow"

    base = price * qty if price and qty else None
    expected_importe = None

    if base and price and qty:
        if discount is not None:
            if 0 <= discount < 100:
                expected_importe = round(base * (100 - discount) / 100, 2)
                trace["importe"]["expected"] = expected_importe
                if importe is None:
                    trace["importe"]["status"] = "hint_missing"
                    _add_token(f"importe_hint={round(expected_importe, 2)}")
                else:
                    diff = abs(expected_importe - (importe or 0.0))
                    trace["importe"]["diff"] = round(diff, 4)
                    if diff > _DISCOUNT_TOLERANCE:
                        trace["importe"]["status"] = "mismatch"
                        _add_token("importe_formula")
            else:
                expected_importe = round(base * (100 - min(max(discount, 0.0), 100.0)) / 100, 2)
                trace["importe"]["expected"] = expected_importe
                if importe is None:
                    trace["importe"]["status"] = "hint_missing"
                    _add_token(f"importe_hint={round(expected_importe, 2)}")
        elif importe is not None:
            computed_discount = 100 - ((importe / base) * 100)
            computed_discount = max(0.0, min(100.0, computed_discount))
            trace["descuento"]["computed"] = round(computed_discount, 2)
            _add_token(f"discount_hint={round(computed_discount, 2)}")
    elif base and discount is None and importe is not None:
        computed_discount = 100 - ((importe / base) * 100)
        computed_discount = max(0.0, min(100.0, computed_discount))
        trace["descuento"]["computed"] = round(computed_discount, 2)
        _add_token(f"discount_hint={round(computed_discount, 2)}")

    importe_hint = next((tok for tok in warn_tokens if tok.startswith("importe_hint=")), None)
    if importe_hint:
        try:
            hint_val = float(importe_hint.split("=", 1)[1])
            trace["importe"]["hint"] = hint_val
            if importe is None:
                trace["importe"]["status"] = "hint"
        except Exception:
            trace["importe"]["hint_error"] = importe_hint

    discount_hint = next((tok for tok in warn_tokens if tok.startswith("discount_hint=")), None)
    if discount_hint:
        try:
            hint_val = float(discount_hint.split("=", 1)[1])
            trace["descuento"]["hint"] = hint_val
            if discount is None:
                trace["descuento"]["status"] = "hint"
        except Exception:
            trace["descuento"]["hint_error"] = discount_hint

    if not warn_tokens:
        row["ParseWarn"] = ""
    else:
        row["ParseWarn"] = ";".join(warn_tokens)
    trace["warnings"] = warn_tokens
    row["ParseTrace"] = json.dumps(trace, ensure_ascii=False)


def _merge_text(base_text: str | None, extra_text: str | None) -> str:
    base = (base_text or "").strip()
    extra = (extra_text or "").strip()
    if not extra:
        return base_text or ""
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base}\n{extra}"


def _attach_ocr_text(page, override_text: str, original_extract):
    merged = _merge_text(original_extract() or "", override_text)

    def _extract_text_with_override(self, *args, _orig=original_extract, _override=override_text, **kwargs):
        orig = _orig(*args, **kwargs)
        return _merge_text(orig, _override)

    page.extract_text = MethodType(_extract_text_with_override, page)
    return merged


def _compute_text_density(page, text: str | None) -> tuple[float, int]:
    text = text or ""
    char_count = len(text.strip())
    try:
        area = float(page.width or 0.0) * float(page.height or 0.0)
    except Exception:
        area = 0.0
    density = (char_count / area) if area else 0.0
    return density, char_count


def _compute_entropy(text: str | None) -> float:
    if not text:
        return 0.0
    text = text.strip()
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    total = 0
    for ch in text:
        if ch.isspace():
            continue
        freq[ch] = freq.get(ch, 0) + 1
        total += 1
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in freq.values():
        p = count / total
        if p <= 0:
            continue
        entropy -= p * math.log2(p)
    return entropy


def _collect_text_metrics(page, text: str | None) -> dict[str, float | int]:
    density, char_count = _compute_text_density(page, text)
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    entropy = _compute_entropy(text)
    return {
        "density": density,
        "char_count": char_count,
        "line_count": len(lines),
        "entropy": entropy,
    }


def _should_trigger_ocr(metrics: dict[str, float | int]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if metrics.get("char_count", 0) < _OCR_MIN_CHARS:
        reasons.append(f"chars<{_OCR_MIN_CHARS}")
    if metrics.get("density", 0.0) < _OCR_DENSITY_THRESHOLD:
        reasons.append(f"density<{_OCR_DENSITY_THRESHOLD}")
    if metrics.get("line_count", 0) < _OCR_MIN_LINES:
        reasons.append(f"lines<{_OCR_MIN_LINES}")
    entropy = metrics.get("entropy", 0.0)
    if _OCR_MIN_ENTROPY > 0 and entropy < _OCR_MIN_ENTROPY:
        reasons.append(f"entropy<{_OCR_MIN_ENTROPY}")
    return (len(reasons) > 0, reasons)


def _normalize_albaran_number(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", str(value)).upper()


def _extract_albaran_candidate(meta: dict | None, joined_text: str | None) -> str:
    if meta:
        meta_albaran = meta.get("AlbaranNumero")
        if _looks_like_albaran_value(meta_albaran):
            return meta_albaran.strip()
    if not joined_text:
        return ""
    normalized = normalize_spaces(_strip_diacritics(joined_text))
    match = _ALBARAN_FALLBACK_RE.search(normalized)
    if match:
        return match.group(1).strip()
    return ""


def _extract_hoja_info(lines: list[str]) -> tuple[int | None, int | None]:
    for line in lines:
        normalized = normalize_spaces(_strip_diacritics(line))
        match = _HOJA_RE.search(normalized)
        if match:
            try:
                num = int(match.group(1))
                total = int(match.group(2))
                return num, total
            except Exception:
                continue
    return None, None


def _looks_like_footer_page(lines: list[str]) -> bool:
    if not lines:
        return False
    normalized = []
    for line in lines:
        clean = normalize_spaces(_strip_diacritics(line)).upper()
        if clean:
            normalized.append(clean)
    if not normalized:
        return False
    joined = " ".join(normalized)
    if any(hint in joined for hint in _TABLE_HEADER_HINTS):
        return False
    footer_hits = sum(1 for kw in _FOOTER_KEYWORDS if kw in joined)
    return footer_hits >= 2


def _normalize_numeric_rows(rows: list[dict]) -> None:
    if not _ENFORCE_DISCOUNT_RULES:
        return
    for row in rows:
        _normalize_numeric_row(row)


OPTIONAL_REQUIRED_FIELDS = {
    "ALKAIN": {"SuPedidoCodigo"},
    "BALANTXA": {"SuPedidoCodigo"},
}

def _strip_diacritics(value):
    if not isinstance(value, str):
        return value
    try:
        normalized = unicodedata.normalize("NFKD", value)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))
    except Exception:
        return value

_ORIGINAL_PRINT = builtins.print

def _ascii_print(*args, **kwargs):
    new_args = [_strip_diacritics(arg) for arg in args]
    _ORIGINAL_PRINT(*new_args, **kwargs)

builtins.print = _ascii_print

def _ensure_utf8_console():
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                continue
def _is_missing_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, float):
        return math.isnan(value)
    return False

def _select_preferred_value(candidates, field, string_fields: set[str]):
    # Cabecera: prioriza texto base sobre OCR si existe valor.
    # Evita que OCR (más ruidoso en cabecera) sobreescriba SuPedido/Albarán correctos.
    if field in {"SuPedidoCodigo", "AlbaranNumero", "FechaAlbaran"}:
        for stage, row in candidates:
            if (stage or "") != "base":
                continue
            base_val = row.get(field)
            if not _is_missing_value(base_val):
                return base_val
    for stage, row in candidates:
        if field == "OcrStage":
            val = row.get(field, stage or "")
            if not val:
                val = stage or ""
        else:
            val = row.get(field)
        if field == "ParseWarn":
            if val is None:
                continue
            return val
        if not _is_missing_value(val):
            return val
    return "" if field in string_fields else None

def _merge_candidate_rows(candidates, columns, string_fields: set[str]):
    merged = {}
    for col in columns:
        merged[col] = _select_preferred_value(candidates, col, string_fields)
    extra_keys = []
    seen = set(columns)
    for _, row in candidates:
        for key in row.keys():
            if key not in seen:
                extra_keys.append(key)
                seen.add(key)
    for key in extra_keys:
        merged[key] = _select_preferred_value(candidates, key, string_fields)
    return merged

def _merge_stage_entries(rows: list[dict], columns: list[str], string_fields: set[str],
                         key_fields=("Pdf", "Pagina", "Parser")) -> list[dict]:
    if not rows:
        return rows
    grouped = OrderedDict()
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        grouped.setdefault(key, []).append(row)
    merged_rows: list[dict] = []
    for group_rows in grouped.values():
        stage_map = OrderedDict()
        for row in group_rows:
            stage = row.get("OcrStage")
            stage_label = stage if stage else "base"
            stage_map.setdefault(stage_label, []).append(row)
        if len(stage_map) <= 1:
            merged_rows.extend(group_rows)
            continue
        stage_order = [s for s in stage_map.keys() if s != "base"]
        if "base" in stage_map:
            stage_order.append("base")
        max_len = max(len(lst) for lst in stage_map.values())
        stage_index = {stage: idx for idx, stage in enumerate(stage_order)}
        for idx in range(max_len):
            candidates = []
            for stage in stage_order:
                lst = stage_map.get(stage)
                if lst and idx < len(lst):
                    candidates.append((stage, lst[idx]))
            if not candidates:
                continue
            def _is_fallback_row(row: dict) -> bool:
                warn = (row.get("ParseWarn") or "").lower()
                return "fallback" in warn
            candidates.sort(key=lambda sr: (_is_fallback_row(sr[1]), stage_index.get(sr[0], len(stage_order))))
            merged_rows.append(_merge_candidate_rows(candidates, columns, string_fields))
    return merged_rows

# ---------------- utilidades de I/O ----------------
def app_dir() -> Path:
    env_dir = os.environ.get("ALBARANES_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def pick_input_folder() -> Path:
    base = app_dir()
    if TK_AVAILABLE:
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(
            "Paso 1/2 - Carpeta de entrada",
            "Selecciona la carpeta que contiene los PDFs de albaranes a procesar.\n\n"
            "- Puedes elegir una carpeta con subcarpetas.\n"
            "- Asegúrate de que no estén abiertos los Excels de salidas previas."
        )
        folder = filedialog.askdirectory(initialdir=str(base), title="Selecciona la carpeta con PDFs")
        root.destroy()
        if not folder: sys.exit(1)
        return Path(folder)
    print("Ruta carpeta PDFs:", file=sys.stderr)
    p = input("> ").strip()
    if not p: sys.exit(1)
    return Path(p)

def pick_output_file(default_dir: Path) -> Path:
    if TK_AVAILABLE:
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(
            "Paso 2/2 - Salida Excel",
            "Elige donde guardar el Excel master (albaranes_master.xlsx).\n\n"
            "- Si no eliges nada, se usara el nombre por defecto en la carpeta seleccionada."
        )
        filename = filedialog.asksaveasfilename(
            initialdir=str(default_dir),
            title="Guardar Excel (master)",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="albaranes_master.xlsx",
        )
        root.destroy()
        return Path(filename) if filename else (default_dir / "albaranes_master.xlsx")
    return default_dir / "albaranes_master.xlsx"


def _apply_user_settings(base_dir: Path):
    """Sobrescribe ajustes globales desde user_settings.json si existe."""
    cfg = load_settings(base_dir)
    if not cfg:
        return {}
    _apply_settings_dict(cfg)
    return cfg


def _apply_settings_dict(cfg: dict):
    """Aplica un diccionario de configuracion sobre los globals."""
    g = globals()
    # Banderas simples
    for key in ("PRECHECK_ENABLED", "STOP_ON_ERROR", "DEBUG_ENABLED", "SUPEDIDO_TRUNCATED_ENABLED"):
        if key in cfg:
            g[key] = bool(cfg[key])
    # OCR toggles
    ocr_cfg = g.get("OCR_CONFIG", {})
    if "OCR_CONFIG" in cfg and isinstance(cfg["OCR_CONFIG"], dict):
        for k in ("ocrmypdf", "doctr", "tesseract", "preprocess"):
            if k in cfg["OCR_CONFIG"] and isinstance(cfg["OCR_CONFIG"][k], dict):
                ocr_cfg.setdefault(k, {}).update(cfg["OCR_CONFIG"][k])
    for optional_stage, module_name in (("ocrmypdf", "ocrmypdf"), ("doctr", "doctr")):
        stage_cfg = ocr_cfg.get(optional_stage) or {}
        if stage_cfg.get("enabled"):
            try:
                available = find_spec(module_name) is not None
            except Exception:
                available = False
            if not available:
                stage_cfg["enabled"] = False
    if "OCR_WORKFLOW" in cfg and isinstance(cfg["OCR_WORKFLOW"], dict):
        workflow_cfg = dict(cfg["OCR_WORKFLOW"])
        if workflow_cfg.get("ocr_force_all") and cfg.get("ocr_mode") != "force":
            workflow_cfg["ocr_force_all"] = False
        g["OCR_WORKFLOW"].update(workflow_cfg)
    if "TRACE_OUTPUT" in cfg and isinstance(cfg["TRACE_OUTPUT"], dict):
        g["TRACE_OUTPUT"].update(cfg["TRACE_OUTPUT"])


def _open_settings_ui(base_dir: Path):
    if not TK_AVAILABLE:
        print("[WARN] Tkinter no disponible; no se puede abrir el configurador.")
        return
    current = load_settings(base_dir)
    cfg = {
        "PRECHECK_ENABLED": current.get("PRECHECK_ENABLED", PRECHECK_ENABLED),
        "STOP_ON_ERROR": current.get("STOP_ON_ERROR", STOP_ON_ERROR),
        "DEBUG_ENABLED": current.get("DEBUG_ENABLED", DEBUG_ENABLED),
        "OCR_CONFIG": {
            "ocrmypdf": {"enabled": False},
            "doctr": {"enabled": False},
            "tesseract": {"enabled": current.get("OCR_CONFIG", {}).get("tesseract", {}).get("enabled", OCR_CONFIG["tesseract"]["enabled"])},
        },
        "OCR_WORKFLOW": {
            "ocr_force_all": current.get("OCR_WORKFLOW", {}).get("ocr_force_all", OCR_WORKFLOW.get("ocr_force_all", False))
        },
    }
    root = tk.Tk()
    root.title("Configurar Albaranes Parser")
    bool_vars = {
        "PRECHECK_ENABLED": tk.BooleanVar(value=cfg["PRECHECK_ENABLED"]),
        "STOP_ON_ERROR": tk.BooleanVar(value=cfg["STOP_ON_ERROR"]),
        "DEBUG_ENABLED": tk.BooleanVar(value=cfg["DEBUG_ENABLED"]),
        "tesseract": tk.BooleanVar(value=cfg["OCR_CONFIG"]["tesseract"]["enabled"]),
        "ocr_force_all": tk.BooleanVar(value=cfg["OCR_WORKFLOW"]["ocr_force_all"]),
    }

    row = 0
    def add_chk(label, key):
        nonlocal row
        tk.Checkbutton(root, text=label, variable=bool_vars[key]).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        row += 1

    add_chk("Precheck (conteo inicial)", "PRECHECK_ENABLED")
    add_chk("Parar en primer error grave", "STOP_ON_ERROR")
    add_chk("Debug activado", "DEBUG_ENABLED")
    add_chk("Tesseract OCR", "tesseract")
    add_chk("Forzar OCR en todas las páginas", "ocr_force_all")

    def on_save():
        data = {
            "PRECHECK_ENABLED": bool_vars["PRECHECK_ENABLED"].get(),
            "STOP_ON_ERROR": bool_vars["STOP_ON_ERROR"].get(),
            "DEBUG_ENABLED": bool_vars["DEBUG_ENABLED"].get(),
            "OCR_CONFIG": {
                "ocrmypdf": {"enabled": False},
                "doctr": {"enabled": False},
                "tesseract": {"enabled": bool_vars["tesseract"].get()},
            },
            "OCR_WORKFLOW": {"ocr_force_all": bool_vars["ocr_force_all"].get()},
        }
        save_settings(base_dir, data)
        tk.messagebox.showinfo("Configuración guardada", "Se guardó en user_settings.json.\nReinicia el programa para aplicar.")
        root.destroy()

    tk.Button(root, text="Guardar y cerrar", command=on_save).grid(row=row, column=0, padx=8, pady=10, sticky="w")
    root.mainloop()

# ---- Prompt inicial de configuracion ----
def _prompt_settings(base_dir: Path):
    if not TK_AVAILABLE:
        return {}
    current = load_settings(base_dir)
    defaults = {
        "PRECHECK_ENABLED": current.get("PRECHECK_ENABLED", PRECHECK_ENABLED),
        "STOP_ON_ERROR": current.get("STOP_ON_ERROR", STOP_ON_ERROR),
        "DEBUG_ENABLED": current.get("DEBUG_ENABLED", DEBUG_ENABLED),
        "OCR_CONFIG": {
            "ocrmypdf": {"enabled": False},
            "doctr": {"enabled": False},
            "tesseract": {"enabled": current.get("OCR_CONFIG", {}).get("tesseract", {}).get("enabled", OCR_CONFIG["tesseract"]["enabled"])},
        },
        "OCR_WORKFLOW": {
            "ocr_force_all": current.get("OCR_WORKFLOW", {}).get("ocr_force_all", OCR_WORKFLOW.get("ocr_force_all", False))
        },
    }
    root = tk.Tk()
    root.title("Albaranes Parser - Configuracion inicial")
    bool_vars = {
        "PRECHECK_ENABLED": tk.BooleanVar(value=defaults["PRECHECK_ENABLED"]),
        "STOP_ON_ERROR": tk.BooleanVar(value=defaults["STOP_ON_ERROR"]),
        "DEBUG_ENABLED": tk.BooleanVar(value=defaults["DEBUG_ENABLED"]),
        "tesseract": tk.BooleanVar(value=defaults["OCR_CONFIG"]["tesseract"]["enabled"]),
        "ocr_force_all": tk.BooleanVar(value=defaults["OCR_WORKFLOW"]["ocr_force_all"]),
    }

    row = 0
    tk.Label(root, text="Configura las opciones y pulsa Continuar para procesar.\nSe usan los valores guardados si no cambias nada.").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    row += 1

    def add_chk(label, key):
        nonlocal row
        tk.Checkbutton(root, text=label, variable=bool_vars[key]).grid(row=row, column=0, sticky="w", padx=8, pady=3)
        row += 1

    add_chk("Precheck (conteo inicial)", "PRECHECK_ENABLED")
    add_chk("Parar en primer error grave", "STOP_ON_ERROR")
    add_chk("Debug activado", "DEBUG_ENABLED")
    add_chk("Tesseract OCR", "tesseract")
    add_chk("Forzar OCR en todas las paginas", "ocr_force_all")

    result = {}
    def _collect(save: bool):
        nonlocal result
        result = {
            "PRECHECK_ENABLED": bool_vars["PRECHECK_ENABLED"].get(),
            "STOP_ON_ERROR": bool_vars["STOP_ON_ERROR"].get(),
            "DEBUG_ENABLED": bool_vars["DEBUG_ENABLED"].get(),
            "OCR_CONFIG": {
                "ocrmypdf": {"enabled": False},
                "doctr": {"enabled": False},
                "tesseract": {"enabled": bool_vars["tesseract"].get()},
            },
            "OCR_WORKFLOW": {"ocr_force_all": bool_vars["ocr_force_all"].get()},
            "_save": save,
        }
        root.destroy()

    def _cancel():
        nonlocal result
        result = None
        root.destroy()

    tk.Button(root, text="Guardar y continuar", command=lambda: _collect(True)).grid(row=row, column=0, sticky="w", padx=8, pady=8)
    row += 1
    tk.Button(root, text="Continuar sin guardar", command=lambda: _collect(False)).grid(row=row, column=0, sticky="w", padx=8, pady=4)
    row += 1
    tk.Button(root, text="Cancelar", command=_cancel).grid(row=row, column=0, sticky="w", padx=8, pady=4)

    root.mainloop()
    return result

# ---------------- helpers Excel ----------------
def write_excel(path: Path, df_detail: pd.DataFrame, df_meta: pd.DataFrame, add_provider_summary: bool):
    """Escribe un Excel con Lineas, Totales_por_Albaran y (opcional) Resumen_Proveedor."""
    df_tot = consolidate_totals(df_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        df_detail = _normalize_df_types(df_detail)

        df_detail.to_excel(writer, index=False, sheet_name="Lineas")
        df_tot = _normalize_df_types(df_tot)

        df_tot.to_excel(writer, index=False, sheet_name="Totales_por_Albaran")
        if add_provider_summary:
            resumen = _kpis_for_summary(df_detail, df_tot)
            resumen = _normalize_df_types(resumen)

            resumen.to_excel(writer, index=False, sheet_name="Resumen_Proveedor")

def _write_excel_safe(path: Path, df_detail: pd.DataFrame, df_meta: pd.DataFrame, add_provider_summary: bool) -> Path:
    """
    Intenta escribir al path; si estÃ¡ bloqueado por Excel, escribe con sufijo _YYYYmmdd_HHMMSS.
    """
    try:
        write_excel(path, df_detail, df_meta, add_provider_summary)
        return path
    except PermissionError:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = path.with_name(path.stem + "_" + ts + path.suffix)
        write_excel(alt, df_detail, df_meta, add_provider_summary)
        return alt

# ---------------- utilidades de PDFs ----------------
def collect_pdfs(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted([p for p in input_path.glob(pattern)])
    return [input_path] if input_path.suffix.lower() == ".pdf" else []

def precheck(pdfs: list[Path]) -> dict:
    """Cuenta pÃ¡ginas (albaranes) de cada PDF antes de procesar."""
    total_pages = 0
    per_pdf = {}
    for p in pdfs:
        try:
            with pdfplumber.open(str(p)) as doc:
                n = len(doc.pages)
        except Exception:
            n = 0
        per_pdf[str(p)] = n
        total_pages += n
    return {"total_pdfs": len(pdfs), "per_pdf_pages": per_pdf, "total_pages": total_pages}

# ---------------- consolidaciones ----------------
def consolidate_totals(df_meta: pd.DataFrame) -> pd.DataFrame:
    """Agrega a nivel (Proveedor, Albaran, Fecha, SuPedido) y compara con pie."""
    if df_meta.empty:
        return pd.DataFrame(columns=META_COLS + ["Dif_Suma_vs_Neto", "Dif_Suma_vs_Total"])

    group_cols = ["Proveedor", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo"]

    def last_non_nan(s: pd.Series):
        s2 = s.dropna()
        return s2.iloc[-1] if not s2.empty else np.nan

    out = (
        df_meta.groupby(group_cols, dropna=False, as_index=False)
        .agg({
            "SumaImportesLineas": "sum",
            "NetoComercialPie": last_non_nan,
            "TotalAlbaranPie": last_non_nan,
        })
        .reset_index(drop=True)
    )

    out["Dif_Suma_vs_Neto"] = (
        pd.to_numeric(out["SumaImportesLineas"], errors="coerce")
        - pd.to_numeric(out["NetoComercialPie"], errors="coerce")
    ).round(2)

    out["Dif_Suma_vs_Total"] = (
        pd.to_numeric(out["SumaImportesLineas"], errors="coerce")
        - pd.to_numeric(out["TotalAlbaranPie"], errors="coerce")
    ).round(2)

    return out

def _kpis_for_summary(df_detail: pd.DataFrame, df_tot: pd.DataFrame) -> pd.DataFrame:
    """KPIs para la hoja Resumen_Proveedor (por parser)."""
    if df_detail.empty:
        return pd.DataFrame([{
            "Proveedor": "", "Parser": "", "#PDFs": 0, "#Paginas": 0,
            "#Albaranes": 0, "#Lineas": 0,
            "Importe_lineas_sum": 0.0, "Neto_pie_sum": 0.0, "Total_pie_sum": 0.0,
            "#Lineas_con_warn": 0, "Primer_dia": "", "Ultimo_dia": "",
        }])

    prov = df_detail["Proveedor"].astype(str).mode().iat[0] if "Proveedor" in df_detail else ""
    pid = df_detail["Parser"].astype(str).mode().iat[0] if "Parser" in df_detail else ""

    n_pdfs = df_detail["Pdf"].nunique() if "Pdf" in df_detail else 0
    n_pages = df_detail["Pagina"].nunique() if "Pagina" in df_detail else 0

    if not df_tot.empty:
        n_alb = df_tot[["AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo"]].drop_duplicates().shape[0]
        neto_sum = pd.to_numeric(df_tot["NetoComercialPie"], errors="coerce").sum(skipna=True)
        total_sum = pd.to_numeric(df_tot["TotalAlbaranPie"], errors="coerce").sum(skipna=True)
    else:
        n_alb = 0; neto_sum = total_sum = 0.0

    if "ParseWarn" in df_detail.columns:
        s = df_detail["ParseWarn"].astype("string")
        n_warn = int(((s.notna()) & (s.str.strip().ne(""))).sum())
    else:
        n_warn = 0

    if "FechaAlbaran" in df_detail.columns:
        fechas = df_detail["FechaAlbaran"].astype("string")
        fechas = fechas[fechas.str.strip().ne("")]
        primer = fechas.min() if not fechas.empty else ""
        ultimo = fechas.max() if not fechas.empty else ""
    else:
        primer = ultimo = ""

    return pd.DataFrame([{
        "Proveedor": prov,
        "Parser": pid,
        "#PDFs": int(n_pdfs),
        "#Paginas": int(n_pages),
        "#Albaranes": int(n_alb),
        "#Lineas": int(df_detail.shape[0]),
        "Importe_lineas_sum": pd.to_numeric(df_detail["Importe"], errors="coerce").sum(skipna=True),
        "Neto_pie_sum": neto_sum,
        "Total_pie_sum": total_sum,
        "#Lineas_con_warn": n_warn,
        "Primer_dia": primer,
        "Ultimo_dia": ultimo,
    }])

# ---------------- nÃºcleo por PDF ----------------
\
\
def process_pdf(pdf_path: Path,
                results_detail: list,
                errors: list,
                page_trace: list | None = None,
                skipped_pages: list | None = None,
                ocr_conf: dict | None = None, target_pages: set[int] | None = None,
                allow_fallback: bool = True, stage_label: str = "base",
                required_fields: list[str] | None = None,
                debug_split_stage: bool = True,
                cancel_event: threading.Event | None = None,
                progress_cb=None):
    """
    Procesa un PDF pagina a pagina. Anade filas a:
      - results_detail: [{'pdf','page','detected','parser_id','items'}]
      - errors: [{'pdf','page','detected','parser_id','items','msg'}]
    """
    ocr_conf = ocr_conf or {}
    required_fields = required_fields or []
    debug_label = pdf_path.name if (stage_label == "base" or not debug_split_stage) else f"{stage_label}_{pdf_path.name}"
    ocr_available = bool(
        (ocr_conf.get("ocrmypdf") or {}).get("enabled", False)
        or (ocr_conf.get("doctr") or {}).get("enabled", False)
        or (ocr_conf.get("tesseract") or {}).get("enabled", False)
    )
    ocr_force_all = bool((OCR_WORKFLOW or {}).get("ocr_force_all", False))
    override_texts: dict[int, str] = {}
    ocr_stages: list[str] = []
    ocr_loaded = False
    last_albaran_number = ""

    def _ensure_ocr():
        nonlocal override_texts, ocr_stages, ocr_loaded
        if cancel_event is not None and cancel_event.is_set():
            raise PipelineCancelled("Cancelado por el usuario")
        if not ocr_available or ocr_loaded:
            return
        try:
            artifacts = apply_ocr_pipeline(pdf_path, ocr_conf)
            override_texts = artifacts.text_by_page or {}
            ocr_stages = artifacts.stages or []
        except Exception as exc:
            print(f"[WARN][OCR] No se pudo aplicar OCR a {pdf_path.name}: {exc}")
            override_texts = {}
            ocr_stages = []
        ocr_loaded = True

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    raise PipelineCancelled("Cancelado por el usuario")
                if target_pages and i not in target_pages:
                    continue
                original_extract = page.extract_text
                base_text = original_extract() or ""
                page_used_ocr = False
                fallback_used = False
                attempts = 0
                metrics = _collect_text_metrics(page, base_text)
                should_auto, auto_reasons = _should_trigger_ocr(metrics)
                trace_entry = {
                    "Pdf": pdf_path.name,
                    "Pagina": i,
                    "CharCountPre": metrics.get("char_count", 0),
                    "LineCountPre": metrics.get("line_count", 0),
                    "DensityPre": metrics.get("density", 0.0),
                    "EntropyPre": metrics.get("entropy", 0.0),
                    "CharCount": metrics.get("char_count", 0),
                    "LineCount": metrics.get("line_count", 0),
                    "Density": metrics.get("density", 0.0),
                    "Entropy": metrics.get("entropy", 0.0),
                    "OcrTriggered": False,
                    "TriggerReason": "",
                    "Stage": stage_label,
                    "OcrForceAll": ocr_force_all,
                }
                trace_reasons: list[str] = []
                skip_page = False

                if ocr_force_all and ocr_available:
                    _ensure_ocr()
                    override = (override_texts.get(i) or "").strip()
                    if override:
                        _attach_ocr_text(page, override, original_extract)
                        page_used_ocr = True
                        trace_entry["OcrTriggered"] = True
                        trace_reasons.append("force_all")
                        base_text = page.extract_text() or base_text
                        metrics = _collect_text_metrics(page, base_text)
                        trace_entry["CharCount"] = metrics.get("char_count", trace_entry["CharCount"])
                        trace_entry["LineCount"] = metrics.get("line_count", trace_entry["LineCount"])
                        trace_entry["Density"] = metrics.get("density", trace_entry["Density"])
                        trace_entry["Entropy"] = metrics.get("entropy", trace_entry["Entropy"])
                elif ocr_available and should_auto:
                    _ensure_ocr()
                    override = (override_texts.get(i) or "").strip()
                    if override:
                        _attach_ocr_text(page, override, original_extract)
                        page_used_ocr = True
                        trace_entry["OcrTriggered"] = True
                        trace_reasons.extend(auto_reasons)
                        base_text = page.extract_text() or base_text
                        metrics = _collect_text_metrics(page, base_text)
                        trace_entry["CharCount"] = metrics.get("char_count", trace_entry["CharCount"])
                        trace_entry["LineCount"] = metrics.get("line_count", trace_entry["LineCount"])
                        trace_entry["Density"] = metrics.get("density", trace_entry["Density"])
                        trace_entry["Entropy"] = metrics.get("entropy", trace_entry["Entropy"])
                    elif auto_reasons:
                        trace_reasons.extend(auto_reasons)

                parse_failed = False
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise PipelineCancelled("Cancelado por el usuario")
                    text = page.extract_text() or base_text
                    lines = [normalize_spaces(ln) for ln in text.splitlines() if ln.strip()]
                    joined = " ".join(lines)
                    dbg_page_text(debug_label, i, lines, joined)

                    try:
                        proveedor = detect_proveedor(lines, joined, dbgmeta={"pdf": pdf_path.name, "page": i})
                    except TypeError:
                        proveedor = detect_proveedor(lines, joined)

                    pinfo = get_parser_for(proveedor)
                    parser_id = pinfo["id"] if pinfo else None

                    dbg_detect_result(debug_label, i, proveedor, parser_id or "generic")

                    try:
                        if pinfo:
                            items, meta = pinfo["parse"](page, i)
                        else:
                            try:
                                items, meta = generic_parser.parse_page(page, i, proveedor_detectado=proveedor)
                                parser_id = "generic"
                            except TypeError:
                                items, meta = generic_parser.parse_page(page, i)
                                parser_id = "generic"
                    except Exception as ex:
                        errors.append({"pdf": pdf_path.name, "page": i, "detected": proveedor,
                                       "parser_id": parser_id or "generic", "items": 0,
                                       "msg": f"Error ejecutando parser: {ex!r}"})
                        if STOP_ON_ERROR:
                            raise
                        parse_failed = True
                        break

                    _normalize_supedido_field(meta)
                    for row in items or []:
                        _normalize_supedido_field(row)

                    needs_required = _page_missing_required(items, meta, required_fields)
                    if needs_required and ocr_available and not page_used_ocr:
                        _ensure_ocr()
                        override = (override_texts.get(i) or "").strip()
                        if override:
                            _attach_ocr_text(page, override, original_extract)
                            page_used_ocr = True
                            trace_entry["OcrTriggered"] = True
                            if "needs_required" not in trace_reasons:
                                trace_reasons.append("needs_required")
                            attempts += 1
                            if attempts <= 1:
                                base_text = page.extract_text() or base_text
                                metrics = _collect_text_metrics(page, base_text)
                                trace_entry["CharCount"] = metrics.get("char_count", trace_entry["CharCount"])
                                trace_entry["LineCount"] = metrics.get("line_count", trace_entry["LineCount"])
                                trace_entry["Density"] = metrics.get("density", trace_entry["Density"])
                                trace_entry["Entropy"] = metrics.get("entropy", trace_entry["Entropy"])
                                continue
                        else:
                            page_used_ocr = True  # evitar bucle si override vacío
                            if "needs_required" not in trace_reasons:
                                trace_reasons.append("needs_required_no_text")

                    if allow_fallback and (proveedor and proveedor != "DESCONOCIDO") and not items:
                        hoja_num, hoja_total = _extract_hoja_info(lines)
                        candidate_albaran = _extract_albaran_candidate(meta, joined)
                        norm_candidate = _normalize_albaran_number(candidate_albaran)
                        norm_last = _normalize_albaran_number(last_albaran_number)
                        footer_only = _looks_like_footer_page(lines)

                        same_albaran_last_page = (
                            norm_candidate
                            and norm_last
                            and norm_candidate == norm_last
                            and hoja_num is not None
                            and hoja_total is not None
                            and hoja_num == hoja_total
                            and hoja_total >= hoja_num
                        )
                        inferred_footer_last_page = (
                            footer_only
                            and norm_last
                            and hoja_num is not None
                            and hoja_total is not None
                            and hoja_total >= 2
                            and hoja_num == hoja_total
                        )

                        if same_albaran_last_page or inferred_footer_last_page:
                            skip_page = True
                            skip_rec = {
                                "Pdf": pdf_path.name,
                                "Pagina": i,
                                "Proveedor": proveedor,
                                "AlbaranNumero": candidate_albaran or last_albaran_number or "",
                                "Hoja": hoja_num,
                                "TotalHojas": hoja_total,
                            }
                            if skipped_pages is not None:
                                skipped_pages.append(skip_rec)
                            print(f"[INFO] {pdf_path.name}: pagina {i} descartada (ultima hoja sin lineas) "
                                  f"albaran={skip_rec['AlbaranNumero']}")
                            break
                        parser_id_eff = parser_id or (pinfo["id"] if pinfo else "generic")
                        items = [_make_fallback_item(text or "", proveedor, parser_id_eff, i, pdf_path.name, meta=meta)]
                        errors.append({"pdf": pdf_path.name, "page": i, "detected": proveedor,
                                       "parser_id": parser_id_eff, "items": 1,
                                       "msg": "Fallback anadido - detectado sin lineas parseadas"})
                        fallback_used = True
                        needs_required = False

                    break

                if parse_failed:
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "pdf": pdf_path.name,
                                "page": i,
                                "processed": True,
                                "ok": False,
                                "items": 0,
                                "skipped": False,
                                "fallback": False,
                            }
                        )
                    continue
                if skip_page:
                    results_detail.append({
                        "pdf": pdf_path.name,
                        "page": i,
                        "detected": proveedor,
                        "parser_id": parser_id or "generic",
                        "items": 0,
                        "stage": stage_label,
                        "ocr_applied": page_used_ocr,
                        "ocr_pipeline": "+".join(ocr_stages) if page_used_ocr else "",
                        "needs_required": False,
                        "skipped_last_page": True,
                        "AlbaranNumero": (skip_rec["AlbaranNumero"] if "skip_rec" in locals() else ""),
                        "Hoja": (skip_rec["Hoja"] if "skip_rec" in locals() else None),
                        "TotalHojas": (skip_rec["TotalHojas"] if "skip_rec" in locals() else None),
                    })
                    if page_trace is not None:
                        trace_entry["TriggerReason"] = ";".join(dict.fromkeys(trace_reasons)) if trace_reasons else ""
                        trace_entry["OcrStage"] = stage_label + ("+ocr" if page_used_ocr else "")
                        trace_entry["OcrPipeline"] = "+".join(ocr_stages) if page_used_ocr else ""
                        trace_entry["ProveedorDetectado"] = proveedor
                        trace_entry["Parser"] = parser_id or "generic"
                        trace_entry["Items"] = 0
                        trace_entry["NeedsRequired"] = False
                        trace_entry["Fallback"] = False
                        trace_entry["OcrApplied"] = page_used_ocr
                        trace_entry["AlbaranNumero"] = trace_entry.get("AlbaranNumero") or (skip_rec["AlbaranNumero"] if "skip_rec" in locals() else "")
                        trace_entry["Hoja"] = trace_entry.get("Hoja") or (skip_rec["Hoja"] if "skip_rec" in locals() else None)
                        trace_entry["TotalHojas"] = trace_entry.get("TotalHojas") or (skip_rec["TotalHojas"] if "skip_rec" in locals() else None)
                        page_trace.append(trace_entry)
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "pdf": pdf_path.name,
                                "page": i,
                                "processed": True,
                                "ok": True,
                                "items": 0,
                                "skipped": True,
                                "fallback": False,
                            }
                        )
                    continue

                ocr_stage_label = stage_label + ("+ocr" if page_used_ocr else "")
                nitems = len(items or [])
                for row in items:
                    row["Proveedor"] = proveedor
                    row["Parser"] = parser_id or "generic"
                    row["Pdf"] = pdf_path.name
                    row["Pagina"] = i
                    row["ParseWarn"] = (row.get("ParseWarn") or "")
                    row["OcrStage"] = ocr_stage_label
                    row["OcrPipeline"] = "+".join(ocr_stages) if page_used_ocr else ""
                    row["NeedsRequired"] = needs_required
                    source_label = "ocr" if "ocr" in ocr_stage_label.lower() else "base"
                    row.setdefault("CantidadFuente", source_label)
                    row.setdefault("PrecioFuente", source_label if row.get("PrecioUnitario") is not None else "")
                    row.setdefault("DescuentoFuente", source_label if row.get("DescuentoPct") is not None else "")
                    row.setdefault("ImporteFuente", source_label if row.get("Importe") is not None else "")
                    row.setdefault("ParseTrace", "")
                    if not row.get("AlbaranNumero"):
                        row["AlbaranNumero"] = meta.get("AlbaranNumero", "")
                    if not row.get("FechaAlbaran"):
                        row["FechaAlbaran"] = meta.get("FechaAlbaran", "")
                    if not row.get("SuPedidoCodigo"):
                        row["SuPedidoCodigo"] = meta.get("SuPedidoCodigo", "")

                meta = meta or {}
                meta["Proveedor"] = proveedor
                meta["Parser"] = parser_id or "generic"
                meta["Pagina"] = i
                meta["Pdf"] = pdf_path.name
                meta.setdefault("OcrPipeline", "")
                meta["OcrStage"] = ocr_stage_label
                if page_used_ocr:
                    meta["OcrPipeline"] = "+".join(ocr_stages) or "ocr"

                try:
                    final_text = page.extract_text() or base_text
                except Exception:
                    final_text = base_text
                final_metrics = _collect_text_metrics(page, final_text)
                trace_entry["CharCount"] = final_metrics.get("char_count", trace_entry["CharCount"])
                trace_entry["LineCount"] = final_metrics.get("line_count", trace_entry["LineCount"])
                trace_entry["Density"] = final_metrics.get("density", trace_entry["Density"])
                trace_entry["Entropy"] = final_metrics.get("entropy", trace_entry["Entropy"])
                if trace_reasons:
                    trace_entry["TriggerReason"] = ";".join(dict.fromkeys(trace_reasons))
                trace_entry["OcrStage"] = ocr_stage_label
                trace_entry["OcrPipeline"] = "+".join(ocr_stages) if page_used_ocr else ""
                trace_entry["ProveedorDetectado"] = proveedor
                trace_entry["Parser"] = parser_id or "generic"
                trace_entry["Items"] = nitems
                trace_entry["NeedsRequired"] = needs_required
                trace_entry["Fallback"] = fallback_used
                trace_entry["OcrApplied"] = page_used_ocr

                results_detail.append({
                    "pdf": pdf_path.name,
                    "page": i,
                    "detected": proveedor,
                    "parser_id": parser_id or "generic",
                    "items": nitems,
                    "stage": stage_label,
                    "ocr_applied": page_used_ocr,
                    "ocr_pipeline": "+".join(ocr_stages) if page_used_ocr else "",
                    "needs_required": needs_required,
                    "skipped_last_page": False,
                })

                if page_trace is not None:
                    page_trace.append(trace_entry)

                if progress_cb is not None:
                    progress_cb(
                        {
                            "pdf": pdf_path.name,
                            "page": i,
                            "processed": True,
                            "ok": nitems > 0 or fallback_used,
                            "items": nitems,
                            "skipped": False,
                            "fallback": fallback_used,
                        }
                    )

                if proveedor == "DESCONOCIDO":
                    errors.append({"pdf": pdf_path.name, "page": i, "detected": proveedor,
                                   "parser_id": parser_id or "generic", "items": nitems,
                                   "msg": "Proveedor DESCONOCIDO"})
                elif nitems == 0:
                    errors.append({"pdf": pdf_path.name, "page": i, "detected": proveedor,
                                   "parser_id": parser_id or "generic", "items": 0,
                                   "msg": "Detectado pero sin lineas parseadas"})

                yield items, meta
                if nitems:
                    albaran_for_state = ""
                    if meta:
                        albaran_for_state = meta.get("AlbaranNumero") or ""
                    if not albaran_for_state:
                        for row in items:
                            if row.get("AlbaranNumero"):
                                albaran_for_state = row["AlbaranNumero"]
                                break
                    if albaran_for_state:
                        last_albaran_number = albaran_for_state
    except PipelineCancelled:
        raise
    except Exception as ex:
        errors.append({"pdf": pdf_path.name, "page": "-", "detected": "-",
                       "parser_id": "-", "items": 0,
                       "msg": f"No se pudo abrir el PDF: {ex!r}"})
        if STOP_ON_ERROR:
            raise

def _emit_log(logger: logging.Logger | None, message: str, level: int = logging.INFO) -> None:
    if logger is None:
        print(message)
        return
    logger.log(level, message)


def run_pipeline(
    in_path: Path,
    out_path: Path,
    recursive: bool = False,
    cancel_event: threading.Event | None = None,
    progress_cb=None,
    logger: logging.Logger | None = None,
) -> dict:
    import time

    total_start = time.time()
    out_dir = out_path.parent

    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("Cancelado por el usuario")

    pdfs = collect_pdfs(in_path, recursive)
    if not pdfs:
        raise FileNotFoundError(f"No se han encontrado PDFs en: {in_path}")

    total_pages = None
    if PRECHECK_ENABLED:
        info = precheck(pdfs)
        total_pages = int(info["total_pages"])
        _emit_log(logger, f"[PRECHECK] PDFs: {info['total_pdfs']} | Albaranes (paginas): {info['total_pages']}")
        for k, v in info["per_pdf_pages"].items():
            _emit_log(logger, f"  - {Path(k).name}: {v} pags")
        if progress_cb is not None:
            progress_cb({"event": "precheck", "total_pages": total_pages, "total_pdfs": int(info["total_pdfs"])})

    all_items, all_meta = [], []
    results_detail, errors = [], []
    page_trace_rows: list[dict] = []
    all_skipped: list[dict] = []

    debug_cfg = OCR_DEBUG or {}
    ocr_cfg = OCR_CONFIG or {}
    debug_split_stage = bool(debug_cfg.get("per_stage_files", True))
    ocr_available = bool(
        (ocr_cfg.get("ocrmypdf") or {}).get("enabled", False)
        or (ocr_cfg.get("doctr") or {}).get("enabled", False)
        or (ocr_cfg.get("tesseract") or {}).get("enabled", False)
    )
    base_msg = "con pipeline OCR hibrido" if ocr_available else "solo texto embebido"
    _emit_log(logger, f"[INFO] Procesando {len(pdfs)} PDF(s) ({base_msg})...")

    cancelled = False
    for pdf in pdfs:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        _emit_log(logger, f"[INFO] Iniciando {pdf.name}...")
        processed_pages = 0
        skipped_pages_log: list[dict] = []
        try:
            for processed_pages, (items, meta) in enumerate(
                process_pdf(
                    pdf,
                    results_detail,
                    errors,
                    page_trace=page_trace_rows,
                    skipped_pages=skipped_pages_log,
                    ocr_conf=ocr_cfg,
                    target_pages=None,
                    allow_fallback=True,
                    stage_label="base",
                    required_fields=OCR_REQUIRED_FIELDS,
                    debug_split_stage=debug_split_stage,
                    cancel_event=cancel_event,
                    progress_cb=progress_cb,
                ),
                start=1,
            ):
                if processed_pages % 10 == 0:
                    _emit_log(logger, f"[INFO] {pdf.name}: avance {processed_pages} paginas...")
                all_items.extend(items or [])
                if meta:
                    all_meta.append(meta)
        except PipelineCancelled:
            cancelled = True
            _emit_log(logger, "[INFO] Cancelacion solicitada por el usuario.")
            break

        if processed_pages == 0:
            _emit_log(logger, f"[INFO] {pdf.name}: sin paginas (posible PDF vacio)")
        else:
            _emit_log(logger, f"[INFO] {pdf.name}: paginas procesadas={processed_pages}")
        if skipped_pages_log:
            all_skipped.extend(skipped_pages_log)

    if cancelled:
        elapsed = time.time() - total_start
        return {
            "cancelled": True,
            "output_path": str(out_path),
            "pdfs": len(pdfs),
            "albaranes_totales": int(total_pages or 0),
            "albaranes_procesados": 0,
            "albaranes_fallidos": int(total_pages or 0),
            "duracion_segundos": round(elapsed, 2),
            "errors": errors,
        }

    all_items = _merge_stage_entries(all_items, DETAIL_COLS, DETAIL_STRING_COLS)
    for row in all_items:
        _normalize_supedido_field(row)
    _repair_crosspage_header_keys(all_items)
    for idx, row in enumerate(all_items):
        if (not row.get("Codigo")) and row.get("CantidadServida") not in (None, "") and row.get("Importe") not in (None, ""):
            prov = (row.get("Proveedor") or "UNK").upper()
            row["Codigo"] = f"UNK_{prov}_{idx + 1:04d}"
            warn = row.get("ParseWarn") or ""
            if "missing_code_placeholder" not in warn:
                row["ParseWarn"] = (warn + "|missing_code_placeholder").strip("|")
    _normalize_numeric_rows(all_items)
    all_meta = _merge_stage_entries(all_meta, META_COLS, META_STRING_COLS)
    for meta in all_meta:
        _normalize_supedido_field(meta)

    df_detail = pd.DataFrame(all_items)
    for c in DETAIL_COLS:
        if c not in df_detail.columns:
            df_detail[c] = "" if c in ("Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo", "Descripcion", "Pdf", "ParseWarn", "OcrStage") else np.nan
    df_detail = df_detail[DETAIL_COLS]

    df_meta = pd.DataFrame(all_meta)
    for c in META_COLS:
        if c not in df_meta.columns:
            df_meta[c] = "" if c in ("Proveedor", "Parser", "AlbaranNumero", "FechaAlbaran", "SuPedidoCodigo", "OcrStage") else np.nan
    df_meta = df_meta[META_COLS]

    out_written = _write_excel_safe(out_path, df_detail, df_meta, add_provider_summary=False)

    # --- resto de outputs/summary ---
    summary_placeholder = {
        "df_detail": df_detail,
        "results_detail": results_detail,
        "errors": errors,
        "all_skipped": all_skipped,
        "page_trace_rows": page_trace_rows,
        "pdfs": pdfs,
        "total_start": total_start,
        "total_pages": total_pages,
        "out_dir": out_dir,
        "out_path": out_written,
        "ocr_available": ocr_available,
    }
    return _finalize_run_outputs(summary_placeholder, logger)


def _finalize_run_outputs(state: dict, logger: logging.Logger | None) -> dict:
    import time

    df_detail = state["df_detail"]
    results_detail = state["results_detail"]
    errors = state["errors"]
    all_skipped = state["all_skipped"]
    page_trace_rows = state["page_trace_rows"]
    pdfs = state["pdfs"]
    total_start = state["total_start"]
    total_pages = state["total_pages"]
    out_dir = state["out_dir"]
    out_path = state["out_path"]
    ocr_available = state["ocr_available"]

    try:
        df_err = pd.DataFrame(errors) if errors else pd.DataFrame(columns=["pdf", "page", "detected", "parser_id", "items", "msg"])
        if not df_detail.empty and "ParseWarn" in df_detail.columns:
            df_fb = df_detail[df_detail["ParseWarn"] == "fallback_no_parse"].copy()
        else:
            df_fb = pd.DataFrame()
        err_path = out_dir / "albaranes_errores.xlsx"
        with pd.ExcelWriter(err_path, engine="xlsxwriter") as writer:
            df_err = _normalize_df_types(df_err)
            df_err.to_excel(writer, index=False, sheet_name="Errores")
            if not df_fb.empty:
                df_fb = _normalize_df_types(df_fb)
                df_fb.to_excel(writer, index=False, sheet_name="Fallbacks_en_Detalle")
    except Exception as _ex:
        _emit_log(logger, f"[WARN] No se pudo escribir albaranes_errores.xlsx: {_ex!r}", logging.WARNING)

    trace_cfg = TRACE_OUTPUT or {}
    if trace_cfg.get("enable_page_log") and page_trace_rows:
        trace_df = pd.DataFrame(page_trace_rows)
        if trace_cfg.get("extra_columns"):
            for col in trace_cfg["extra_columns"]:
                if col not in trace_df.columns:
                    trace_df[col] = ""
            ordered = [col for col in trace_cfg["extra_columns"] if col in trace_df.columns]
            ordered.extend(c for c in trace_df.columns if c not in ordered)
            trace_df = trace_df[ordered]
        excel_path = trace_cfg.get("page_log_excel")
        if excel_path:
            excel_path = Path(excel_path)
            if not excel_path.is_absolute():
                excel_path = Path.cwd() / excel_path
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                trace_df.to_excel(excel_path, index=False, engine="xlsxwriter")
            except Exception as exc:
                _emit_log(logger, f"[WARN] No se pudo escribir el log de paginas en Excel ({excel_path}): {exc}", logging.WARNING)
        json_path = trace_cfg.get("page_log_json")
        if json_path:
            json_path = Path(json_path)
            if not json_path.is_absolute():
                json_path = Path.cwd() / json_path
            json_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                json_path.write_text(trace_df.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                _emit_log(logger, f"[WARN] No se pudo escribir el log de paginas en JSON ({json_path}): {exc}", logging.WARNING)

    if all_skipped:
        skipped_df = pd.DataFrame(all_skipped)
        skipped_path = out_dir / "paginas_descartadas.csv"
        try:
            skipped_df.to_csv(skipped_path, index=False, encoding="utf-8")
            _emit_log(logger, f"[INFO] Paginas descartadas (ultima hoja sin lineas): {len(all_skipped)} (ver {skipped_path.name})")
        except Exception as exc:
            _emit_log(logger, f"[WARN] No se pudo escribir paginas_descartadas.csv: {exc}", logging.WARNING)
    else:
        _emit_log(logger, "[INFO] No se descartaron paginas por ser ultimas sin lineas.")

    if total_pages is None:
        total_pages = int(df_detail["Pagina"].nunique()) if not df_detail.empty else 0

    processed_pages = sum(1 for r in results_detail if r.get("items", 0) > 0 or r.get("skipped_last_page"))
    failed_pages = int(total_pages) - int(processed_pages)
    _emit_log(logger, f"[RESUMEN] Albaranes totales: {total_pages} | Procesados OK: {processed_pages} | Fallidos: {failed_pages}")

    if errors:
        _emit_log(logger, "[ERRORES]")
        for e in errors:
            _emit_log(logger, f"  - {e['pdf']} p.{e['page']}: {e['msg']} [detect={e['detected']}, parser={e['parser_id']}, items={e['items']}]")
    else:
        _emit_log(logger, "[ERRORES] (sin errores)")

    if ocr_available:
        _emit_log(logger, "[OCR] Pipeline hibrido activo (revisa columnas OcrStage/OcrPipeline en los Excels).")

    elapsed = time.time() - total_start
    summary = {
        "pdfs": len(pdfs),
        "albaranes_totales": int(total_pages),
        "albaranes_procesados": int(processed_pages),
        "albaranes_fallidos": int(failed_pages),
        "duracion_segundos": round(elapsed, 2),
        "cancelled": False,
    }
    dbg_run_summary(summary, errors)

    try:
        txt_path = out_dir / "albaranes_errores.txt"
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(f"[RESUMEN] Albaranes totales: {total_pages} | Procesados OK: {processed_pages} | Fallidos: {failed_pages}\n\n")
            if errors:
                fh.write("[ERRORES]\n")
                for e in errors:
                    fh.write(f" - {e.get('pdf')} p.{e.get('page')}: {e.get('msg')} [detect={e.get('detected')}, parser={e.get('parser_id')}, items={e.get('items')}]\n")
            else:
                fh.write("Sin errores registrados.\n")
    except Exception as _ex:
        _emit_log(logger, f"[WARN] No se pudo escribir albaranes_errores.txt: {_ex!r}", logging.WARNING)

    mins, secs = divmod(elapsed, 60)
    _emit_log(logger, f"\nOK - Generado master: {out_path}")
    _emit_log(logger, f"[RESUMEN] Duracion total: {int(mins)}m {secs:.1f}s")

    summary["errors"] = errors
    summary["output_path"] = str(out_path)
    return summary

# ---------------- CLI principal ----------------
def main():
    _ensure_utf8_console()
    ap = argparse.ArgumentParser(description="Extractor de albaranes multiproveedor")
    ap.add_argument("--in", dest="input_path", required=False, help="Carpeta con PDFs o ruta a un PDF")
    ap.add_argument("--out", dest="output_xlsx", required=False, help="Ruta del Excel master")
    ap.add_argument("--recursive", action="store_true", help="Buscar PDFs tambien en subcarpetas")
    ap.add_argument("--config-ui", action="store_true", help="Abrir la interfaz grafica")
    ap.add_argument("--no-ui", action="store_true", help="Modo batch: no mostrar interfaz grafica")
    ap.add_argument("--self-test", action="store_true", help="Ejecutar diagnostico completo de instalacion/OCR")
    ap.add_argument("--self-test-out", dest="self_test_out", required=False, help="Carpeta donde guardar el informe de diagnostico")
    args = ap.parse_args()

    base_dir = app_dir()

    _apply_user_settings(base_dir)

    if args.self_test:
        from albaranes_tool.selftest import run_installation_selftest

        report = run_installation_selftest(
            base_dir=base_dir,
            run_pipeline_fn=run_pipeline,
            config={
                "OCR_CONFIG": OCR_CONFIG,
                "OCR_WORKFLOW": OCR_WORKFLOW,
                "OCR_DEBUG": OCR_DEBUG,
            },
            output_dir=Path(args.self_test_out) if args.self_test_out else None,
            keep_artifacts=True,
        )
        print(f"[SELFTEST] {'OK' if report.get('ok') else 'FAIL'}")
        print(f"[SELFTEST] Informe: {report.get('report_dir')}")
        sys.exit(0 if report.get("ok") else 1)

    should_launch_gui = TK_AVAILABLE and not args.no_ui and (
        args.config_ui or (not args.input_path and not args.output_xlsx)
    )
    if should_launch_gui:
        from albaranes_tool.gui_app import launch_gui
        from albaranes_tool.selftest import run_installation_selftest

        defaults = {
            "PRECHECK_ENABLED": PRECHECK_ENABLED,
            "STOP_ON_ERROR": STOP_ON_ERROR,
            "DEBUG_ENABLED": DEBUG_ENABLED,
            "SUPEDIDO_TRUNCATED_ENABLED": bool(SUPEDIDO_TRUNCATED_ENABLED),
            "OCR_CONFIG": {
                "ocrmypdf": {"enabled": bool((OCR_CONFIG or {}).get("ocrmypdf", {}).get("enabled", False))},
                "doctr": {"enabled": bool((OCR_CONFIG or {}).get("doctr", {}).get("enabled", False))},
                "tesseract": {"enabled": bool((OCR_CONFIG or {}).get("tesseract", {}).get("enabled", False))},
            },
            "OCR_WORKFLOW": {"ocr_force_all": bool((OCR_WORKFLOW or {}).get("ocr_force_all", False))},
        }
        launch_gui(
            base_dir=base_dir,
            run_pipeline_fn=run_pipeline,
            selftest_fn=run_installation_selftest,
            apply_settings_fn=_apply_settings_dict,
            load_settings_fn=load_settings,
            save_settings_fn=save_settings,
            defaults=defaults,
        )
        return

    if args.input_path:
        in_path = Path(args.input_path)
    elif args.no_ui:
        print("Ruta carpeta PDFs:", file=sys.stderr)
        raw_in = input("> ").strip()
        in_path = Path(raw_in) if raw_in else Path("")
    else:
        in_path = pick_input_folder()
    if not in_path.exists():
        print(f"Ruta no encontrada: {in_path}", file=sys.stderr)
        sys.exit(2)

    if args.output_xlsx:
        out_path = Path(args.output_xlsx)
    elif args.no_ui:
        out_path = in_path / "albaranes_master.xlsx" if in_path.is_dir() else in_path.parent / "albaranes_master.xlsx"
    else:
        out_path = pick_output_file(in_path if in_path.is_dir() else in_path.parent)

    try:
        run_pipeline(in_path, out_path, recursive=args.recursive)
    except Exception as exc:
        print(f"[ERROR] {exc!r}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()


