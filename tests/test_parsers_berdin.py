from parsers import berdin


def test_normalize_code_preserves_leading_digit():
    """
    Antes se perdía el primer dígito en códigos de 9 cifras al recortar '1' inicial.
    Ahora debe conservarse.
    """
    assert berdin._normalize_code("110116576") == "110116576"


def test_strip_trailing_internal_order_from_supedido():
    assert berdin._strip_trailing_internal_order("26.501/01/H519161") == "26.501/01/H"
    assert berdin._strip_trailing_internal_order("A260129/IA110109405") == "A260129/IA1"
    assert berdin._strip_trailing_internal_order("26.501/01/H519162LOE") == "26.501/01/H"


def test_extract_supedido_from_header_row_compact():
    lines = [
        "Su Pedido   Nuestro pedido   Fecha de pedido",
        "A260129/IA110109405 29/01/2026",
    ]
    assert berdin._extract_supedido_from_header_row(lines) == "A260129/IA1"


def test_extract_supedido_when_su_header_is_corrupted():
    lines = [
        "do = = = Nuestro pedido Fecha de pedido",
        "A-040226-F] 10109570 05/02/2026",
    ]
    assert berdin._extract_supedido_from_header_row(lines) == "A040226/FJ"


def test_extract_supedido_when_only_fecha_header_is_visible():
    lines = [
        "Fecha de pedido",
        "26008/07/Y 10109723 11/02/2026",
    ]
    assert berdin._extract_supedido_from_header_row(lines) == "26008/07/Y"


def test_extract_supedido_with_split_ia_suffix():
    lines = [
        "Su Pedido Nuestro pedido Fecha de pedido",
        "25.034/05/IAl 7 519467 04/02/2026",
    ]
    assert berdin._extract_supedido_from_header_row(lines) == "25.034/05/IA17"


def test_normalize_supedido_with_middle_dot_separator():
    assert berdin._normalize_supedido("25.625·01/E") == "25.625-01/E"


def test_supedido_quality_rejects_malformed_patterns():
    assert berdin._is_plausible_supedido("26.501/01/H")
    assert not berdin._is_plausible_supedido("2/-01/01/H")


def test_parse_page_prefers_header_block_with_valid_supedido():
    class DummyPage:
        def __init__(self, txt: str):
            self._txt = txt

        def extract_text(self):
            return self._txt

    txt = "\n".join(
        [
            "Albaran numero: 10183593",
            "Su Pedido Nuestro pedido Fecha de pedido",
            "25.034/01/IA22 519468 04/02/2026",
            "POS CODIGO Descripcion C.PEDIDA C.SERVIDA C.PEDTE UDS/P. PRECIO DTO IMPORTE",
            "1 10136268 Magnetotermico ACTI9 1 1 1 255,920 89,00 28,15",
            "Albaran numero: 10183593",
            "Su Pedido Nuestro pedido Fecha de pedido",
            "25.034/01/1422 519468 04/02/2026",
            "POS CODIGO Descripcion C.PEDIDA C.SERVIDA C.PEDTE UDS/P. PRECIO DTO IMPORTE",
            "1 10136268 Magnetotermico ACTI9 1 1 1 255,920 89,00 28,15",
        ]
    )
    _, meta = berdin.parse_page(DummyPage(txt), 1)
    assert meta["SuPedidoCodigo"] == "25.034/01/IA22"


def test_parse_page_prefers_clean_block_over_malformed_supedido():
    class DummyPage:
        def __init__(self, txt: str):
            self._txt = txt

        def extract_text(self):
            return self._txt

    txt = "\n".join(
        [
            "Albaran numero: 10182697",
            "Su Pedido Nuestro pedido Fecha de pedido",
            "2/-01/01/H 519162 12/01/2026",
            "POS CODIGO Descripcion C.PEDIDA C.SERVIDA C.PEDTE UDS/P. PRECIO DTO IMPORTE",
            "1 110125214 Rejilla 8 8 1 31,070 50,20 123,78",
            "Albaran numero: 10182697",
            "Su Pedido Nuestro pedido Fecha de pedido",
            "26.501/01/H 519162 12/01/2026",
            "POS CODIGO Descripcion C.PEDIDA C.SERVIDA C.PEDTE UDS/P. PRECIO DTO IMPORTE",
            "1 110125214 Rejilla 8 8 1 31,070 50,20 123,78",
        ]
    )
    _, meta = berdin.parse_page(DummyPage(txt), 1)
    assert meta["SuPedidoCodigo"] == "26.501/01/H"


def test_parse_page_recovers_compact_price_dto_tail():
    class DummyPage:
        def __init__(self, txt: str):
            self._txt = txt

        def extract_text(self):
            return self._txt

    txt = "\n".join(
        [
            "Albaran numero: 10182697",
            "Su Pedido Nuestro pedido Fecha de pedido",
            "26.501/01/H 519162 12/01/2026",
            "POS CODIGO Descripcion C.PEDIDA C.SERVIDA C.PEDTE UDS/P. PRECIO DTO IMPORTE",
            "1 10125214 Rejilla salida mecan 92x92 SEE NSYCAG92LPF 8 8 1 310705020 12378",
            "Neto Comercial 123,78",
        ]
    )
    items, _ = berdin.parse_page(DummyPage(txt), 1)
    assert items
    item = items[0]
    assert item["Codigo"] == "10125214"
    assert abs(float(item["Importe"]) - 123.78) < 0.01
    assert abs(float(item["PrecioUnitario"]) - 31.07) < 0.05
    assert abs(float(item["DescuentoPct"]) - 50.2) < 0.05
