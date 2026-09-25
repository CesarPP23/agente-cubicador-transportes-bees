"""[PATCH V6.12-FASE1D] Edge cases del reorden FIT->HEIGHT->OVERHANG de
`_cuboide_admite_candidato`/`_fit_directo_o_con_tolerancia` -verificados
offline contra el código original (git v6.11-multicd-pass) sobre 500.000
llamadas reales de BK52+BK53 más estos 9 casos (0 diferencias en ambos).
Estos booleanos ya son los esperados -confirmados idénticos al
comportamiento pre-reorden."""
import config
from models import PalletV5
from src.packing_bloques import _cuboide_admite_candidato, _fit_directo_o_con_tolerancia
from src.packing_columnar import _CuboidLibre
from src.torres import TorreCandidate

MARGEN = config.SOBRESALIENTE_MAX_CM
TOLERANCIA = config.TOLERANCIA_OVERHANG_CM


def _cand(sku="A", largo=40, ancho=30, alto=20, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _pallet_vacio():
    return PalletV5(id="EDGE", cd="CD")


def test_overhang_justo_en_el_limite_admite():
    c = _CuboidLibre(x=-MARGEN, y=0, z=0, w=50, h=50, d=30)
    assert _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_overhang_levemente_excedido_rechaza():
    c = _CuboidLibre(x=-MARGEN - 1, y=0, z=0, w=50, h=50, d=30)
    assert not _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_altura_exacta_al_limite_admite():
    c = _CuboidLibre(x=0, y=0, z=0, w=50, h=50, d=20)
    assert _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_altura_levemente_excedida_rechaza():
    c = _CuboidLibre(x=0, y=0, z=0, w=50, h=50, d=19)
    assert not _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_fit_exacto_directo_admite():
    c = _CuboidLibre(x=0, y=0, z=0, w=40, h=30, d=30)
    assert _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_fit_solo_via_tolerancia_admite():
    c = _CuboidLibre(x=0, y=0, z=0, w=40 - TOLERANCIA / 2, h=30, d=30)
    assert _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_fit_fuera_incluso_con_tolerancia_rechaza():
    c = _CuboidLibre(x=0, y=0, z=0, w=40 - TOLERANCIA - 5, h=30, d=30)
    assert not _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_falla_overhang_y_altura_simultaneamente_rechaza():
    c = _CuboidLibre(x=-MARGEN - 5, y=0, z=0, w=50, h=50, d=10)
    assert not _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_falla_los_tres_checks_simultaneamente_rechaza():
    c = _CuboidLibre(x=-MARGEN - 5, y=0, z=0, w=5, h=5, d=10)
    assert not _cuboide_admite_candidato(_pallet_vacio(), c, _cand(), None, 6, {"A": 6})


def test_fit_directo_o_con_tolerancia_reordenada_mismos_resultados():
    """`_fit_directo_o_con_tolerancia` también quedó reordenada (FIT->
    HEIGHT->OVERHANG) -mismos 9 casos, ahora contra la función standalone
    (la usan tests directos, ver test_packing_bloques.py/test_reglas_
    bk31.py)."""
    pallet = _pallet_vacio()
    casos = [
        (_CuboidLibre(x=-MARGEN, y=0, z=0, w=50, h=50, d=30), True),
        (_CuboidLibre(x=-MARGEN - 1, y=0, z=0, w=50, h=50, d=30), False),
        (_CuboidLibre(x=0, y=0, z=0, w=50, h=50, d=20), True),
        (_CuboidLibre(x=0, y=0, z=0, w=50, h=50, d=19), False),
        (_CuboidLibre(x=0, y=0, z=0, w=40, h=30, d=30), True),
        (_CuboidLibre(x=0, y=0, z=0, w=40 - TOLERANCIA / 2, h=30, d=30), True),
        (_CuboidLibre(x=0, y=0, z=0, w=40 - TOLERANCIA - 5, h=30, d=30), False),
        (_CuboidLibre(x=-MARGEN - 5, y=0, z=0, w=50, h=50, d=10), False),
        (_CuboidLibre(x=-MARGEN - 5, y=0, z=0, w=5, h=5, d=10), False),
    ]
    for c, esperado in casos:
        assert _fit_directo_o_con_tolerancia(pallet, c, _cand()) == esperado
