from parsers import alkain


def test_find_albaran_prioritizes_fecha_albaran_row_with_ocr_noise():
    lines = [
        "ALKAIN",
        "ALBARAN",
        "C.I.F.: A20074738",
        (
            "L -r - . - 2 F 5 E /0 C 2 H /2 A 6 [ - A 2 - 6 L 1 B 0 A 0 R 81 A 1 N 7 1 1 "
            "FATIMA INCIARTE - A 94 T 3 E 6 N 4 D 2 I 0 D 2 O 5- 4 P 0 O 1 R 2"
        ),
        "ARTICULO DESCRIPCION CANTIDAD PRECIO IMPORTE",
        "CONDICIONES GENERALES DE VENTA:",
        "El 30825382 | m Za. i== Tai yg",
    ]
    got = alkain._find_albaran(lines, " ".join(lines))  # noqa: SLF001
    assert got == "261008117"


def test_find_albaran_from_clean_fecha_albaran_row():
    lines = [
        "FECHA ALBARAN ATENDIDO POR HOJA",
        "03/02/26 261004599 IBON IRAOLA - 689138229 - ferreteria@alkain.com 1/1",
        "ARTICULO DESCRIPCION CANTIDAD PRECIO IMPORTE",
    ]
    got = alkain._find_albaran(lines, " ".join(lines))  # noqa: SLF001
    assert got == "261004599"

