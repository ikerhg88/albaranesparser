from parsers import elicetxe


def test_extract_header_context_line():
    lines = [
        "ALBARAN FECHA CODIGO N PEDIDO",
        "600200597 09/02/2026 620 26.010/81",
    ]
    text = " ".join(lines)
    albaran, fecha, supedido = elicetxe._extract_header(lines, text)  # noqa: SLF001
    assert albaran == "600200597"
    assert supedido == "26.010/81"
    assert fecha


def test_parse_row_reference_qty_price():
    row = "VARIOS 1 3002005970001 10,00 1 CABLE VV-K DE 25G2.5mm2 0,000"
    parsed = elicetxe._parse_row(row)  # noqa: SLF001
    assert parsed is not None
    qty, code, concept, price, imp = parsed
    assert qty == 10.0
    assert code == "3002005970001"
    assert "CABLE VV-K" in concept
    assert price == 0.0
    assert imp is None
