"""[SKU_BLOQUE, camas] El pallet se arma CAMA POR CAMA (piso por piso), no
por columnas verticales de un solo SKU -corrección explícita del usuario:
"nunca pero nunca se empieza haciendo columnas, siempre primero se van
llenando las filas de abajo hacia arriba".

[bug real corregido, reporte con foto del Inspector: "hay cajas que estan
flotandoen el vacio, toda caja debe esta puesta sobre otra caja"] La
versión anterior de este archivo reseteaba el espacio libre en cada
frontera de "cama" asumiendo 100% de soporte a esa altura -acá se prueba
que el motor nuevo (un solo `_PalletEnConstruccion` continuo por pallet,
más bajo primero) nunca produce esa violación, vía `validar_geometria_v5`
(que ahora incluye el chequeo anti-flotación)."""
import pandas as pd

from src.packing_bloques import armar_pallets_bloques
from src.validacion_v5 import validar_geometria_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_cama=None, cd="BK31", nivel=None):
    fila = {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }
    if cajas_cama is not None:
        fila["Cajas_Cama_Efectivo"] = cajas_cama
    if nivel is not None:
        fila["Nivel_Categoria"] = nivel
    return fila


def _torres_por_z(pallets):
    """Agrupa todas las torres de todos los pallets por (id_pallet, z
    redondeado) -cada grupo es UNA cama."""
    grupos: dict[tuple, list] = {}
    for p in pallets:
        for t in p.torres:
            grupos.setdefault((p.id, round(t.z, 3)), []).append(t)
    return grupos


def test_ejemplo_del_usuario_100_cajas_capacidad_150_un_solo_pallet():
    """100 cajas de una SKU cuya capacidad de cama es 150 -las 100 quedan
    en UN SOLO PALLET, en la MISMA cama (mismo z), no repartidas."""
    df = pd.DataFrame([_fila("KR_NEGRA", 30, 20, 20.0, 100, cajas_cama=150)])
    pallets = armar_pallets_bloques(df, "BK31")
    pallets_con_kr = {p.id for p in pallets if any(t.sku == "KR_NEGRA" for t in p.torres)}
    assert len(pallets_con_kr) == 1
    total = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "KR_NEGRA")
    assert total == 100


def test_arma_fila_por_fila_no_columnas():
    """El SKU ancla, dentro de UNA cama, tiene que quedar todo al mismo z
    (una fila horizontal), nunca apilado en una sola columna de piso a
    techo -eso era el bug del modelo anterior (torres)."""
    df = pd.DataFrame([_fila("A", 20, 20, 25.0, 8, cajas_cama=8)])
    pallets = armar_pallets_bloques(df, "BK31")
    torres_a = [t for p in pallets for t in p.torres if t.sku == "A"]
    zs = {round(t.z, 3) for t in torres_a}
    assert zs == {0.0}, f"todas las torres de A deberían estar en la MISMA cama (z=0), no repartidas en columnas: {zs}"


