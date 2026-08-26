"""[V5-P11] Estabilidad informativa: calcula KPIs, nunca bloquea."""
import config
from models import PalletV5
from src.estabilidad import ESTADO_OK, ESTADO_WARN_COG, ESTADO_WARN_TORRE_ESBELTA, calcular_estabilidad
from src.torres import TorreCandidate, crear_torre


def _torre(sku, x, y, largo=20.0, ancho=20.0, alto=20.0, cantidad=1, peso=1.0):
    cand = TorreCandidate(
        sku=sku, cd="BK31", orientacion="L×A", largo=largo, ancho=ancho, alto_caja=alto,
        max_cajas_verticales=cantidad, cantidad_disponible=cantidad, peso_unitario=peso,
    )
    return crear_torre(cand, x=x, y=y, cantidad=cantidad)


def test_pallet_centrado_y_parejo_da_ok():
    # 4 torres iguales, una en cada esquina -> centro de masa en el centro geométrico.
    torres = [
        _torre("A", 0, 0, peso=1.0),
        _torre("B", 100, 0, peso=1.0),
        _torre("C", 0, 80, peso=1.0),
        _torre("D", 100, 80, peso=1.0),
    ]
    pallet = PalletV5(id="P1", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 20)
    est = calcular_estabilidad(pallet)
    assert est.estados == [ESTADO_OK]
    assert est.ok is True
    assert abs(est.centro_masa_x - config.PALLET_LARGO / 2) < 5
    assert abs(est.centro_masa_y - config.PALLET_ANCHO / 2) < 5


def test_peso_concentrado_en_una_esquina_da_warn_cog():
    torres = [_torre("A", 0, 0, peso=100.0), _torre("B", 100, 80, peso=0.1)]
    pallet = PalletV5(id="P2", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 20)
    est = calcular_estabilidad(pallet)
    assert ESTADO_WARN_COG in est.estados
    assert est.ok is False


def test_torre_esbelta_se_detecta():
    torre_esbelta = _torre("A", 0, 0, largo=10, ancho=10, alto=25, cantidad=6)  # 150cm de alto, base 10x10
    pallet = PalletV5(id="P3", cd="BK31", torres=[torre_esbelta], altura_final=config.ALTURA_PALLET_VACIO + torre_esbelta.altura)
    est = calcular_estabilidad(pallet)
    assert ESTADO_WARN_TORRE_ESBELTA in est.estados
    assert len(est.torres_esbeltas) == 1


def test_peso_por_cuadrante_suma_el_peso_total():
    torres = [_torre("A", 0, 0, peso=2.0), _torre("B", 100, 80, peso=3.0)]
    pallet = PalletV5(id="P4", cd="BK31", torres=torres, altura_final=config.ALTURA_PALLET_VACIO + 20)
    est = calcular_estabilidad(pallet)
    assert round(sum(est.peso_por_cuadrante.values()), 6) == 5.0


def test_nunca_bloquea_solo_informa():
    """Un pallet con TODAS las alertas activadas sigue siendo un
    EstabilidadPallet normal -no levanta excepción, no impide nada."""
    torre_mala = _torre("A", 0, 0, largo=5, ancho=5, alto=25, cantidad=8, peso=1000.0)
    pallet = PalletV5(id="P5", cd="BK31", torres=[torre_mala], altura_final=config.ALTURA_PALLET_VACIO + torre_mala.altura)
    est = calcular_estabilidad(pallet)  # no debe reventar
    assert isinstance(est.estados, list)
    assert len(est.estados) >= 1


def test_pallet_sin_torres_da_ok_por_defecto():
    pallet = PalletV5(id="P6", cd="BK31", torres=[], altura_final=config.ALTURA_PALLET_VACIO)
    est = calcular_estabilidad(pallet)
    assert est.estados == [ESTADO_OK]


def test_peso_apilado_arriba_pesa_mas_que_el_mismo_peso_al_piso():
    """[packing3d] Dos pallets con el mismo peso total y la misma torre
    "pesada", pero en uno esa torre está apilada bien arriba (z alto) y en
    el otro al piso (z=0) -el de arriba tiene que dar una fracción de peso
    superior MAYOR. Si el cálculo ignorara `t.z` (bug real, encontrado al
    habilitar el apilado), ambos darían exactamente igual."""
    from src.torres import TorreCandidate as TC

    liviana_al_piso = _torre("liviana", 0, 0, largo=100, ancho=80, alto=10, peso=0.1)

    pesada_al_piso = crear_torre(
        TC(sku="pesada", cd="BK31", orientacion="L×A", largo=20, ancho=20, alto_caja=20,
           max_cajas_verticales=1, cantidad_disponible=1, peso_unitario=100.0),
        x=0, y=80, cantidad=1, z=0.0,
    )
    pallet_abajo = PalletV5(
        id="PA", cd="BK31", torres=[liviana_al_piso, pesada_al_piso],
        altura_final=config.ALTURA_PALLET_VACIO + 20,
    )

    pesada_arriba = crear_torre(
        TC(sku="pesada", cd="BK31", orientacion="L×A", largo=20, ancho=20, alto_caja=20,
           max_cajas_verticales=1, cantidad_disponible=1, peso_unitario=100.0),
        x=0, y=80, cantidad=1, z=180.0,
    )
    pallet_arriba = PalletV5(
        id="PB", cd="BK31", torres=[liviana_al_piso, pesada_arriba],
        altura_final=config.ALTURA_PALLET_VACIO + 200,
    )

    est_abajo = calcular_estabilidad(pallet_abajo)
    est_arriba = calcular_estabilidad(pallet_arriba)
    assert est_arriba.fraccion_peso_superior > est_abajo.fraccion_peso_superior
