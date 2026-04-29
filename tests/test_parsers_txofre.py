from parsers import txofre


def test_txofre_ignores_spurious_no_code_fragment():
    class DummyPage:
        def __init__(self, txt: str):
            self._txt = txt

        def extract_text(self):
            return self._txt

    txt = "\n".join(
        [
            "Nº ALBARÁN 2026/01/001337 FECHA 28/01/26",
            "DIVISION/OBRA CIF S/PEDIDO",
            "LOYOLA NORTE S.A. A20074738 LIS TELEFONO",
            "ARTÍCULO DESCRIPCIÓN CANTIDAD PRECIO IMPORTE",
            "2 LA MANANA 1,00",
            "ALY170610 JGO. LLAVES ALLEN BOLA 9PZAS. ALYCO 2,00 7,5000 15,00",
            "TOTAL ALBARÁN",
        ]
    )
    items, meta = txofre.parse_page(DummyPage(txt), 2)
    assert meta["AlbaranNumero"] == "2026/01/001337"
    assert len(items) == 1
    assert items[0]["Codigo"] == "ALY170610"
    assert abs(float(items[0]["Importe"]) - 15.0) < 0.01

