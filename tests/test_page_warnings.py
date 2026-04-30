import main


def test_reference_data_requires_at_least_one_header_reference():
    items = [
        {
            "AlbaranNumero": "",
            "FechaAlbaran": "",
            "SuPedidoCodigo": "",
            "Descripcion": "linea sin cabecera",
        }
    ]

    assert not main._has_any_reference_data(items, {})
    assert main._missing_reference_fields(items, {}) == [
        "AlbaranNumero",
        "FechaAlbaran",
        "SuPedidoCodigo",
    ]


def test_reference_data_accepts_any_header_reference_from_meta_or_rows():
    items = [{"AlbaranNumero": "", "FechaAlbaran": "", "SuPedidoCodigo": "A260226"}]

    assert main._has_any_reference_data(items, {})
    assert main._missing_reference_fields(items, {"FechaAlbaran": "02/03/2026"}) == ["AlbaranNumero"]


def test_page_warning_accumulates_codes_and_actions():
    errors = []
    trace = {}

    main._register_page_warning(
        errors,
        trace,
        pdf_name="test.pdf",
        page=1,
        detected="BERDIN",
        parser_id="berdin",
        items_count=0,
        code="REFERENCIAS_NO_DETECTADAS",
        message="sin referencias",
        missing_fields=["AlbaranNumero"],
        action="revisar cabecera",
    )
    main._register_page_warning(
        errors,
        trace,
        pdf_name="test.pdf",
        page=1,
        detected="BERDIN",
        parser_id="berdin",
        items_count=0,
        code="PARSER_SIN_LINEAS",
        message="sin lineas",
        action="revisar parser",
    )

    assert len(errors) == 2
    assert trace["WarningCode"] == "REFERENCIAS_NO_DETECTADAS;PARSER_SIN_LINEAS"
    assert trace["MissingReferenceFields"] == "AlbaranNumero"
    assert trace["DiagnosticAction"] == "revisar cabecera | revisar parser"
