"""parsers/__init__.py
Detección neutral por proveedor + registro uniforme de parsers.
"""
from __future__ import annotations

import re
import sys
import traceback
import importlib
import pkgutil

try:
    from config import DETECTION_CONFIG
except Exception:
    DETECTION_CONFIG = {}

# Cargar módulo generic (fallback). No participa en detección directa.
from . import generic  # noqa: F401

_THIS_PKG = __package__


def _try_import(mod_name: str):
    try:
        return importlib.import_module(f"{_THIS_PKG}.{mod_name}")
    except Exception as ex:
        print(f"[parsers] No se pudo importar '{mod_name}': {ex!r}", file=sys.stderr)
        traceback.print_exc()
        return None


def _is_auxiliary_module_name(mod_name: str) -> bool:
    """Exclude temporary/legacy parser modules from runtime auto-registry."""
    lowered = (mod_name or "").lower()
    aux_tokens = (
        "backup",
        "tmp",
        "_old",
        "old_",
        "minimal",
        "restore",
        "_bad",
        "bad_",
    )
    return any(tok in lowered for tok in aux_tokens)


# Descubrir todos los .py del paquete (excepto __init__ y generic)
_discovered = []
for _m in pkgutil.iter_modules([__path__[0]]):  # type: ignore[name-defined]
    name = _m.name
    if name in {"__init__", "generic"} or _is_auxiliary_module_name(name):
        continue
    mod = _try_import(name)
    if mod is not None:
        _discovered.append(mod)


# Registry builder (PROVIDER_NAME -> {id,name,parse})
REGISTRY: dict[str, dict[str, object]] = {}


def _register(mod):
    try:
        prov = getattr(mod, "PROVIDER_NAME")
        pid = getattr(mod, "PARSER_ID")
        parse_fn = getattr(mod, "parse_page")
    except Exception:
        return
    mod_name = getattr(mod, "__name__", "").split(".")[-1]
    current = REGISTRY.get(prov)
    entry = {"id": pid, "name": prov, "parse": parse_fn, "module": mod_name}
    if current is None:
        REGISTRY[prov] = entry
        return

    canonical_mod = prov.lower()
    current_mod = str(current.get("module", ""))
    new_is_canonical = (mod_name == canonical_mod)
    current_is_canonical = (current_mod == canonical_mod)
    if new_is_canonical and not current_is_canonical:
        REGISTRY[prov] = entry
        return
    if current_is_canonical and not new_is_canonical:
        return


# Registrar todos los parsers detectados con el mismo peso
for m in _discovered:
    _register(m)


def _ascii_upper(s: str) -> str:
    """Uppercase + fold accents to ASCII, robust to mojibake.

    We avoid bespoke replacements and rely on Unicode decomposition.
    """
    if not s:
        return ""
    try:
        import unicodedata as _ud
        s2 = _ud.normalize("NFKD", s.upper())
        return "".join(ch for ch in s2 if not _ud.combining(ch))
    except Exception:
        return s.upper()


def _word_pat(term: str) -> re.Pattern:
    t = _ascii_upper(term)
    t = re.sub(r"\s+", r"\\s+", t)
    return re.compile(rf"(?<!\w){t}(?!\w)", re.I)


# Aliases de marcas por proveedor (nombre, CIF, web, teléfono). Los módulos
# pueden definir BRAND_ALIASES para ampliar.
_FALLBACK_BRAND_ALIASES: dict[str, list[str]] = {
    "TXOFRE": ["TXOFRE", "B-20460812", "TXOFRE.COM", "TXOFRE@TXOFRE.COM", "TXOFRE 943 46 63 94"],
    "BERDIN": ["BERDIN", "GRUPO BERDIN", "B20288372", "BERDIN.COM", "943471119"],
    "ELEKTRA": ["ELEKTRA", "GRUPO ELEKTRA", "ELECTRICIDAD ELEKTRA", "ELEKTRA.ES"],
    "AELVASA": ["AELVASA", "ALMACENES ELECTRICOS VASCONGADOS"],
    "SALTOKI": ["SALTOKI", "SALTOKI SL", "SALTOKI.COM", "CIF B31663609", "948 30 00 30"],
    "GABYL": ["GABYL", "GABYL SA"],
    "CLC": ["C.L.C", "CLC MAQUINARIA", "CLC", "CLC EIBAR"],
    "ALKAIN": ["ALKAIN", "ALCAIN", "ALKAIN.COM", "943 64 20 25"],
}

_CONFIG_BRAND_ALIASES = DETECTION_CONFIG.get("brand_aliases", {}) if isinstance(
    DETECTION_CONFIG, dict
) else {}

def _gather_aliases(prov: str) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for source in (
        _CONFIG_BRAND_ALIASES.get(prov) or [],
        _FALLBACK_BRAND_ALIASES.get(prov, [prov]),
    ):
        for alias in source:
            if not isinstance(alias, str):
                continue
            cleaned = alias.strip()
            if not cleaned:
                continue
            key = cleaned.upper()
            if key in seen:
                continue
            seen.add(key)
            combined.append(cleaned)
    if not combined:
        combined.append(prov)
    return combined

