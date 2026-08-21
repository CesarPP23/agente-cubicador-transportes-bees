"""[V5-P14] Validación geométrica dura: overlap y overflow sobre PalletV5
ya armados -auditoría independiente del algoritmo de packing."""
import config
from models import PalletV5
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_geometria_v5, validar_pallet_v5


def _torre(sku, x, y, largo=30.0, ancho=20.0, alto=25.0, cantidad=1):
    cand = TorreCandidate(
        sku=sku, cd="BK31", orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=cantidad, cantidad_disponible=cantidad, peso_unitario=1.0,
    )
    return crear_torre(cand, x=x, y=y, cantidad=cantidad)


def test_pallet_valido_sin_violaciones():
    torres = [_torre("A", 0, 0), _torre("B", 30, 0)]
    pallet = PalletV5(id="P1", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 25)
    assert validar_pallet_v5(pallet) == []


def test_torres_pegadas_lado_a_lado_no_es_overlap():
    # B empieza exactamente donde termina A (30) -tocarse en el borde es válido.
    torres = [_torre("A", 0, 0, largo=30), _torre("B", 30, 0, largo=30)]
    pallet = PalletV5(id="P2", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 25)
    assert validar_pallet_v5(pallet) == []


def test_detecta_overlap_entre_torres():
    torres = [_torre("A", 0, 0, largo=30, ancho=30), _torre("B", 10, 10, largo=30, ancho=30)]
    pallet = PalletV5(id="P3", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 25)
    violaciones = validar_pallet_v5(pallet)
    assert len(violaciones) == 1
    assert "se superpone" in violaciones[0]


def test_apilar_dos_torres_distintas_en_el_mismo_xy_no_es_overlap():
    """[packing3d] Una torre corta con otra SKU apilada justo encima -mismo
    (x, y), rangos de Z que no se cruzan- es el caso que el packing 3D
    existe para habilitar, no una violación."""
    torre_base = _torre("A", 0, 0, alto=25, cantidad=2)  # z: 0-50
    cand_arriba = TorreCandidate(
        sku="B", cd="BK31", orientacion="L×A", largo=30.0, ancho=20.0, alto_caja=20.0,
        max_cajas_verticales=3, cantidad_disponible=3, peso_unitario=1.0,
    )
    torre_arriba = crear_torre(cand_arriba, x=0, y=0, cantidad=3, z=torre_base.altura)  # z: 50-110
    pallet = PalletV5(id="P8", cd="BK31", torres=[torre_base, torre_arriba], altura_final=config.ALTURA_PALLET_VACIO + 110)
    assert validar_pallet_v5(pallet) == []


def test_detecta_overlap_vertical_si_los_rangos_de_z_se_cruzan():
    """Mismo XY, pero la segunda torre empieza ANTES de que termine la
    primera -eso sí es una superposición real (dos cajas en el mismo punto
    del espacio)."""
    torre_base = _torre("A", 0, 0, alto=25, cantidad=2)  # z: 0-50
    cand_arriba = TorreCandidate(
        sku="B", cd="BK31", orientacion="L×A", largo=30.0, ancho=20.0, alto_caja=20.0,
        max_cajas_verticales=3, cantidad_disponible=3, peso_unitario=1.0,
    )
    torre_arriba = crear_torre(cand_arriba, x=0, y=0, cantidad=3, z=30.0)  # z: 30-90, se cruza con 0-50
    pallet = PalletV5(id="P9", cd="BK31", torres=[torre_base, torre_arriba], altura_final=config.ALTURA_PALLET_VACIO + 90)
    violaciones = validar_pallet_v5(pallet)
    assert len(violaciones) == 1
    assert "se superpone" in violaciones[0]


def test_detecta_overflow_fuera_de_la_base():
    torre = _torre("A", 100, 0, largo=30, ancho=20)  # 100+30=130 > 120
    pallet = PalletV5(id="P4", cd="BK31", torres=[torre], altura_final=config.ALTURA_PALLET_VACIO + 25)
    violaciones = validar_pallet_v5(pallet)
    assert len(violaciones) == 1
    assert "se sale de la base" in violaciones[0]


def test_detecta_altura_sobre_el_tope_duro():
    torre = _torre("A", 0, 0, alto=300, cantidad=1)
    pallet = PalletV5(id="P5", cd="BK31", torres=[torre], altura_final=config.ALTURA_TOPE_DURO + 50)
    violaciones = validar_pallet_v5(pallet)
    assert any("tope duro" in v for v in violaciones)


def test_validar_geometria_v5_une_violaciones_de_varios_pallets():
    torre_mala = _torre("A", 100, 0, largo=30, ancho=20)
    p1 = PalletV5(id="P6", cd="BK31", torres=[torre_mala], altura_final=config.ALTURA_PALLET_VACIO + 25)
    p2 = PalletV5(id="P7", cd="BK31", torres=[_torre("B", 0, 0)], altura_final=config.ALTURA_PALLET_VACIO + 25)
    violaciones = validar_geometria_v5([p1, p2])
    assert len(violaciones) == 1
    assert violaciones[0].startswith("P6:")
