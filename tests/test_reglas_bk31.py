"""Límites operativos confirmados a partir del armado manual de BK31."""
import pytest

import config
from models import PalletV5
from src.packing_bloques import _candidatos_lote, _fit_directo_o_con_tolerancia
from src.packing_columnar import _CuboidLibre, _PalletEnConstruccion, _altura_presupuesto
from src.torres import TorreCandidate, crear_torre
from src.validacion import _cabe_en_pallet
from src.validacion_v5 import validar_pallet_v5


def _cand(sku="CAJA", largo=25.7, ancho=26, alto=17):
    return TorreCandidate(sku, "BK31", "L×A", largo, ancho, alto, 10, 10, 1.0)


def _pallet(torres):
    return PalletV5(id="BK31", cd="BK31", torres=torres,
                    altura_final=config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in torres))


@pytest.mark.parametrize("altura,admitido", [(216.42, True), (220, True), (220.01, False)])
def test_altura_total_incluye_parihuela(altura, admitido):
    cand = _cand(alto=altura - config.ALTURA_PALLET_VACIO)
    pc = _PalletEnConstruccion(PalletV5(id="BK31", cd="BK31"))
    assert (_fit_directo_o_con_tolerancia(pc.pallet, pc.libres[0], cand)) == admitido
    torre = crear_torre(cand, x=0, y=0, cantidad=1)
    assert (validar_pallet_v5(_pallet([torre])) == []) == admitido
    assert _altura_presupuesto() == pytest.approx(205.08)


@pytest.mark.parametrize("x,y,admitido", [
    (-2, 0, True), (0, -2, True), (102, 0, True), (0, 82, True),
    (-2.01, 0, False), (0, -2.01, False), (102.01, 0, False), (0, 82.01, False),
])
def test_margen_exterior_por_cada_lado(x, y, admitido):
    torre = crear_torre(_cand(largo=20, ancho=20), x=x, y=y, cantidad=1)
    assert (validar_pallet_v5(_pallet([torre])) == []) == admitido


def test_envelope_efectivo_124x104():
    """PATCH V6.01, sección 6, Test 1: 120x100 + 2cm/lado -> 124x104."""
    assert config.PALLET_LARGO_EFECTIVO == 124.0
    assert config.PALLET_ANCHO_EFECTIVO == 104.0


def test_4cm_concentrados_en_un_lado_es_invalido_aunque_quepa_en_el_envelope_global():
    """PATCH V6.01, sección 6, Test 5: una caja de 120cm (=PALLET_LARGO) NO
    puede arrancar en x=-4 -viola el margen de 2cm del lado izquierdo, aunque
    su borde derecho (x=116) quede muy dentro del envelope global de 124
    (chequeo INCORRECTO que este patch reemplaza: `x + largo <= 124`, que
    aceptaría esto sin problema)."""
    torre = crear_torre(_cand(largo=120, ancho=20), x=-4, y=0, cantidad=1)
    assert torre.x + torre.largo <= config.PALLET_LARGO_EFECTIVO  # el chequeo viejo lo habría aceptado
    assert validar_pallet_v5(_pallet([torre])) != []  # el chequeo por lado lo rechaza


def test_armado_usa_margen_simetrico_completo():
    cand = _cand(largo=124, ancho=104)
    assert _cabe_en_pallet(124, 104)
    assert not _cabe_en_pallet(124.01, 104)
    pc = _PalletEnConstruccion(PalletV5(id="BK31", cd="BK31"))
    assert _fit_directo_o_con_tolerancia(pc.pallet, pc.libres[0], cand)
    torre = pc.colocar(cand, 1, 0)
    assert (torre.x, torre.y) == (-2, -2)
    assert validar_pallet_v5(pc.pallet) == []


@pytest.mark.parametrize("x,y,largo,ancho,admitido", [
    (0, 0, 25.7, 26, True),  # Altomayo sobre Vino de 24 cm.
    (-2, -2, 28, 35, True),  # 2 cm simultáneamente en los cuatro bordes.
    (-2.01, 0, 26, 26, False), (0, -2.01, 24, 33, False),
    (0, 0, 26.01, 26, False), (0, 0, 24, 33.01, False),
])
def test_sobresaliente_sobre_apoyo_por_lado(x, y, largo, ancho, admitido):
    base = crear_torre(_cand("VINO", 24, 31, 30.5), x=20, y=20, cantidad=1)
    arriba = crear_torre(_cand(largo=largo, ancho=ancho), x=20+x, y=20+y, z=30.5, cantidad=1)
    assert (validar_pallet_v5(_pallet([base, arriba])) == []) == admitido


def test_margen_no_tapa_un_hueco_interior_ni_acepta_flotacion():
    izquierda = crear_torre(_cand("A", 10, 30, 20), x=0, y=0, cantidad=1)
    derecha = crear_torre(_cand("B", 10, 30, 20), x=11, y=0, cantidad=1)
    arriba = crear_torre(_cand("C", 21, 30, 20), x=0, y=0, z=20, cantidad=1)
    assert any("caja flotando" in v for v in validar_pallet_v5(_pallet([izquierda, derecha, arriba])))
    assert any("caja flotando" in v for v in validar_pallet_v5(_pallet([arriba])))


def test_lote_con_sobresaliente_se_detiene_antes_del_obstaculo_superior():
    base = crear_torre(_cand("BASE", 24, 31, 20), x=0, y=0, cantidad=1)
    lateral = crear_torre(_cand("LATERAL", 10, 26, 20), x=24, y=0, z=40, cantidad=1)
    pallet = _pallet([base, lateral])
    pc = _PalletEnConstruccion(pallet, [_CuboidLibre(0, 0, 20, 24, 31, 100)])
    cand = _cand(alto=17)
    opciones = _candidatos_lote([pc], [{}], {"CAJA": 5}, {"CAJA": [cand]}, {}, {}, {}, 205.08, 1)
    assert opciones
    assert all(op[-1] == 1 for op in opciones)  # una caja cabe; dos chocarían a Z=40.