def test_otro_sku_de_altura_compatible_comparte_la_cama():
    """Un SKU chico de altura parecida a la del ancla debe compartir la
    MISMA cama (mismo z) en vez de esperar a otro pallet. El ancla necesita
    MÁS demanda pendiente que el secundario para ser elegida como ancla de
    la primera cama (criterio de selección: mayor demanda pendiente)."""
    df = pd.DataFrame(
        [
            _fila("ANCLA", 100, 90, 20.0, 5, cajas_cama=1),  # más demanda -> ancla de la 1ra cama
            _fila("CHICO", 15, 8, 18.0, 3, cajas_cama=50),  # altura parecida (18 vs 20), debería compartir cama
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    grupos = _torres_por_z(pallets)
    camas_con_ambos = [g for g in grupos.values() if {t.sku for t in g} == {"ANCLA", "CHICO"}]
    assert camas_con_ambos, "ANCLA y CHICO deberían terminar en la misma cama (misma z)"


def test_sku_muy_mas_bajo_comparte_capa_pero_queda_totalmente_soportado():
    """Un SKU mucho más bajo que el ancla puede terminar en la MISMA capa
    baja (z=0, al lado del ancla, ambos apoyados directo en el piso del
    pallet) -eso ya no es un problema: cada uno tiene su propio soporte
    real, ninguno queda flotando. `validar_geometria_v5` es el juez final
    (incluye el chequeo anti-flotación)."""
    df = pd.DataFrame(
        [
            _fila("ALTO", 100, 90, 100.0, 5, cajas_cama=1),
            _fila("BAJITO", 15, 8, 20.0, 3, cajas_cama=50),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert validar_geometria_v5(pallets) == []


def test_ninguna_torre_queda_flotando_con_skus_de_alturas_mixtas():
    """[invariante central del reporte del usuario] Con varios SKUs de
    alturas bien distintas compitiendo por espacio, ninguna torre debe
    terminar sin soporte real completo debajo -escenario que en la versión
    anterior (reset de espacio libre por cama) producía cajas flotando."""
    df = pd.DataFrame(
        [
            _fila("A", 40, 30, 25.0, 6, cajas_cama=10),
            _fila("B", 25, 20, 20.0, 8, cajas_cama=30),
            _fila("C", 15, 15, 22.0, 20, cajas_cama=60),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert validar_geometria_v5(pallets) == []


def test_no_pierde_demanda():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 25.0, 37, cajas_cama=8),
            _fila("B", 25, 25, 20.0, 12, cajas_cama=10),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado: dict[str, int] = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 12


def test_demanda_grande_ocupa_varias_camas_del_mismo_pallet():
    """Demanda mucho mayor a lo que entra en una cama -tiene que apilar
    VARIAS camas del mismo SKU (una arriba de la otra), no perder nada."""
    df = pd.DataFrame([_fila("GRANDE", 30, 20, 20.0, 370, cajas_cama=150)])
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "GRANDE")
    assert despachado == 370


def test_licores_nunca_queda_arriba_de_nabs():
    """NABs (nivel 6) nunca puede quedar en una cama de altura MENOR (más
    abajo) que una cama de Licores (nivel 1) del mismo pallet -aunque NABs
    tenga más demanda pendiente, que antes hubiera ganado el ancla de la
    primera cama por peso puro."""
    df = pd.DataFrame(
        [
            _fila("NABS", 30, 20, 20.0, 100, cajas_cama=30, nivel=6),  # mucha demanda, ganaría por peso puro
            _fila("LICOR", 30, 20, 20.0, 20, cajas_cama=30, nivel=1),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    torres_por_cama = _torres_por_z(pallets)

    for (pallet_id, z), torres in torres_por_cama.items():
        skus_en_cama = {t.sku for t in torres}
        if "NABS" in skus_en_cama:
            # cualquier cama de LICOR en el MISMO pallet tiene que estar a
            # una z MENOR (más abajo) que esta cama de NABS.
            for (otro_pallet, otro_z), otras_torres in torres_por_cama.items():
                if otro_pallet != pallet_id:
                    continue
                if any(t.sku == "LICOR" for t in otras_torres):
                    assert otro_z < z, "LICOR quedó en una cama igual o más alta que NABS en el mismo pallet"


def test_licores_si_puede_quedar_debajo_de_nabs():
    df = pd.DataFrame(
        [
            _fila("LICOR", 30, 20, 20.0, 20, cajas_cama=30, nivel=1),
            _fila("NABS", 30, 20, 20.0, 20, cajas_cama=30, nivel=6),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    torres_por_cama = _torres_por_z(pallets)
    zs_licor = [z for (_pid, z), torres in torres_por_cama.items() if any(t.sku == "LICOR" for t in torres)]
    zs_nabs = [z for (_pid, z), torres in torres_por_cama.items() if any(t.sku == "NABS" for t in torres)]
    assert zs_licor and zs_nabs
    assert max(zs_licor) < min(zs_nabs)


def test_four_loko_queda_arriba_de_todo_por_nivel_remate():
    """[Four Loko] Se identifica por Nivel_Categoria ya resuelto a
    NIVEL_REMATE (config.NIVEL_REMATE) -acá se prueba el efecto en el
    packer, no la detección por texto (eso es derivados.py). Con nivel de
    remate, ninguna otra SKU puede quedar en una cama más alta -Four Loko
    siempre es la última."""
    import config

    df = pd.DataFrame(
        [
            _fila("FOURLOKO", 20, 20, 20.0, 5, cajas_cama=20, nivel=config.NIVEL_REMATE),
            _fila("LICOR", 30, 20, 20.0, 20, cajas_cama=30, nivel=1),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    torres_por_cama = _torres_por_z(pallets)
    for (pallet_id, z), torres in torres_por_cama.items():
        if any(t.sku == "LICOR" for t in torres):
            for (otro_pallet, otro_z), otras_torres in torres_por_cama.items():
                if otro_pallet != pallet_id:
                    continue
                if any(t.sku == "FOURLOKO" for t in otras_torres):
                    assert z < otro_z, "algo quedó en la misma cama o más alto que Four Loko"


def test_categorias_pueden_compartir_la_misma_capa_si_la_geometria_lo_permite():
    """[relajación pedida por el usuario tras el fix de flotación] La regla
    real es por columna física ("no se le puede encimar licores sobre
    nabs"), no "una categoría entera antes que la siguiente". Con NABS de
    huella 100x30 (deja tiras de 20cm sin usar en los 120 de largo) y
    REMATE de huella chica (15x15, cabe en esas tiras), REMATE debe poder
    colocarse en la MISMA capa Z que NABS -sin esperar a que NABS agote
    toda su demanda primero- y sin violar el orden de categoría."""
    df = pd.DataFrame(
        [
            _fila("NABS", 100, 30, 20.0, 15, cajas_cama=30, nivel=6),
            _fila("REMATE", 15, 15, 20.0, 8, cajas_cama=30, nivel=7),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    torres_por_cama = _torres_por_z(pallets)
    capas_mixtas = [g for g in torres_por_cama.values() if {t.sku for t in g} == {"NABS", "REMATE"}]
    assert capas_mixtas, "REMATE debería poder compartir capa con NABS cuando la huella lo permite"
    assert validar_geometria_v5(pallets) == []
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == {"NABS": 15, "REMATE": 8}


def test_sin_columna_nivel_categoria_no_cambia_nada():
    """Sin la columna Nivel_Categoria (compatibilidad con datasets viejos o
    tests que no la setean), todo el mundo cae en el mismo nivel por
    default -no debería cambiar ningún resultado existente."""
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 25.0, 37, cajas_cama=20),
            _fila("B", 25, 25, 20.0, 12, cajas_cama=50),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 12


def test_consolidacion_de_remanentes_nunca_pierde_ni_duplica_demanda():
    """[sección 5, consolidación de remanentes] Con muchos SKUs de baja
    demanda repartidos en varios niveles de categoría (el patrón real que
    produce pallets cortos), la consolidación puede o no reducir el número
    de pallets -pero bajo ninguna circunstancia debe perder o duplicar
    demanda, ni introducir una violación geométrica nueva."""
    df = pd.DataFrame(
        [
            _fila("N1", 20, 20, 20.0, 3, cajas_cama=30, nivel=1),
            _fila("N2A", 25, 20, 22.0, 4, cajas_cama=20, nivel=2),
            _fila("N2B", 30, 25, 18.0, 5, cajas_cama=15, nivel=2),
            _fila("N3", 20, 20, 25.0, 2, cajas_cama=30, nivel=3),
            _fila("N6A", 32, 20, 25.0, 6, cajas_cama=18, nivel=6),
            _fila("N6B", 40, 30, 22.0, 3, cajas_cama=8, nivel=6),
            _fila("N7A", 44, 32, 27.0, 2, cajas_cama=6, nivel=7),
            _fila("N7B", 39, 39, 20.0, 4, cajas_cama=9, nivel=7),
        ]
    )
    esperado = {"N1": 3, "N2A": 4, "N2B": 5, "N3": 2, "N6A": 6, "N6B": 3, "N7A": 2, "N7B": 4}
    pallets = armar_pallets_bloques(df, "BK31")
    despachado: dict[str, int] = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == esperado
    assert validar_geometria_v5(pallets) == []


def test_no_viola_geometria():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 25.0, 37, cajas_cama=8),
            _fila("B", 25, 25, 20.0, 12, cajas_cama=10),
            _fila("C", 40, 30, 15.0, 200, cajas_cama=12),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert validar_geometria_v5(pallets) == []


def test_sin_cajas_cama_efectivo_igual_arma_algo():
    """Sin la columna Cajas_Cama_Efectivo (no debería pasar en el pipeline
    real, pero por si acaso) el packer no debe perder demanda -usa toda la
    huella disponible como tope."""
    df = pd.DataFrame(
        [
            {
                "SKU": "SIN_CAMA", "CD": "BK31", "Cajas_Remanente": 8,
                "Largo_Efectivo": 20, "Ancho_Efectivo": 20, "Alto_Efectivo": 20.0,
                "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
            }
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "SIN_CAMA")
    assert despachado == 8
