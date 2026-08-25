"""[PH_FRACCION] Motor aproximado por fracción de PH -pedido explícito del
usuario tras comparar contra un cubicaje real armado a mano (`Plan de
acción 25.08- CUBICADO.xlsx`, ver PATCH_LOG.md sección "PH_FRACCION").
Estos tests verifican las garantías que SÍ se mantienen en este modo
(demanda exacta, no-solape, no pasarse de altura, orden de categoría,
cobertura mínima por capa) -no la posición exacta de cada caja, que acá
es deliberadamente una aproximación."""
import pandas as pd

import config
from src.packing_ph_fraccion import armar_pallets_ph_fraccion, validar_capas_ph_fraccion
from src.validacion_v5 import validar_geometria_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_por_ph=None, cd="BK31", nivel=None):
    fila = {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }
    if cajas_por_ph is not None:
        fila["Cajas por PH"] = cajas_por_ph
    if nivel is not None:
        fila["Nivel_Categoria"] = nivel
    return fila


def _sin_solape_ni_overflow_ni_altura(pallets):
    viol = validar_geometria_v5(pallets)
    return [v for v in viol if "se superpone" in v or "se sale" in v or "supera el tope" in v]


def test_no_pierde_ni_duplica_demanda():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 20.0, 37, cajas_por_ph=120),
            _fila("B", 25, 25, 18.0, 60, cajas_por_ph=90),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 60


def test_nunca_solapa_ni_excede_altura_ni_se_sale_de_la_base():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 20.0, 200, cajas_por_ph=100),
            _fila("B", 45, 32, 24.0, 150, cajas_por_ph=60),
            _fila("C", 20, 18, 15.0, 300, cajas_por_ph=200),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    assert _sin_solape_ni_overflow_ni_altura(pallets) == []
    for p in pallets:
        assert p.altura_final <= config.ALTURA_MAX_OBSERVADA + 1e-6


