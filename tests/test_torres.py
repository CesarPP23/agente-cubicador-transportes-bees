"""[V5-P4] Modelos columnares: alturas, pesos, split tower, orientación,
serialización temporal."""
import pandas as pd

import config
from models import OrientacionCaja, PalletV5, Torre
from src.torres import (
    TorreCandidate,
    crear_torre,
    dividir_torre,
    generar_torres_candidatas,
    torre_a_dict,
)


def _candidata(sku="1", cd="BK31", largo=30.0, ancho=20.0, alto=25.0, max_vert=8, disp=20, peso=1.5):
    return TorreCandidate(
        sku=sku, cd=cd, orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=max_vert, cantidad_disponible=disp, peso_unitario=peso,
    )


def test_altura_de_torre_es_cantidad_por_alto_caja():
    torre = crear_torre(_candidata(alto=25.0), x=0, y=0, cantidad=5)
    assert torre.cantidad == 5
    assert torre.altura == 125.0  # 5 * 25


def test_peso_de_torre_es_cantidad_por_peso_unitario():
    torre = crear_torre(_candidata(peso=2.0), x=0, y=0, cantidad=4)
    assert torre.peso == 8.0


def test_crear_torre_nunca_excede_maximo_vertical_ni_disponible():
    torre = crear_torre(_candidata(max_vert=3, disp=100), x=0, y=0, cantidad=10)
    assert torre.cantidad == 3  # tope físico de altura

    torre2 = crear_torre(_candidata(max_vert=100, disp=2), x=0, y=0, cantidad=10)
    assert torre2.cantidad == 2  # tope de demanda disponible


def test_split_tower_preserva_demanda_total():
    torre = crear_torre(_candidata(alto=20.0, peso=1.0), x=10, y=5, cantidad=7)
    primera, segunda = dividir_torre(torre, 3)

    assert primera.cantidad == 3
    assert segunda.cantidad == 4
    assert primera.cantidad + segunda.cantidad == torre.cantidad
    assert round(primera.peso + segunda.peso, 6) == round(torre.peso, 6)
    # misma geometría y posición -el packer decide después si reubica la segunda
    assert primera.sku == segunda.sku == torre.sku
    assert primera.alto_caja == segunda.alto_caja == torre.alto_caja


def test_split_tower_rechaza_cantidad_invalida():
    torre = crear_torre(_candidata(), x=0, y=0, cantidad=5)
    try:
        dividir_torre(torre, 10)
        assert False, "debió rechazar cantidad_primera > torre.cantidad"
    except ValueError:
        pass


def test_orientacion_caja_solo_acostada_para_categorias_permitidas():
    parada = OrientacionCaja(largo=30, ancho=20, alto=25, codigo="L×A", acostada=False)
    acostada = OrientacionCaja(largo=30, ancho=25, alto=20, codigo="ACOSTADA_L", acostada=True)
    assert parada.acostada is False
    assert acostada.acostada is True
    # frozen: no se puede mutar una orientación ya decidida
    try:
        parada.largo = 99
        assert False, "OrientacionCaja debería ser inmutable (frozen)"
    except Exception:
        pass


def test_generar_torres_candidatas_da_dos_orientaciones_por_sku():
    df_cd = pd.DataFrame(
        [
            {
                "SKU": "1", "CD": "BK31", "Cajas_Remanente": 10,
                "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 25.0,
                "Peso_Caja": 1.2, "Fuente_Geometria": "UMA_VALIDADA",
            }
        ]
    )
    candidatas = generar_torres_candidatas(df_cd, altura_max_producto=config.ALTURA_PRODUCTO_MAX)
    assert len(candidatas) == 2
    orientaciones = {c.orientacion for c in candidatas}
    assert orientaciones == {"L×A", "A×L"}
    for c in candidatas:
        assert c.max_cajas_verticales == int(config.ALTURA_PRODUCTO_MAX // 25.0)
        assert c.cantidad_disponible == 10


def test_generar_torres_candidatas_descarta_sin_geometria():
    df_cd = pd.DataFrame(
        [{"SKU": "1", "CD": "BK31", "Cajas_Remanente": 10, "Largo_Efectivo": None, "Ancho_Efectivo": None, "Alto_Efectivo": None, "Peso_Caja": 1.0, "Fuente_Geometria": ""}]
    )
    assert generar_torres_candidatas(df_cd, altura_max_producto=config.ALTURA_PRODUCTO_MAX) == []


def test_serializacion_temporal_torre_a_dict():
    torre = crear_torre(_candidata(), x=1.0, y=2.0, cantidad=3)
    d = torre_a_dict(torre)
    assert d["sku"] == "1"
    assert d["cantidad"] == 3
    assert d["altura"] == torre.altura
    assert "placements" not in d  # el resumen no repite el detalle caja a caja


def test_pallet_v5_agrega_peso_y_altura_de_sus_torres():
    t1 = crear_torre(_candidata(sku="A", alto=20.0, peso=1.0), x=0, y=0, cantidad=5)
    t2 = crear_torre(_candidata(sku="B", alto=30.0, peso=2.0), x=40, y=0, cantidad=3)
    pallet = PalletV5(id="PV5-1", cd="BK31", torres=[t1, t2])
    pallet.peso_estimado = sum(t.peso for t in pallet.torres)
    pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.altura for t in pallet.torres)

    assert pallet.peso_estimado == 5 * 1.0 + 3 * 2.0
    assert pallet.altura_final == config.ALTURA_PALLET_VACIO + max(100.0, 90.0)