_CONFIG_HEADER_REGEX = DETECTION_CONFIG.get("header_regex", {}) if isinstance(
    DETECTION_CONFIG, dict
) else {}
_HEADER_REGEX_PATTERNS: dict[str, list[re.Pattern]] = {}
for _prov, _patterns in (_CONFIG_HEADER_REGEX or {}).items():
    compiled: list[re.Pattern] = []
    for _pat in _patterns or []:
        if not isinstance(_pat, str) or not _pat.strip():
            continue
        try:
            compiled.append(re.compile(_pat, re.IGNORECASE))
        except re.error as exc:
            print(f"[parsers] Regex invalida para {_prov}: {_pat!r} ({exc})", file=sys.stderr)
    if compiled:
        _HEADER_REGEX_PATTERNS[_prov] = compiled


# Construir patrones de marca de manera neutra y determinista (orden alfabético)
BRAND_PATTERNS: list[tuple[str, list[re.Pattern]]] = []
for prov in sorted(REGISTRY.keys()):
    aliases = _gather_aliases(prov)
    seen_aliases = {a.upper() for a in aliases}
    # permitir que el módulo aporte aliases
    try:
        mod = next((m for m in _discovered if getattr(m, "PROVIDER_NAME", None) == prov), None)
        if mod is not None:
            for extra in getattr(mod, "BRAND_ALIASES", []) or []:
                if not isinstance(extra, str):
                    continue
                cleaned = extra.strip()
                if not cleaned:
                    continue
                key = cleaned.upper()
                if key in seen_aliases:
                    continue
                seen_aliases.add(key)
                aliases.append(cleaned)
    except Exception:
        pass
    pats = [_word_pat(a) for a in aliases]
    BRAND_PATTERNS.append((prov, pats))


from debugkit import dbg_detect_step  # debug hooks


# Checks estructurales por proveedor (cabeceras/pies característicos)
def _is_hdr_berdin(u: str, u2: str) -> bool:
    return (
        ("POS" in u or "POS" in u2)
        and (("CODIGO" in u) or ("CODIGO" in u2))
        and (("UDS/P" in u) or ("UDS" in u) or ("UDS/P" in u2) or ("UDS" in u2))
        and (("PRECIO" in u) or ("PRECIO" in u2))
        and (("DTO" in u) or ("NETO" in u) or ("OTO" in u) or ("DTO" in u2) or ("NETO" in u2) or ("OTO" in u2))
        and (("IMPORTE" in u) or ("IMPORTE" in u2))
    )


def _is_hdr_elektra(u: str, u2: str) -> bool:
    return (("ARTICULO" in u) or ("ARTICULO" in u2)) and ("CONCEPTO" in u2) and ("CANTIDAD" in u2) and (
        "IMPORTE" in u2
    )


def _is_hdr_aelvasa(u: str, u2: str) -> bool:
    return "REFERENCIA" in u2 and "MARCA" in u2 and "CONCEPTO" in u2 and "RAEE" in u2 and "IMPORTE" in u2


def _is_hdr_saltoki(u: str, u2: str) -> bool:
    return (
        "CODIGO" in u2
        and "CONCEPTO" in u2
        and ("CANTIDAD" in u2 or " CANT " in u2 or "CANT " in u2)
        and "PRECIO" in u2
        and "IMPORTE" in u2
    )


def _is_hdr_gabyl(u: str, u2: str) -> bool:
    return "CODIGO" in u2 and "DESCRIPCION" in u2 and "CANTIDAD" in u2 and "PRECIO" in u2 and "IMPORTE" in u2


def _is_hdr_clc(u: str, u2: str) -> bool:
    return "DENOMIN" in u2 and "CANTIDAD" in u2 and "%OTO" in u2 and "IMPORTE" in u2


def _is_hdr_alkain(u: str, u2: str) -> bool:
    return "ART" in u2 and "DESCRIP" in u2 and "CANTIDAD" in u2 and "PRECIO" in u2 and "IMPORTE" in u2


