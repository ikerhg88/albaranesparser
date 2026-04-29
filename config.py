# config.py
# ========== CONFIGURACION GLOBAL ==========
# Debug general (paginas, deteccion, parsers)
DEBUG_ENABLED = True                # True/False
DEBUG_LEVEL = "verbose"             # "off" | "basic" | "verbose"
DEBUG_DIR = "debug"                 # carpeta de volcados

# Pre-revision de PDFs (conteo de albaranes/paginas)
PRECHECK_ENABLED = True             # True para mostrar el conteo antes de procesar

# Politica de ejecucion
STOP_ON_ERROR = False               # si True, aborta al primer error grave

# OCR multinivel configurable por etapa
OCR_CONFIG = {
    "cache_dir": "debug/ocr_cache",
    "ocrmypdf": {
        "enabled": False,
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
    "doctr": {
        "enabled": False,
        "detector": "db_resnet50",
        "recognizer": "crnn_vgg16_bn",
        "use_gpu": False,
        # El pipeline interno ya procesa 1 página cada vez; el batch se evita para DBNet.
        "batch_size": 0,
    },
    "tesseract": {
        "enabled": True,
        "language": "spa+eng",
        "oem": 1,
        "psm": 11,
        "cmd": "external_bin/tesseract/tesseract.exe",
    },
    "preprocess": {
        "enabled": True,
        "dpi": 300,
        "binarize": True,
        "deskew": True,
    },
}

# Campos clave para decidir si una pagina requiere OCR adicional
OCR_REQUIRED_FIELDS = [
    "AlbaranNumero",
    "SuPedidoCodigo",
    "CantidadServida",
    "Importe",
]

# Opciones de debug especificas de OCR
OCR_DEBUG = {
    "per_stage_files": True,
}

# Estrategia de OCR
OCR_WORKFLOW = {
    "ocr_force_all": False,
    "ocr_skip_providers": [],
}

# Heuristicas para decidir si se relanza OCR en una pagina concreta
OCR_HEURISTICS = {
    # densidad minima de texto (caracteres/pulgada^2 aprox) antes de forzar OCR
    "density_threshold": 0.0008,
    # caracteres minimos detectados; si no se alcanza se intentara OCR
    "min_chars": 120,
    # lineas minimas vistas en el texto base antes de considerar OCR
    "min_lines": 4,
    # entropia minima (Shannon, base 2) para considerar que el texto es legible
    "min_entropy": 3.3,
}

# Reglas generales para normalizar codigos "Su Pedido"
SUPEDIDO_TRUNCATED_ENABLED = True

SUPEDIDO_RULES = {
    "_default": {
        "min_length": 5,
        "min_digits": 3,
        "require_alpha": False,
    },
    "BERDIN": {
        "min_length": 5,
        "min_digits": 3,
        "require_alpha": False,
        # BERDIN suele incluir sufijos de ruido OCR (/Y, /H, /IA1, ...)
        # y queremos normalizarlo al formato compacto del resto.
        "preserve_alpha_suffix": False,
    },
    "ELEKTRA": {
        "min_length": 3,
        "min_digits": 0,
        "require_alpha": False,
        "allow_numeric": True,
        # OCR frecuente en este proveedor: prefijo '1' espurio en códigos de 6 dígitos.
        "strip_leading_one_6d": True,
    },
    "GABYL": {
        "min_length": 3,
        "min_digits": 1,
        "require_alpha": False,
        "allow_numeric": True,
        # Igual criterio que BERDIN: compactar y eliminar sufijos OCR ruidosos.
        "preserve_alpha_suffix": False,
    },
    "CLC": {
        "min_length": 2,
        "min_digits": 0,
        "require_alpha": False,
        "allow_numeric": True,
    },
    "ALKAIN": {
        "min_length": 5,
        "min_digits": 5,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "SALTOKI": {
        "min_length": 2,
        "min_digits": 0,
        "require_alpha": False,
        "allow_numeric": True,
        # Normaliza variantes OCR con sufijos (/Y, /H, /IA...) al formato compacto.
        "preserve_alpha_suffix": False,
    },
    "AELVASA": {
        "min_length": 5,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        # AELVASA suele traer REF con sufijos de traza que no forman parte del código base.
        "preserve_alpha_suffix": False,
    },
    "BACOLSA": {
        "min_length": 4,
        "min_digits": 4,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "BALANTXA": {
        "min_length": 0,
        "min_digits": 0,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "LEYCOLAN": {
        "min_length": 4,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "ARTESOLAR": {
        "min_length": 4,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "EFECTO LED": {
        "min_length": 4,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "LUX MAY": {
        "min_length": 4,
        "min_digits": 4,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "ADARRA": {
        "min_length": 5,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "JUPER": {
        "min_length": 4,
        "min_digits": 4,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": True,
    },
    "ELICETXE": {
        "min_length": 5,
        "min_digits": 3,
        "require_alpha": False,
        "allow_numeric": True,
        "no_truncate": False,
        "preserve_alpha_suffix": False,
    },
    "TXOFRE": {
        "min_length": 3,
        "min_digits": 0,
        "require_alpha": False,
        "allow_numeric": True,
        "preserve_alpha_suffix": False,
    },
}

# Pistas especificas por proveedor (regex adicionales)
PARSER_HINTS = {
    "BERDIN": {
        "su_pedido_patterns": [
            r"\b\d{2}\.\d{3}/[A-Z0-9]+\b",
            r"\b[A-Z]{1,3}\.\d{3}/[A-Z0-9]{1,5}\b",
        ],
    },
    "CLC": {
        "client_code": "00000136",
    },
    "SALTOKI": {
        "client_code": "185519",
    },

}

# Ruta del log detallado por pagina (deteccion/ocr)
TRACE_OUTPUT = {
    "enable_page_log": True,
    "page_log_excel": "debug/detalle_paginas.xlsx",
    "page_log_json": "debug/detalle_paginas.json",
    # Columnas recomendadas (pueden ampliarse desde codigo segun necesidad)
    "extra_columns": [
        "Pdf",
        "Pagina",
        "ProveedorDetectado",
        "Parser",
        "OcrStage",
        "OcrPipeline",
        "Items",
        "NeedsRequired",
        "Fallback",
        "OcrApplied",
        "OcrForceAll",
        "CharCount",
        "LineCount",
        "Density",
        "Entropy",
        "CharCountPre",
        "LineCountPre",
        "DensityPre",
        "EntropyPre",
        "OcrTriggered",
        "TriggerReason",
    ],
}

# Reglas globales de normalizacion numerica (descuentos, importes, etc.)
NUMERIC_RULES = {
    # Si True, aplica correcciones automaticas cuando el descuento supera 100
    # y genera avisos cuando el importe no coincide con Precio * Cantidad * (1 - descuento).
    "enforce_discount_formula": True,
    # Margen de diferencia aceptado entre el importe calculado y el detectado.
    "importe_tolerance": 0.05,
}

# Reglas auxiliares para la deteccion de proveedor a nivel de cabecera/texto
DETECTION_CONFIG = {
    # Alias de marca (en bruto, antes de normalizar a ASCII) para reforzar la deteccion.
    "brand_aliases": {
        "BERDIN": ["BERDIN", "GRUPO BERDIN"],
        "ELEKTRA": ["ELEKTRA", "GRUPO ELEKTRA"],
        "AELVASA": ["AELVASA", "ALMACENES ELECTRICOS VASCONGADOS"],
        "SALTOKI": ["SALTOKI"],
        "GABYL": ["GABYL"],
        "CLC": ["C.L.C", "CLC MAQUINARIA", "CLC"],
        "ALKAIN": ["ALKAIN"],
        "BALANTXA": ["BALANTXA", "CALDERERIA BALANTXA", "BALANTXA.NET"],
        "LEYCOLAN": ["LEYCOLAN", "LEYCOLAN S.A.L", "ILUMINACION Y CONTROL"],
        "ARTESOLAR": ["ARTESOLAR", "ALBARAN DE VENTA", "ARTESOLAR.COM"],
        "BACOLSA": ["BACOLSA", "BACULOS Y COLUMNAS", "BÁCULOS Y COLUMNAS"],
        "Efecto Led": ["EFECTOLED", "EFECTO LED", "EFECTOLED.COM"],
        "LUX MAY": ["LUX MAY", "LUX-MAY", "MANUFACTURAS PLASTICAS MAY"],
    },
    # Patrones (regex) orientativos de cabecera de tabla por proveedor.
    "header_regex": {
        "BERDIN": [
            r"POS.*CODIGO.*DESCRIPCION.*(C\.?PEDIDA)?.*C\.?SERVIDA.*(C\.?PEDTE)?.*UDS/?P.*PRECIO.*DTO.*IMPORTE",
        ],
        "ELEKTRA": [
            r"ARTICULO.*CONCEPTO.*CANTIDAD.*IMPORTE",
        ],
        "AELVASA": [
            r"REFERENCIA.*MARCA.*CONCEPTO.*RAEE.*IMPORTE",
        ],
        "SALTOKI": [
            r"CODIGO.*CONCEPTO.*CANTIDAD.*PRECIO.*IMPORTE",
        ],
        "GABYL": [
            r"CODIGO.*DESCRIPCION.*CANTIDAD.*PRECIO.*IMPORTE",
        ],
        "CLC": [
            r"DENOMIN.*CANTIDAD.*%?DTO.*IMPORTE",
        ],
        "ALKAIN": [
            r"ART.*DESCRIP.*CANTIDAD.*PRECIO.*IMPORTE",
        ],
        "BALANTXA": [
            r"FECHA.*CONCEPTO.*IMPORTE",
        ],
        "LEYCOLAN": [
            r"ART[ÍI]CULO.*DESCRIPCI[ÓO]N.*CANTIDAD.*PRECIO.*TOTAL",
        ],
        "ARTESOLAR": [
            r"REFERENCIA.*CONCEPTOS.*CANTIDAD",
        ],
        "BACOLSA": [
            r"REFERENCIA.*DESCRIPCI[ÓO]N.*CANTIDAD",
        ],
        "Efecto Led": [
            r"REFERENCIA.*DESCRIPCI[ÓO]N.*CANTIDAD.*PRECIO.*IMPORTE",
        ],
        "LUX MAY": [
            r"REFERENCIA.*DESCRIPCI[ÓO]N.*CANTIDAD.*PRECIO",
            r"ALBAR[ÁA]N.*FECHA.*PEDIDO",
        ],
    },
}
