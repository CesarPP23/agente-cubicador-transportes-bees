"""[V5-P5] Packer columnar básico: torres de altura independiente, sin
clustering por altura, altura de pallet <=215, demanda exacta."""
import pandas as pd

import config
from src.packing_columnar import armar_pallets_columnar


def _fila(sku, largo, ancho, alto, cantidad, peso=1.0, cd="BK31"):
    return {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": peso, "Fuente_Geometria": "UMA_VALIDADA",
    }


def test_torres_de_alturas_independientes_en_el_mismo_pallet():
    """Dos SKUs con alto de caja MUY distinto deben poder compartir pallet,
    cada uno con su propia altura de torre -sin agruparse por altura similar
    (eso era el core V4, acá no existe)."""
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 60.0, 3),  # torre de 180cm
            _fila("B", 30, 20, 10.0, 3),  # torre de 30cm, footprint distinto en el pallet
        ]
    )
    # SKU B en otra posición XY para no competir por el mismo rectángulo
    df.loc[1, "Largo_Efectivo"] = 40
    df.loc[1, "Ancho_Efectivo"] = 40

    pallets = armar_pallets_columnar(df, "BK31")
    assert len(pallets) >= 1
    alturas_torre = sorted({t.altura for p in pallets for t in p.torres})
    assert len(alturas_torre) >= 2, "las torres deberían quedar con alturas distintas, no clusterizadas a una sola"


def test_no_hay_clustering_por_altura_como_gate():
    """A diferencia de V4 (TOLERANCIA_ALTURA_PORTANTE agrupaba remanentes por
    altura similar antes de decidir si comparten cama), acá dos SKUs de
    altura de caja muy distinta pueden convivir en el mismo pallet sin pasar
    por ningún filtro de "diferencia de altura tolerada"."""
    df = pd.DataFrame([_fila("A", 20, 20, 15.0, 2), _fila("B", 20, 20, 80.0, 1)])
    pallets = armar_pallets_columnar(df, "BK31")
    total_cajas = sum(t.cantidad for p in pallets for t in p.torres if t.sku in ("A", "B"))
    assert total_cajas == 3  # ambos SKUs entraron, sin que la diferencia de altura bloquee nada


def test_mismo_cd_no_se_mezclan():
    """armar_pallets_columnar recibe un df de UN CD -el CD del pallet
    resultante siempre es el que se pasó como argumento."""
    df = pd.DataFrame([_fila("A", 30, 20, 25.0, 5, cd="BK31")])
    pallets = armar_pallets_columnar(df, "BK31")
    assert all(p.cd == "BK31" for p in pallets)


def test_altura_nunca_supera_215():
    df = pd.DataFrame([_fila("A", 30, 20, 25.0, 50)])  # mucha demanda, fuerza varias torres/pallets
    pallets = armar_pallets_columnar(df, "BK31")
    assert all(p.altura_final <= config.ALTURA_MAX_OBSERVADA + 1e-6 for p in pallets)


def test_demanda_exacta_se_despacha_completa():
    df = pd.DataFrame([_fila("A", 30, 20, 25.0, 37), _fila("B", 25, 25, 20.0, 12)])
    pallets = armar_pallets_columnar(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 12
    # y nada quedó en "sin_colocar"
    assert all("sin_colocar" not in p.metadata for p in pallets)


def test_caja_mas_grande_que_el_pallet_queda_marcada_sin_perder_demanda():
    df = pd.DataFrame([_fila("GIGANTE", 200, 200, 50.0, 3)])
    pallets = armar_pallets_columnar(df, "BK31")
    sin_colocar = {}
    for p in pallets:
        sin_colocar.update(p.metadata.get("sin_colocar", {}))
    assert sin_colocar.get("GIGANTE") == 3  # nunca se descarta en silencio


def test_torre_no_excede_maximo_de_altura_individual():
    df = pd.DataFrame([_fila("A", 30, 20, 25.0, 100)])
    pallets = armar_pallets_columnar(df, "BK31")
    for p in pallets:
        for t in p.torres:
            assert t.altura <= config.ALTURA_PRODUCTO_MAX + 1e-6
