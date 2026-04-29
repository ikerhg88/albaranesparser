from parsers import juper


def test_parse_row_pending_qty():
    row = "JP141002 BOTA PROTOMASTOR FULL SAFETY VERDE/NEGRO T.41 1 Pendiente 1"
    parsed = juper._parse_row(row)  # noqa: SLF001
    assert parsed is not None
    qty, code, concept = parsed
    assert code == "JP141002"
    assert qty == 0.0
    assert "BOTA PROTOMASTOR" in concept


def test_parse_row_ocr_code_correction():
    row = "3P141002 BOTA PROTOMASTOR FULL SAFETY VERDE/NEGRO T.43 1 PAR 1 PAR"
    parsed = juper._parse_row(row)  # noqa: SLF001
    assert parsed is not None
    qty, code, _ = parsed
    assert code == "JP141002"
    assert qty == 1.0
