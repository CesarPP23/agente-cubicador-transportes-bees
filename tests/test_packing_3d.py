"""[V5-packing3d] El packer columnar puede apilar una SKU distinta ENCIMA
de una torre más corta, en el mismo (x, y) -en vez de dejar el aire sobre
una torre corta inutilizable para siempre, como pasaba con el modelo 2D
puro (auditado con datos reales: 82% ocupación de huella pero solo ~54%
eficiencia volumétrica, ver PATCH_LOG.md)."""
import pandas as pd

import config
from models import Torre
from src.packing_columnar import _area_union_xy, armar_pallets_columnar


def _fila(sku, largo, ancho, alto, cantidad, peso=1.0, cd="BK31"):
    return {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": peso, "Fuente_Geometria": "UMA_VALIDADA",
    }


def test_una_sku_se_apila_encima_de_otra_corta_en_el_mismo_xy():
    """SKU A es corta (llena poco del pallet en altura) y ocupa toda la
    huella disponible; SKU B, más angosta, no debería quedar obligada a
    abrir un pallet nuevo si puede subirse arriba de A en la misma XY."""
    df = pd.DataFrame(
        [
            _fila("A", 120, 100, 20.0, 1),  # 1 caja, ocupa TODA la huella, solo 20cm de alto
            _fila("B", 30, 20, 25.0, 3),  # cabe perfectamente en el aire que deja A
        ]
    )
    pallets = armar_pallets_columnar(df, "BK31")
    assert len(pallets) == 1, "B debería poder subirse arriba de A en vez de abrir un pallet nuevo"
    torres_b = [t for p in pallets for t in p.torres if t.sku == "B"]
    assert any(t.z > 0.01 for t in torres_b), "al menos una torre de B debería estar apilada (z>0), no al piso"


def test_demanda_exacta_se_conserva_con_apilado():
    df = pd.DataFrame(
        [
            _fila("A", 120, 100, 20.0, 1),
            _fila("B", 30, 20, 25.0, 3),
            _fila("C", 40, 40, 15.0, 5),
        ]
    )
    pallets = armar_pallets_columnar(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == {"A": 1, "B": 3, "C": 5}


def test_area_union_xy_no_duplica_huellas_apiladas():
    """Dos torres EXACTAMENTE en el mismo (x, y) -apiladas- ocupan la MISMA
    huella, no el doble. La suma ingenua de area_base sí las duplicaba
    (bug real, encontrado con datos reales: ocupacion_xy > 100%)."""
    base = Torre(
        sku="A", cd="BK31", x=0, y=0, largo=30, ancho=20, alto_caja=25,
        cantidad=1, peso=1.0, orientacion="L×A", fuente_geometria="UMA_VALIDADA", z=0.0,
    )
    arriba = Torre(
        sku="B", cd="BK31", x=0, y=0, largo=30, ancho=20, alto_caja=15,
        cantidad=1, peso=1.0, orientacion="L×A", fuente_geometria="UMA_VALIDADA", z=25.0,
    )
    assert _area_union_xy([base, arriba]) == 30 * 20  # no 2*30*20


def test_area_union_xy_suma_huellas_distintas_sin_solaparse():
    a = Torre(
        sku="A", cd="BK31", x=0, y=0, largo=30, ancho=20, alto_caja=25,
        cantidad=1, peso=1.0, orientacion="L×A", fuente_geometria="UMA_VALIDADA",
    )
    b = Torre(
        sku="B", cd="BK31", x=30, y=0, largo=20, ancho=20, alto_caja=25,
        cantidad=1, peso=1.0, orientacion="L×A", fuente_geometria="UMA_VALIDADA",
    )
    assert _area_union_xy([a, b]) == 30 * 20 + 20 * 20


def test_concentrar_sku_prefiere_seguir_llenando_el_mismo_pallet():
    """[V-AUTO-CONSOLIDADO] Con concentrar_sku=True, si el último pallet
    usado para un SKU todavía tiene lugar, la siguiente porción de ese
    mismo SKU tiene que ir ahí -no a otro pallet aunque el ajuste sea
    matemáticamente mejor en otro lado."""
    df = pd.DataFrame(
        [
            # C ocupa la mayor parte de la huella en un pallet nuevo primero.
            _fila("C", 100, 90, 20.0, 1),
            # A tiene demanda de sobra para varias iteraciones del while.
            _fila("A", 20, 20, 25.0, 8),
        ]
    )
    pallets = armar_pallets_columnar(df, "BK31", concentrar_sku=True)
    torres_a_por_pallet: dict[str, int] = {}
    for p in pallets:
        n = sum(1 for t in p.torres if t.sku == "A")
        if n:
            torres_a_por_pallet[p.id] = n
    # todas las torres de A concentradas en el mínimo de pallets posible
    # para esa cantidad -no dispersas en muchos pallets con 1 torre cada uno.
    assert len(torres_a_por_pallet) <= 2


def test_concentrar_sku_no_pierde_demanda():
    df = pd.DataFrame([_fila("A", 30, 20, 25.0, 37), _fila("B", 25, 25, 20.0, 12)])
    pallets = armar_pallets_columnar(df, "BK31", concentrar_sku=True)
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 12


def test_concentrar_sku_false_no_cambia_el_resultado_default():
    """El parámetro nuevo no debe alterar el comportamiento cuando no se
    pide -mismo resultado que sin pasarlo."""
    df = pd.DataFrame([_fila("A", 120, 100, 20.0, 1), _fila("B", 30, 20, 25.0, 3)])
    con_default = armar_pallets_columnar(df, "BK31")
    con_flag_false = armar_pallets_columnar(df, "BK31", concentrar_sku=False)
    assert len(con_default) == len(con_flag_false)
    assert [t.sku for p in con_default for t in p.torres] == [t.sku for p in con_flag_false for t in p.torres]


def test_ocupacion_xy_nunca_supera_1():
    df = pd.DataFrame(
        [
            _fila("A", 120, 100, 20.0, 1),
            _fila("B", 120, 100, 20.0, 8),  # varias capas completas, misma huella que A
        ]
    )
    pallets = armar_pallets_columnar(df, "BK31")
    assert all(p.ocupacion_xy <= 1.0 + 1e-6 for p in pallets)