def test_ninguna_capa_no_maxima_queda_por_debajo_del_umbral_minimo():
    """[garantía "nada flota" a nivel de capa] Con muchos SKUs de tamaños
    variados compitiendo, ninguna capa que tenga otra capa apoyada encima
    debe quedar por debajo de UMBRAL_COBERTURA_CAPA_MINIMO -la capa más
    alta de cada pallet no tiene esa restricción (nada se apoya en ella)."""
    df = pd.DataFrame(
        [
            _fila("A", 40, 30, 25.0, 20, cajas_por_ph=40, nivel=1),
            _fila("B", 25, 20, 20.0, 15, cajas_por_ph=60, nivel=1),
            _fila("C", 33, 28, 22.0, 10, cajas_por_ph=30, nivel=6),
            _fila("D", 20, 15, 18.0, 25, cajas_por_ph=80, nivel=6),
            _fila("E", 50, 35, 27.0, 8, cajas_por_ph=15, nivel=7),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    assert validar_capas_ph_fraccion(pallets) == []


def test_licores_nunca_encima_de_nabs_por_columna_de_capa():
    """El piso de nivel del pallet solo sube -si una capa usó NABs (nivel
    6), ninguna capa siguiente puede volver a nivel 1 (Licores)."""
    df = pd.DataFrame(
        [
            _fila("LICOR", 30, 20, 20.0, 40, cajas_por_ph=80, nivel=1),
            _fila("NABS", 30, 20, 20.0, 40, cajas_por_ph=80, nivel=6),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    for p in pallets:
        capas_por_z: dict[float, set] = {}
        for t in p.torres:
            capas_por_z.setdefault(round(t.z, 3), set()).add(t.sku)
        zs_licor = [z for z, skus in capas_por_z.items() if "LICOR" in skus]
        zs_nabs = [z for z, skus in capas_por_z.items() if "NABS" in skus]
        if zs_licor and zs_nabs:
            assert max(zs_licor) <= min(zs_nabs), "LICOR quedó en una capa más alta que NABS en el mismo pallet"


def test_objetivo_de_ph_se_refleja_en_menos_pallets_que_capacidad_1x():
    """[el hallazgo central de esta sección] Con SKUs cuya demanda
    combinada es ~1.3 PH cada una (varias SKUs, ninguna sola llena un
    pallet), el resultado debe consolidar en MENOS pallets que "1 PH por
    pallet" -si cada SKU abriera su propio pallet dedicado, serían muchos
    más que los ~2 que corresponden a la fracción de PH real combinada."""
    df = pd.DataFrame(
        [
            _fila("A", 25, 20, 20.0, 60, cajas_por_ph=100, nivel=1),   # 0.6 PH
            _fila("B", 22, 18, 18.0, 50, cajas_por_ph=100, nivel=2),   # 0.5 PH
            _fila("C", 28, 24, 22.0, 55, cajas_por_ph=100, nivel=6),   # 0.55 PH
            _fila("D", 20, 20, 16.0, 45, cajas_por_ph=100, nivel=7),   # 0.45 PH
        ]
    )
    # total = 2.1 PH -debería consolidar en 2 pallets, no 4 (uno por SKU)
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    assert len(pallets) <= 3, f"se esperaba consolidación real, salieron {len(pallets)} pallets"
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == {"A": 60, "B": 50, "C": 55, "D": 45}


def test_sin_cajas_por_ph_igual_arma_sin_perder_demanda():
    """Sin la columna 'Cajas por PH' (no debería pasar en el pipeline
    real), el packer no debe romperse ni perder demanda -simplemente esas
    SKUs no aportan al objetivo de PH, se colocan igual por geometría."""
    df = pd.DataFrame([{
        "SKU": "SIN_PH", "CD": "BK31", "Cajas_Remanente": 12,
        "Largo_Efectivo": 20, "Ancho_Efectivo": 20, "Alto_Efectivo": 20.0,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }])
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres)
    assert despachado == 12


def test_ningun_sku_supera_cajas_por_ph_en_un_solo_pallet():
    """[bug real, reportado por el usuario con captura del Excel: SKU
    22443 (Cielo Agua de Mesa 1L) con 98 cajas en UN pallet, cuando el
    Maestro dice `Cajas por PH`=75 -el máximo físico validado para ese SKU
    solo en un pallet, sea homogéneo o mezclado con otros] Con demanda
    mucho mayor a `Cajas por PH`, ningún pallet debe superar ese tope para
    ese SKU -el remanente tiene que repartirse en otro(s) pallet(s), sin
    perder demanda."""
    df = pd.DataFrame([_fila("22443", 32.5, 24, 27.0, 302, cajas_por_ph=75, nivel=6)])
    pallets = armar_pallets_ph_fraccion(df, "BK36")
    for p in pallets:
        cant = sum(t.cantidad for t in p.torres if t.sku == "22443")
        assert cant <= 75, f"{p.id} tiene {cant} cajas de 22443, supera Cajas por PH=75"
    despachado = sum(t.cantidad for p in pallets for t in p.torres)
    assert despachado == 302


def test_objetivo_ph_es_piso_no_techo():
    """[bug real, encontrado corriendo la app con datos reales -BK51: un
    pallet cerraba a 145cm con ph_acumulado=0.43, muy lejos de llegar al
    "techo"] Con un SKU de fracción de PH muy alta (poca huella, mucha
    demanda por caja de PH) que por sí solo ya supera el objetivo de 1.4,
    el pallet NO debe cerrarse ahí si sigue habiendo altura libre y
    demanda compatible pendiente -1.4 es lo que un armador real logra en
    PROMEDIO, no un techo que corte el armado apenas se alcanza."""
    df = pd.DataFrame(
        [
            _fila("DENSO", 20, 20, 15.0, 20, cajas_por_ph=10, nivel=1),  # ph=2.0 él solo
            _fila("COMPATIBLE", 22, 18, 15.0, 40, cajas_por_ph=1000, nivel=1),  # ph≈0, misma altura
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    # si el objetivo de PH fuera un techo, COMPATIBLE apenas entraría
    # (DENSO solo ya llega a 2.0 PH); acá debe entrar la demanda completa
    # porque sigue habiendo piso/altura libre para combinarla.
    assert despachado.get("COMPATIBLE", 0) == 40
    assert despachado.get("DENSO", 0) == 20


def test_sku_alto_sin_companero_no_corta_el_pallet_completo():
    """[bug real, encontrado corriendo la app con datos reales -caso BAT:
    52.5x34x49cm, mucho más alto que cualquier otro SKU del CD] Cuando un
    SKU es el ÚNICO candidato posible para su capa (nada más tiene una
    altura compatible), su cobertura baja no es una mala elección del
    algoritmo -es escasez real. No debe cortar el resto del pallet: la
    demanda de OTRAS alturas, compatible en nivel, debe poder seguir
    apilándose en camas propias por encima."""
    df = pd.DataFrame(
        [
            _fila("ALTO_SOLO", 50, 35, 49.0, 2, cajas_por_ph=10, nivel=7),
            _fila("NORMAL1", 30, 20, 20.0, 30, cajas_por_ph=60, nivel=7),
            _fila("NORMAL2", 28, 22, 18.0, 30, cajas_por_ph=60, nivel=7),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == {"ALTO_SOLO": 2, "NORMAL1": 30, "NORMAL2": 30}
    # el pallet que contiene ALTO_SOLO debe seguir teniendo altura útil
    # apilada arriba de esa capa -no debe quedar cortado justo ahí.
    pallet_con_alto = next(p for p in pallets if any(t.sku == "ALTO_SOLO" for t in p.torres))
    assert pallet_con_alto.altura_final > config.ALTURA_PALLET_VACIO + 49.0 + 10
    assert validar_capas_ph_fraccion(pallets) == []


def test_sku_geometricamente_imposible_no_bloquea_el_resto():
    df = pd.DataFrame(
        [
            _fila("IMPOSIBLE", 500, 500, 20.0, 5, cajas_por_ph=10),
            _fila("NORMAL", 30, 20, 20.0, 10, cajas_por_ph=50),
        ]
    )
    pallets = armar_pallets_ph_fraccion(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "NORMAL")
    assert despachado == 10
    sin_colocar = {}
    for p in pallets:
        sin_colocar.update(p.metadata.get("sin_colocar", {}))
    assert sin_colocar.get("IMPOSIBLE") == 5
