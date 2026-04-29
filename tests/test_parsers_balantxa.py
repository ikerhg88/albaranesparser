from parsers import balantxa


class DummyPage:
    def __init__(self, txt: str):
        self._txt = txt

    def extract_text(self):
        return self._txt


def test_balantxa_extracts_supedido_from_concept_line():
    txt = "\n".join(
        [
            "NOTA DE ENTREGA N°: 17239",
            "FECHA: 06-11-2025",
            "CLIENTE: LOYOLA NORTE, S.A.",
            "FECHA CONCEPTO IMPORTE",
            "06-11-2025 Pedido no 25.622/01:",
            "Suministro de una chapa galvanizada 3mm, cortada y plegada a medida.",
            "23,40",
        ]
    )
    items, meta = balantxa.parse_page(DummyPage(txt), 1)
    assert meta["SuPedidoCodigo"] == "25.622/01"
    assert items[0]["SuPedidoCodigo"] == "25.622/01"
    assert meta["AlbaranNumero"] == "17239"


def test_balantxa_extracts_supedido_with_npedido_label():
    txt = "\n".join(
        [
            "NOTA DE ENTREGA N°: 17240",
            "Nº Pedido: 25622/01",
            "FECHA CONCEPTO IMPORTE",
            "06-11-2025 Suministro de pieza",
            "120,00",
        ]
    )
    _, meta = balantxa.parse_page(DummyPage(txt), 1)
    assert meta["SuPedidoCodigo"] == "25622/01"

