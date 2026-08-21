"""[V5-P2] No sustituir una medición física por footprint artificial si el
dato operacional (Maestro) puede explicarse con el sobresaliente de negocio
validado (2.5cm/lado). Ver DOCUMENTACION_LOGICA_V5.md sección 5.3."""
import pandas as pd

from src.reconciliacion_geometrica import capacidad_xy_max, capacidad_xy_max_con_sobresaliente, reconciliar_sku


def _row(sku="1", largo=41.0, ancho=30.0, alto=25.0, cajas_por_cama=9, categoria="Licores"):
    return pd.Series(
        {
            "SKU": sku,
            "Largo de caja": largo,
            "Ancho de caja": ancho,
            "Alto de caja": alto,
            "Cajas por cama": cajas_por_cama,
            "Categoria_Normalizada": categoria,
        }
    )


def test_uma_estricta_insuficiente_sobresaliente_suficiente_da_nuevo_estado():
    # 41x30cm: estricto (120x100) entran 8; con sobresaliente (125x105) entran 10.
    cap_estricta, _ = capacidad_xy_max(41.0, 30.0)
    cap_sobresaliente, _ = capacidad_xy_max_con_sobresaliente(41.0, 30.0)
    assert cap_estricta == 8
    assert cap_sobresaliente == 10

    g = reconciliar_sku(_row(largo=41.0, ancho=30.0, cajas_por_cama=9))  # 8 < 9 <= 10

    assert g.fuente_geometria == "UMA_VALIDADA_CON_SOBRESALIENTE"
    assert g.requiere_revision is False


def test_geometria_medida_permanece_trazable_sin_fabricar_footprint():
    """Con UMA_VALIDADA_CON_SOBRESALIENTE, largo/ancho efectivos son
    EXACTAMENTE los medidos -no un footprint inventado por
    inferir_footprint_desde_cajas_cama."""
    g = reconciliar_sku(_row(largo=41.0, ancho=30.0, cajas_por_cama=9))
    assert g.fuente_geometria == "UMA_VALIDADA_CON_SOBRESALIENTE"
    assert g.largo_efectivo == 41.0
    assert g.ancho_efectivo == 30.0
    # y la medición original queda igual de trazable en largo_uma/ancho_uma
    assert g.largo_uma == 41.0
    assert g.ancho_uma == 30.0


def test_alto_nunca_cambia_salvo_categoria_de_rotacion_libre():
    # Licores: NO está en CATEGORIAS_ROTACION_LIBRE -alto siempre el medido.
    g_licor = reconciliar_sku(_row(categoria="Licores", alto=25.0, cajas_por_cama=None))
    assert g_licor.alto_efectivo == 25.0
    assert g_licor.acostada is False

    # Comestibles SÍ puede acostarse si eso entra más -acá alto puede cambiar.
    # Caja 40x30x24.7 (ver PARCHES_V4.md): acostada gana bastante.
    g_comestible = reconciliar_sku(
        pd.Series(
            {
                "SKU": "2",
                "Largo de caja": 41.6,
                "Ancho de caja": 31.3,
                "Alto de caja": 24.7,
                "Cajas por cama": None,
                "Categoria_Normalizada": "Comestibles",
            }
        )
    )
    # Sin techo del Maestro, se usa la orientación de mayor capacidad -en
    # este SKU real, acostada gana (ver PARCHES_V4.md).
    assert g_comestible.acostada is True
    assert g_comestible.alto_efectivo != 24.7


def test_maestro_imposible_sigue_degradando_cuando_ni_sobresaliente_alcanza():
    """SKU 22183 real: declara 84 cajas/cama, geometría (35x24) da 15 incluso
    con sobresaliente -sigue degradando, no queda colgado en un estado nuevo."""
    g = reconciliar_sku(_row(largo=35.0, ancho=24.0, alto=28.0, cajas_por_cama=84))
    assert g.fuente_geometria == "MAESTRO_IMPOSIBLE_DEGRADADO"
    assert g.cajas_cama_maestro < 84
