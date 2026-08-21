"""[V5-P3] El solver de capacidad y el de layout ya no pueden divergir: si
`capacidad = N`, tienen que existir N placements reales, sin solape, sin
salirse del pallet, y de forma determinística."""
import random

from src.layout_solver import resolver_layout_rectangulos


def _sin_solapes(placements) -> bool:
    for i, (x1, y1, w1, d1, _o1) in enumerate(placements):
        for x2, y2, w2, d2, _o2 in placements[i + 1 :]:
            if x1 + w1 <= x2 + 1e-6 or x2 + w2 <= x1 + 1e-6 or y1 + d1 <= y2 + 1e-6 or y2 + d2 <= y1 + 1e-6:
                continue
            return False
    return True


def _dentro_del_pallet(placements, W, H) -> bool:
    return all(x >= -1e-6 and y >= -1e-6 and x + w <= W + 1e-6 and y + d <= H + 1e-6 for x, y, w, d, _o in placements)


def test_mixto_40x30_en_120x100_da_10_placements_validos():
    r = resolver_layout_rectangulos(120, 100, 40, 30)
    assert r.capacidad == 10
    assert len(r.placements) == 10
    assert _sin_solapes(r.placements)
    assert _dentro_del_pallet(r.placements, 120, 100)


def test_capacidad_siempre_igual_a_cantidad_de_placements():
    casos = [(120, 100, 30, 20), (120, 100, 35, 25), (120, 100, 60, 50), (120, 100, 452, 452)]
    for pl, pa, cl, ca in casos:
        r = resolver_layout_rectangulos(pl, pa, cl, ca)
        assert r.capacidad == len(r.placements), f"caja {cl}x{ca}: capacidad={r.capacidad} pero {len(r.placements)} placements"


def test_random_500_casos_sin_solape_ni_desborde():
    rng = random.Random(42)
    for _ in range(500):
        largo = round(rng.uniform(5, 60), 1)
        ancho = round(rng.uniform(5, 60), 1)
        r = resolver_layout_rectangulos(120, 100, largo, ancho, con_pinwheel=False)  # sin pinwheel: 500 casos rápido
        assert r.capacidad == len(r.placements)
        assert _sin_solapes(r.placements), f"solape con caja {largo}x{ancho}"
        assert _dentro_del_pallet(r.placements, 120, 100), f"desborde con caja {largo}x{ancho}"


def test_determinismo():
    r1 = resolver_layout_rectangulos(120, 100, 35, 25)
    r2 = resolver_layout_rectangulos(120, 100, 35, 25)
    assert r1.capacidad == r2.capacidad
    assert r1.placements == r2.placements
    assert r1.metodo == r2.metodo


def test_no_cabe_ni_una_caja():
    r = resolver_layout_rectangulos(120, 100, 452, 452)
    assert r.capacidad == 0
    assert r.placements == []


def test_sin_rotacion_respeta_una_sola_orientacion():
    r = resolver_layout_rectangulos(120, 100, 40, 30, permitir_rotacion_xy=False)
    assert all(o == "L×A" for *_xywd, o in r.placements)
    assert r.capacidad == 9  # 120//40=3 * 100//30=3