def _footer_hint_scores(up: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    if ("TOTAL: EUR" in up and "S/REF" in up) or (
        "CLIENTE" in up and "ALBARAN" in up and "FECHA" in up and "S/REF" in up
    ):
        scores["SALTOKI"] = scores.get("SALTOKI", 0) + 1
    if ("TOTAL NETO" in up and "FOR - 04.03" in up):
        scores["GABYL"] = scores.get("GABYL", 0) + 1
    if ("NETO COMERCIAL" in up and "TOTAL (EUR)" in up):
        scores["BERDIN"] = scores.get("BERDIN", 0) + 1
    if "TXOFRE" in up or "B-20460812" in up or "TXOFRE.COM" in up:
        scores["TXOFRE"] = scores.get("TXOFRE", 0) + 2
    if "WWW.SALTOKI.COM" in up or "B31663609" in up:
        scores["SALTOKI"] = scores.get("SALTOKI", 0) + 2
    if "ALKAIN" in up or "ALCAIN" in up:
        scores["ALKAIN"] = scores.get("ALKAIN", 0) + 2
    return scores


_HDR_CHECKS = {
    "BERDIN": _is_hdr_berdin,
    "ELEKTRA": _is_hdr_elektra,
    "AELVASA": _is_hdr_aelvasa,
    "SALTOKI": _is_hdr_saltoki,
    "GABYL": _is_hdr_gabyl,
    "CLC": _is_hdr_clc,
    "ALKAIN": _is_hdr_alkain,
}


def detect_proveedor(lines, joined_text, dbgmeta=None):
    """Devuelve el PROVIDER_NAME más probable o 'DESCONOCIDO'."""
    up = _ascii_upper(joined_text or "")
    U = [_ascii_upper(ln or "") for ln in (lines or [])]
    BRAND_WEIGHT = 6  # que un match de marca pese mucho más que una cabecera genérica

    if "DOCUMENTO DE IDENTIFICACION DE RESIDUOS" in up:
        return "DESCONOCIDO"

    def _log(step, info):
        if dbgmeta and isinstance(dbgmeta, dict):
            try:
                dbg_detect_step(dbgmeta.get("pdf", "?"), dbgmeta.get("page", 0), step, info or {})
            except Exception:
                pass

    _log("start", {"n_lines": len(U)})

    # 0) Marcas en texto: sumar coincidencias por proveedor
    scores = {prov: 0 for prov in REGISTRY.keys()}
    brand_hits = {prov: 0 for prov in REGISTRY.keys()}
    for provider_name, rxs in BRAND_PATTERNS:
        hits = sum(1 for rx in rxs if rx.search(up))
        if hits:
            brand_hits[provider_name] += hits
            scores[provider_name] += hits * BRAND_WEIGHT

    # 1) Cabeceras (ventana 2 líneas): sumar sin devolver temprano
    for i in range(len(U)):
        u = U[i]
        v = U[i + 1] if i + 1 < len(U) else ""
        u2 = f"{u} {v}" if v else u
        for prov, fn in _HDR_CHECKS.items():
            if prov in REGISTRY and fn(u, u2):
                scores[prov] = scores.get(prov, 0) + 1
        for prov, regexes in _HEADER_REGEX_PATTERNS.items():
            if prov not in REGISTRY:
                continue
            if any(rx.search(u2) for rx in regexes):
                scores[prov] = scores.get(prov, 0) + 1

    # 2) Pies característicos: sumar
    for prov, inc in _footer_hint_scores(up).items():
        if prov in REGISTRY:
            scores[prov] = scores.get(prov, 0) + inc

    # Si hay marcas detectadas, solo permitir proveedores con la mejor marca,
    # para evitar que una cabecera genérica gane a un match de logo.
    max_brand = max(brand_hits.values()) if brand_hits else 0
    candidate_provs = (
        [prov for prov, hits in brand_hits.items() if hits == max_brand and hits > 0]
        if max_brand > 0
        else list(REGISTRY.keys())
    )

    # Penalizaciones básicas por colisión de marca (negatividad simple)
    # Ej.: si aparece SALTOKI, restar a ALKAIN y viceversa (par solapado frecuente)
    if "SALTOKI" in scores:
        scores["ALKAIN"] = scores.get("ALKAIN", 0) - 1
    if "ALKAIN" in scores:
        scores["SALTOKI"] = scores.get("SALTOKI", 0) - 1

    # Elegir mejor puntuación; criterios de desempate: más brand_hits, luego alfabético
    best_prov = None
    best_score = 0
    for prov in sorted(candidate_provs):
        sc = scores.get(prov, 0)
        if sc > best_score:
            best_score = sc
            best_prov = prov
        elif sc == best_score and sc > 0:
            if brand_hits.get(prov, 0) > brand_hits.get(best_prov, 0):
                best_prov = prov

    if best_prov and best_score > 0:
        _log("detect_result", {"scores": scores, "brand_hits": brand_hits, "selected": best_prov})
        return best_prov

    _log("unknown", {"scores": scores})
    return "DESCONOCIDO"


def get_parser_for(proveedor_name: str):
    if not proveedor_name:
        return None
    # Coincidencia exacta primero
    reg = REGISTRY.get(proveedor_name)
    if reg:
        return reg
    # Coincidencia flexible (aliases/mayúsculas/acentos)
    name = _ascii_upper(proveedor_name)
    for provider_name, rxs in BRAND_PATTERNS:
        if any(rx.search(name) for rx in rxs):
            return REGISTRY.get(provider_name)
    for provider_name in REGISTRY.keys():
        if provider_name != getattr(generic, "PROVIDER_NAME", "GENERIC"):
            if _ascii_upper(provider_name) in name or name in _ascii_upper(provider_name):
                return REGISTRY.get(provider_name)
    return None


__all__ = ["detect_proveedor", "get_parser_for", "REGISTRY"]
