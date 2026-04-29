import common


def test_fix_qty_price_import_recovers_inflated_qty():
    """
    Caso típico OCR Berdin: qty inflada x10 (41 en lugar de 4) con precio y dto coherentes.
    Debe recalcular la cantidad desde importe/precio/dto.
    """
    item = {
        "CantidadServida": 41.0,
        "PrecioUnitario": 57.22,
        "DescuentoPct": 73.56,
        "Importe": 60.52,
    }
    out = common.fix_qty_price_import(item.copy())
    assert out["CantidadServida"] == 4
    # Importes y precio deben quedar coherentes
    assert round(out["Importe"], 2) == 60.52

