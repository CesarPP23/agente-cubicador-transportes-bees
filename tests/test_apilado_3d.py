import config
from models import Cama, Pallet
from src.apilado_3d import _consolidar_pallets, armar_pallets


def _info(sku, categoria="Licores", nivel=1):
    return {
        "descripcion": f"Producto {sku}",
        "categoria": categoria,
        "nivel_categoria": nivel,
        "peso_no_validable": False,
        "peso_caja": 1.0,
    }


def test_orden_de_estabilidad_se_respeta_sin_importar_orden_de_entrada():
    cama_lacteos = Cama(categorias=["Lácteos"], altura_cama=20, cantidades={"L1": 5}, nivel_categoria=2)
    cama_licores = Cama(categorias=["Licores"], altura_cama=20, cantidades={"L0": 5}, nivel_categoria=1)

    camas_por_cd = {"BK31": [cama_lacteos, cama_licores]}
    info_sku = {"L0": _info("L0", "Licores", 1), "L1": _info("L1", "Lácteos", 2)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    categorias_en_orden = [cama.categorias[0] for cama in pallets[0].camas]
    assert categorias_en_orden.index("Licores") < categorias_en_orden.index("Lácteos")


def test_remate_nunca_comparte_pallet_y_prioriza_mayor_remanente():
    cama_comestibles = Cama(
        categorias=["Comestibles"], altura_cama=20, cantidades={"C1": 50}, nivel_categoria=None
    )
    cama_cigarros = Cama(categorias=["Cigarros"], altura_cama=20, cantidades={"G1": 5}, nivel_categoria=None)

    camas_por_cd = {"BK31": [cama_comestibles, cama_cigarros]}
    info_sku = {
        "C1": _info("C1", "Comestibles", None),
        "G1": _info("G1", "Cigarros", None),
    }

    pallets = armar_pallets(camas_por_cd, info_sku)

    for pallet in pallets:
        categorias = {cama.categorias[0] for cama in pallet.camas}
        assert not ({"Comestibles", "Cigarros"} <= categorias)

    primer_pallet_categorias = {cama.categorias[0] for cama in pallets[0].camas}
    assert "Comestibles" in primer_pallet_categorias


def test_cierre_forzado_bajo_altura_minima_se_marca_parcial():
    cama = Cama(categorias=["Licores"], altura_cama=50, cantidades={"L0": 5}, nivel_categoria=1)
    camas_por_cd = {"BK31": [cama]}
    info_sku = {"L0": _info("L0", "Licores", 1)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    assert pallets[0].altura_final < config.ALTURA_TOTAL_MIN
    assert config.ESTADO_PALLET_PARCIAL in pallets[0].estado


def test_consolidacion_nunca_mueve_una_cama_hacia_un_pallet_mas_chico():
    # Reproduce el bug real: un pallet ya casi completo (186.7cm) no debe perder su
    # cama de remate para "ayudar" a un pallet mucho más chico (66.02cm) — eso solo
    # empeora el resultado neto.
    bueno = Pallet(id="A", cd="X", tipo="Mixto", altura_final=186.7)
    bueno.camas = [
        Cama(categorias=["Licores"], altura_cama=166.1, cantidades={"L1": 5}, nivel_categoria=1),
        Cama(categorias=["Comestibles"], altura_cama=20.6, cantidades={"C1": 3}, nivel_categoria=None),
    ]
    malo = Pallet(id="B", cd="X", tipo="Mixto", altura_final=66.02)
    malo.camas = [Cama(categorias=["Comestibles"], altura_cama=51.1, cantidades={"C2": 2}, nivel_categoria=None)]

    info_sku = {
        "L1": _info("L1", "Licores", 1),
        "C1": _info("C1", "Comestibles", None),
        "C2": _info("C2", "Comestibles", None),
    }

    resultado = _consolidar_pallets([bueno, malo], info_sku)
    pallet_a = next(p for p in resultado if p.id == "A")
    assert len(pallet_a.camas) == 2
    assert any(c.categorias[0] == "Comestibles" for c in pallet_a.camas)
