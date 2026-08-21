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


def test_camas_de_categorias_distintas_comparten_pallet_sin_orden_fijo():
    """[V4b / fotos de los 42 pallets reales] Ya no hay orden de estabilidad
    por nivel de categoría -confirmado con Omar contra las fotos de los 42
    pallets reales, que mezclan Licores/Lácteos/Comestibles/etc. libremente
    en el mismo pallet. Lo único que importa es que la altura acumulada
    entre dentro del límite."""
    cama_lacteos = Cama(categorias=["Lácteos"], altura_cama=20, cantidades={"L1": 5}, nivel_categoria=2)
    cama_licores = Cama(categorias=["Licores"], altura_cama=20, cantidades={"L0": 5}, nivel_categoria=1)

    camas_por_cd = {"BK31": [cama_lacteos, cama_licores]}
    info_sku = {"L0": _info("L0", "Licores", 1), "L1": _info("L1", "Lácteos", 2)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    categorias = {cama.categorias[0] for cama in pallets[0].camas}
    assert categorias == {"Lácteos", "Licores"}


def test_mezcla_libre_prioriza_camas_mas_pesadas_primero():
    """[V4b] Preferencia suave "peso abajo" (fotos de los 42 pallets reales,
    botellas/Licores tienden a la base): a igual altura de cama, la más
    pesada se procesa primero en `_asignar_camas`, así que tiende a terminar
    más abajo en el pallet que la reciba -no es una regla dura, solo un
    desempate."""
    pesada = Cama(categorias=["Licores"], altura_cama=20, cantidades={"P1": 10}, nivel_categoria=1)
    liviana = Cama(categorias=["Comestibles"], altura_cama=20, cantidades={"L1": 1}, nivel_categoria=None)

    camas_por_cd = {"BK31": [liviana, pesada]}
    info_sku = {
        "P1": {**_info("P1", "Licores", 1), "peso_caja": 20.0},
        "L1": {**_info("L1", "Comestibles", None), "peso_caja": 0.5},
    }

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    assert pallets[0].camas[0].categorias == ["Licores"]


def test_cierre_forzado_bajo_altura_minima_se_marca_parcial():
    cama = Cama(categorias=["Licores"], altura_cama=50, cantidades={"L0": 5}, nivel_categoria=1)
    camas_por_cd = {"BK31": [cama]}
    info_sku = {"L0": _info("L0", "Licores", 1)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    # [Sección 3.2 / v2] el umbral que decide PARCIAL es el tolerado (185, no 190)
    assert pallets[0].altura_final < config.ALTURA_TOTAL_MIN_TOLERADO
    assert config.ESTADO_PALLET_PARCIAL in pallets[0].estado


def test_consolidacion_nunca_mueve_una_cama_hacia_un_pallet_mas_chico():
    # Reproduce el bug real: un pallet ya casi completo (181.7cm, bajo el nuevo
    # umbral tolerado de 185) no debe perder su cama de remate para "ayudar" a un
    # pallet mucho más chico (66.02cm) — eso solo empeora el resultado neto.
    bueno = Pallet(id="A", cd="X", tipo="Mixto", altura_final=181.7)
    bueno.camas = [
        Cama(categorias=["Licores"], altura_cama=161.1, cantidades={"L1": 5}, nivel_categoria=1),
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
