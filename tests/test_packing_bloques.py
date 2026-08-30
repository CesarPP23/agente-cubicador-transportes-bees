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

import config
from models import PalletV5, Torre
from src.packing_bloques import (
    _capacidad_instalada,
    _empacar_n_pallets,
    _empacar_n_pallets_greedy,
    _mejor_cuboide_para_sku,
    _necesita_columna_nueva,
    _restaurar_estado_pallets,
    _snapshot_estado_pallets,
    armar_pallets_bloques,
)
from src.packing_columnar import _PalletEnConstruccion
from src.torres import generar_torres_candidatas
from src.validacion_v5 import validar_geometria_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_cama=None, cd="BK31", nivel=None, categoria=None, cajas_por_ph=None):
    fila = {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }
    if cajas_cama is not None:
        fila["Cajas_Cama_Efectivo"] = cajas_cama
    if nivel is not None:
        fila["Nivel_Categoria"] = nivel
    if categoria is not None:
        fila["Categoria_Normalizada"] = categoria
    if cajas_por_ph is not None:
        fila["Cajas por PH"] = cajas_por_ph
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


def _apoyado_directo(pallets, sku_arriba, sku_abajo) -> bool:
    """[segunda reescritura de bandas] Busca, en cualquier pallet, alguna
    torre de `sku_arriba` cuya base quede exactamente sobre el tope de una
    torre de `sku_abajo` con huella solapada -mismo criterio de soporte
    real que usa `_soporte_viola_nivel`. Sirve para verificar la jerarquía
    de peso desde afuera del packer, sin asumir ninguna estructura de
    "cama" ni de "banda"."""
    for p in pallets:
        for t in p.torres:
            if t.sku != sku_arriba:
                continue
            for o in p.torres:
                if o.sku != sku_abajo:
                    continue
                if abs((o.z + o.altura) - t.z) > 1e-6:
                    continue
                if o.x + o.largo <= t.x + 1e-6 or t.x + t.largo <= o.x + 1e-6:
                    continue
                if o.y + o.ancho <= t.y + 1e-6 or t.y + t.ancho <= o.y + 1e-6:
                    continue
                return True
    return False


def test_licores_nunca_queda_arriba_de_nabs():
    """[segunda reescritura de bandas -pedido explícito: "nunca puede ir
    una caja de licor encima de otra categoria porque pesa mucho"] Aunque
    NABs tenga mucha más demanda pendiente (que antes hubiera ganado el
    ancla de la primera cama por peso/huella puro), ninguna torre de
    LICOR puede terminar apoyada DIRECTAMENTE sobre una torre de NABS."""
    df = pd.DataFrame(
        [
            _fila(
                "NABS", 30, 20, 20.0, 100, cajas_cama=30, categoria="NABs",
                nivel=config.nivel_de_categoria("NABs"),
            ),  # mucha demanda
            _fila(
                "LICOR", 30, 20, 20.0, 20, cajas_cama=30, categoria="Licores",
                nivel=config.nivel_de_categoria("Licores"),
            ),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert not _apoyado_directo(pallets, sku_arriba="LICOR", sku_abajo="NABS")


def test_licores_si_puede_quedar_debajo_de_nabs():
    """[pedido explícito: "si puede ir 1 caja de nabs o de importados sobre
    licor"] Con demanda pareja, NABs SÍ debe poder terminar apoyado
    directamente sobre Licores en algún caso -no hace falta exclusividad
    de cama para lograrlo, alcanza con que el chequeo de soporte lo
    permita en esa dirección."""
    df = pd.DataFrame(
        [
            _fila(
                "LICOR", 30, 20, 20.0, 20, cajas_cama=30, categoria="Licores",
                nivel=config.nivel_de_categoria("Licores"),
            ),
            _fila(
                "NABS", 30, 20, 20.0, 20, cajas_cama=30, categoria="NABs",
                nivel=config.nivel_de_categoria("NABs"),
            ),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert _apoyado_directo(pallets, sku_arriba="NABS", sku_abajo="LICOR")
    assert not _apoyado_directo(pallets, sku_arriba="LICOR", sku_abajo="NABS")


def test_licores_lacteos_nabs_pueden_compartir_piso_del_pallet():
    """[segunda reescritura de bandas -pedido explícito tras revisar el
    cubicaje real: distintas categorías SÍ comparten pallet, incluso la
    misma Z, sin agotar una entera antes de tocar la siguiente] Con poca
    demanda de cada una (mucho menos que su propia `Cajas por cama`), las
    3 categorías deben poder coexistir en el mismo pallet, en el piso
    (z=0) -la jerarquía de peso solo restringe QUÉ puede quedar apoyado
    sobre QUÉ, no impide que compartan la base."""
    df = pd.DataFrame(
        [
            _fila(
                "NABS", 30, 20, 20.0, 2, cajas_cama=30, categoria="NABs",
                nivel=config.nivel_de_categoria("NABs"),
            ),
            _fila(
                "LACTEO", 30, 20, 20.0, 2, cajas_cama=30, categoria="Lácteos",
                nivel=config.nivel_de_categoria("Lácteos"),
            ),
            _fila(
                "LICOR", 30, 20, 20.0, 2, cajas_cama=30, categoria="Licores",
                nivel=config.nivel_de_categoria("Licores"),
            ),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert len(pallets) == 1
    torres_en_piso = {t.sku for t in pallets[0].torres if t.z <= 1e-6}
    assert torres_en_piso == {"LICOR", "LACTEO", "NABS"}, (
        f"se esperaba que las 3 categorías compartieran el piso del pallet, quedó: {torres_en_piso}"
    )


def test_four_loko_queda_en_banda_remanente_no_en_licores():
    """[Four Loko, reescritura de bandas -pedido explícito: "ya no es
    obligatorio que sea lo más alto"] Se identifica por Nivel_Categoria ya
    resuelto a NIVEL_REMATE (config.NIVEL_REMATE) por derivados.py -acá se
    prueba el efecto en el packer, no la detección por texto. Aunque su
    Categoria_Normalizada diga "Licores", Four Loko cae en la banda
    remanente (4), NO en la banda 1 (Licores regulares) -por construcción
    de bandas estrictamente secuenciales, eso alcanza para que quede
    siempre por encima de Licores de verdad en el mismo pallet, sin
    necesitar ninguna regla "Cigarros/remate siempre lo más alto"."""
    import config

    df = pd.DataFrame(
        [
            _fila("FOURLOKO", 20, 20, 20.0, 5, cajas_cama=20, categoria="Licores", nivel=config.NIVEL_REMATE),
            _fila("LICOR", 30, 20, 20.0, 20, cajas_cama=30, categoria="Licores", nivel=1),
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


def test_huella_grande_gana_el_empate_de_z_sobre_mas_demanda():
    """[bug real, encontrado con datos reales del usuario -Plan_Picking_
    Optimizado (11).xlsx, CD BK31 pallets 003+004: 76.4cm + 112.9cm,
    sumados ~189cm, pero en pallets SEPARADOS, mismo nivel de categoría
    (7, Comestibles) los dos] El usuario preguntó directamente por qué no
    estaban juntos si sumados entraban. Causa real: el desempate de "cuál
    SKU gana el mismo Z" priorizaba más demanda pendiente -eso hacía que
    SKUs chicas de mucha demanda acapararan el piso PRIMERO mientras
    estaba abierto, dejando a las SKUs grandes (BAT, huella 52.5x34; otras
    de ~40x30-47) sin ningún bolsillo grande donde entrar más tarde.
    Reproducido acá con las mismas huellas/demandas reales: SKUS chicas de
    mucha demanda (30x30, demanda 4) compitiendo con SKUs grandes de poca
    demanda (45x35, demanda 2) -las grandes deben conseguir lugar (huella
    gana el empate), no quedar sin colocar."""
    df = pd.DataFrame(
        [
            _fila("CHICA1", 30, 30, 18.0, 4, cajas_cama=12, nivel=7),
            _fila("CHICA2", 30, 30, 18.0, 4, cajas_cama=12, nivel=7),
            _fila("CHICA3", 27, 30, 16.0, 4, cajas_cama=10, nivel=7),
            _fila("GRANDE1", 45, 35, 24.0, 2, cajas_cama=5, nivel=7),
            _fila("GRANDE2", 42, 32, 23.5, 2, cajas_cama=8, nivel=7),
            _fila("GRANDE3", 52.5, 34, 49.0, 2, cajas_cama=6, nivel=7),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado == {"CHICA1": 4, "CHICA2": 4, "CHICA3": 4, "GRANDE1": 2, "GRANDE2": 2, "GRANDE3": 2}
    assert validar_geometria_v5(pallets) == []
    # todo esto debería entrar en un solo pallet, no repartirse en varios
    # cortos -es el escenario real del usuario.
    assert len(pallets) == 1, f"se esperaba 1 pallet, salieron {len(pallets)}: {[round(p.altura_final) for p in pallets]}"


def test_orientacion_cae_a_la_rotada_si_la_preferida_no_entra_en_nada():
    """[bug real, encontrado con datos reales del usuario -Plan_Picking_
    Optimizado (10).xlsx, CD BK31: 5 pallets, ninguno pasaba los 170cm]
    Cada SKU prueba TODAS sus orientaciones disponibles en cada intento de
    colocación y usa la que le da la mejor Z (ver sección 6 del docstring
    del módulo) -así que una vez que el piso se fragmenta, si la
    orientación "preferida" (mejor grilla en un pallet vacío) no entra en
    ningún hueco que quede pero la rotada sí, se usa la rotada. Acá se
    fuerza ese escenario: GRANDE ocupa casi toda la altura del pallet
    dejando solo una tira lateral angosta (20cm) -B (30x12) en su
    orientación preferida (30cm de largo) no entra en la tira, pero rotada
    (12cm de largo) sí. Antes de este fix, B se quedaba sin colocar en este
    pallet aunque hubiera lugar real; ahora debe cambiarse a la rotada."""
    from src.packing_columnar import _altura_presupuesto

    presupuesto = _altura_presupuesto()
    df = pd.DataFrame(
        [
            _fila("GRANDE", 100, 100, presupuesto - 5, 1, cajas_cama=1),
            _fila("B", 30, 12, 20.0, 2, cajas_cama=30),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("B", 0) == 2, "B debería entrar rotado en la tira lateral, no quedar sin colocar"
    assert validar_geometria_v5(pallets) == []


def test_orientacion_por_intento_cierra_columna_de_altura_pareja():
    """[caso real reportado por el usuario con foto: "columnas" de altura
    despareja, aire visible sobre la columna más corta] A (huella 45x100)
    tiene poca demanda -su columna se agota rápido, dejando un tramo de
    piso de 45cm de ancho libre desde su tope hacia arriba. B tiene mucha
    demanda: su orientación "preferida" (55x18, mejor grilla en un pallet
    vacío) no entra en esa tira de 45cm (55 > 45), pero su otra
    orientación "de pie" (18x55) sí. Antes de este fix, la orientación de
    B quedaba fija en la preferida para todo el pallet -mientras siguiera
    encontrando dónde ir en SU PROPIA columna (75cm de ancho), nunca se
    comparaba contra la rotada, así que el tramo que dejó A libre se
    quedaba vacío aunque B tuviera de sobra demanda y la rotada calzara
    ahí. Ahora cada intento de B compara ambas orientaciones y usa la que
    da la Z más baja -por lo tanto, una vez que la columna de A queda más
    baja que seguir subiendo en la propia columna de B, alguna torre de B
    debe aparecer usando la rotada (18 de largo) exactamente sobre la
    columna de A (x=0), no solo en su propia columna."""
    df = pd.DataFrame(
        [
            _fila("A", 45, 100, 30.0, 2, cajas_cama=1, categoria="Licores"),
            _fila("B", 55, 18, 18.0, 25, cajas_cama=5, categoria="Licores"),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert validar_geometria_v5(pallets) == []
    torres_b_sobre_a = [
        t for p in pallets for t in p.torres
        if t.sku == "B" and t.x < 45 - 1e-6 and t.z >= 60 - 1e-6 and t.largo < 55
    ]
    assert torres_b_sobre_a, "B debería rellenar, con su orientación rotada, el tramo que A dejó libre"


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


# --- orientación flexible (Comestibles/Aseo/Cigarros) + tope real de
# Cajas por PH -pedido explícito del usuario tras ver fotos de camas
# flotando en el motor aproximado PH_FRACCION, que se retiró; este motor
# exacto (0% de flotación) es el que quedó conectado al pipeline de
# nuevo, con estos 2 agregados -----------------------------------------

def _dataset_con_hueco_real(categoria_relleno="Aseo"):
    """GRANDE (footprint 35x100) deja siempre una tira de 15cm de ancho
    (120 - 3*35) sin usar -ninguna de las 2 orientaciones "de pie" de
    RELLENO entra ahí (25x20 o 20x25, ambas > 15cm de largo), pero
    acostada sí (10x25, usando el Alto_Efectivo de 20 como una de las
    dimensiones del piso)."""
    return pd.DataFrame(
        [
            _fila("GRANDE", 35, 100, 20.0, 300, cajas_cama=3, nivel=1, categoria="Licores"),
            _fila(
                "RELLENO", 25, 20, 10.0, 40, cajas_cama=200,
                nivel=config.nivel_de_categoria(categoria_relleno),
                categoria=categoria_relleno,
            ),
        ]
    )


def test_categoria_flexible_entra_acostada_donde_de_pie_no_calza():
    df = _dataset_con_hueco_real("Aseo")
    pallets = armar_pallets_bloques(df, "BK31")
    torres_relleno = [t for p in pallets for t in p.torres if t.sku == "RELLENO"]
    assert torres_relleno, "RELLENO debería entrar en la tira que GRANDE deja libre"
    assert any("acostado" in t.orientacion for t in torres_relleno), (
        "RELLENO solo entra en la tira angosta acostado -ninguna orientación de pie calza"
    )
    assert validar_geometria_v5(pallets) == [], "el motor exacto debe seguir en 0% de flotación con orientación flexible"


def test_nabs_nunca_se_coloca_acostado():
    """[pedido explícito del usuario] "nabs es el unico que siempre tiene
    que ir de pie" -aunque acostado calzara mejor en un hueco angosto,
    NABs no tiene esa opción disponible."""
    df = _dataset_con_hueco_real("NABs")
    pallets = armar_pallets_bloques(df, "BK31")
    torres_relleno = [t for p in pallets for t in p.torres if t.sku == "RELLENO"]
    for t in torres_relleno:
        assert "acostado" not in t.orientacion, f"NABs (RELLENO) quedó acostado: {t.orientacion}"


def test_categoria_no_flexible_no_se_acuesta():
    """Licores (u otra categoría fuera de Comestibles/Aseo/Cigarros) no
    tiene orientaciones "acostado" disponibles en absoluto."""
    df = _dataset_con_hueco_real("Licores")
    pallets = armar_pallets_bloques(df, "BK31")
    torres_relleno = [t for p in pallets for t in p.torres if t.sku == "RELLENO"]
    for t in torres_relleno:
        assert "acostado" not in t.orientacion


def test_ningun_sku_supera_cajas_por_ph_en_un_solo_pallet():
    """[bug real, reportado por el usuario con captura del Excel: SKU
    22443 con 98 cajas en UN pallet, cuando el Maestro dice `Cajas por
    PH`=75] Con demanda mucho mayor a `Cajas por PH`, ningún pallet debe
    superar ese tope para ese SKU."""
    df = pd.DataFrame([_fila("22443", 32.5, 24, 27.0, 302, cajas_cama=15, cajas_por_ph=75, nivel=6)])
    pallets = armar_pallets_bloques(df, "BK36")
    for p in pallets:
        cant = sum(t.cantidad for t in p.torres if t.sku == "22443")
        assert cant <= 75, f"{p.id} tiene {cant} cajas de 22443, supera Cajas por PH=75"
    despachado = sum(t.cantidad for p in pallets for t in p.torres)
    assert despachado == 302


def _torre_test(sku, x, y, z, alto_caja, cantidad):
    return Torre(
        sku=sku, cd="BK31", x=x, y=y, largo=30, ancho=20, alto_caja=alto_caja,
        cantidad=cantidad, peso=0.0, orientacion="L×A", fuente_geometria="TEST", z=z,
    )


def test_capacidad_instalada_suma_el_resto_de_todas_las_columnas():
    """[combinación por fila, caso real Pallet 1 CD Callao] `_capacidad_
    instalada` debe sumar, sobre TODAS las columnas ya existentes de un
    SKU, cuánto más cabe verticalmente en CADA una antes del presupuesto
    de altura -no solo mirar la más alta ni una sola columna."""
    presupuesto = 200.0
    pallet = PalletV5(
        id="P1", cd="BK31",
        torres=[_torre_test("A", 0, 0, 0, 20, 3), _torre_test("A", 30, 0, 0, 20, 5)],
    )
    # columna en (0,0): tope=60 -> resto floor((200-60)/20)=7
    # columna en (30,0): tope=100 -> resto floor((200-100)/20)=5
    assert _capacidad_instalada(pallet, "A", presupuesto) == 12
    assert _capacidad_instalada(pallet, "B", presupuesto) == 0  # sin columnas propias


def test_necesita_columna_nueva_cede_solo_cuando_hay_capacidad_de_sobra():
    """[combinación por fila] Un SKU con una columna que ya tiene sitio de
    sobra (capacidad instalada >= demanda pendiente) NO necesita una celda
    NUEVA -pero SÍ sigue necesitando si su demanda pendiente supera esa
    capacidad, y una celda que ya es SU PROPIA columna nunca cuenta como
    "nueva" (eso lo decide el llamador aparte, ver `_empacar`)."""
    presupuesto = 200.0
    pallet = PalletV5(id="P1", cd="BK31", torres=[_torre_test("A", 0, 0, 0, 20, 3)])  # capacidad restante: 7
    assert _necesita_columna_nueva(pallet, "A", 5, 1, 30, 0, 0.0, presupuesto) is False  # 5 <= 7
    assert _necesita_columna_nueva(pallet, "A", 20, 1, 30, 0, 0.0, presupuesto) is True  # 20 > 7
    # celda que ya es propia (0,0): nunca es "nueva", sin importar la demanda
    assert _necesita_columna_nueva(pallet, "A", 20, 1, 0, 0, 60.0, presupuesto) is False
    # sin ninguna columna propia todavía: SIEMPRE necesita (no hay capacidad instalada)
    vacio = PalletV5(id="P2", cd="BK31", torres=[])
    assert _necesita_columna_nueva(vacio, "A", 5, 1, 0, 0, 0.0, presupuesto) is True


def test_necesita_columna_nueva_excepcion_remate_en_el_piso():
    """[excepción de remate, ver test_four_loko_queda_en_banda_remanente_
    no_en_licores] Una categoría de remate (Four Loko/Cigarros incluidos)
    nunca "necesita" -a los efectos de desplazar al ganador normal- una
    celda en el PISO del pallet (z=0), sin importar su demanda -ese piso
    sigue siendo dominio exclusivo de Licores reales. Por encima del piso
    (z>0) sí puede necesitarla, como cualquier otra categoría."""
    presupuesto = 200.0
    vacio = PalletV5(id="P1", cd="BK31", torres=[])
    assert _necesita_columna_nueva(vacio, "FOURLOKO", 20, config.NIVEL_REMATE, 0, 0, 0.0, presupuesto) is False
    assert _necesita_columna_nueva(vacio, "FOURLOKO", 20, config.NIVEL_REMATE, 0, 0, 25.0, presupuesto) is True


# [solver real de N pallets fijos -pedido explícito del usuario: "encaremos
# el diseño más grande pero solo usemos como base el pallet 1... si
# logramos replicar ese pallet a la perfección lo demás va a salir"] A
# diferencia de `_empacar` (voraz, sin poder deshacer una mala decisión),
# `_empacar_n_pallets` corre además un backtracking real con undo -ver
# comentario extenso en `packing_bloques.py` justo antes de
# `COMBINACION_PALLETS_SHORTLIST_K`. Verificado contra el caso real
# (Pallet 1, CD Callao, 21 SKUs, 93 cajas): sube de 67 a 78 cajas
# colocadas (Electrolight, el SKU más golpeado, pasa de 18 a 25 -completo),
# sin ninguna violación geométrica y sin mover el dataset de referencia de
# 9 CDs (`_empacar_n_pallets` no tiene ningún llamador en el pipeline real,
# confirmado con `grep -rn "pallets_objetivo"` -cero riesgo de regresión
# ahí). Estos tests no dependen del Excel real del usuario (no está en el
# repo) -reproducen el patrón (Licor con mucha demanda vs. SKU de footprint
# chico y mucha demanda) a escala sintética.
def _armar_estado_dos_skus(licor_demanda: int, chica_demanda: int):
    """Escenario sintético que reproduce el patrón real de Pallet 1: un
    Licor de footprint grande (29x20.5, igual que "Ron Flor de Caña" real)
    compitiendo por piso contra un SKU de footprint chico (26x19, igual
    que "Electrolight" real) y mucha demanda. A demanda suficientemente
    alta (92/25) el greedy deja al SKU chico muy corto (12/25) aunque el
    Licor ya tenga toda SU demanda cubierta -mismo patrón, escala chica."""
    df = pd.DataFrame(
        [
            _fila("LICOR", 29, 20.5, 30.0, licor_demanda, cajas_cama=16, nivel=1, categoria="Licores"),
            _fila("CHICA", 26, 19, 19.0, chica_demanda, cajas_cama=20, nivel=6, categoria="NABs"),
        ]
    )
    candidatas = generar_torres_candidatas(df, config.ALTURA_PRODUCTO_MAX)
    por_sku: dict = {}
    for c in candidatas:
        por_sku.setdefault(c.sku, []).append(c)
    pendientes = {"LICOR": licor_demanda, "CHICA": chica_demanda}
    capacidad_cama_por_sku = {"LICOR": 16, "CHICA": 20}
    nivel_por_sku = {"LICOR": 1, "CHICA": 6}
    return df, por_sku, pendientes, capacidad_cama_por_sku, nivel_por_sku


def test_n_pallets_backtracking_nunca_peor_que_el_greedy():
    """[garantía central del solver] `_empacar_n_pallets` (backtracking
    real) nunca puede colocar MENOS cajas que `_empacar_n_pallets_greedy`
    -su primera rama explorada en cada nodo reproduce exactamente la misma
    prioridad `(z, nivel, -área, -pendiente)` del greedy, así que el
    incumbente inicial ya iguala el resultado de siempre; de ahí en más
    solo puede empatar o mejorar."""
    _, por_sku, pendientes, capacidad_cama_por_sku, nivel_por_sku = _armar_estado_dos_skus(92, 25)

    pallets_greedy, _ = _empacar_n_pallets_greedy(
        dict(pendientes), por_sku, capacidad_cama_por_sku, nivel_por_sku, {}, "BK31", [0], 1
    )
    total_greedy = sum(t.cantidad for p in pallets_greedy for t in p.torres)

    pallets_nuevo, _ = _empacar_n_pallets(
        dict(pendientes), por_sku, capacidad_cama_por_sku, nivel_por_sku, {}, "BK31", [0], 1
    )
    total_nuevo = sum(t.cantidad for p in pallets_nuevo for t in p.torres)

    assert total_nuevo >= total_greedy
    assert validar_geometria_v5(pallets_nuevo) == []


def test_pallets_objetivo_respeta_cantidad_exacta_y_reporta_sin_colocar():
    """[contrato de pallets_objetivo, sin tests previos que lo cubrieran -
    verificado con grep antes de este cambio] `armar_pallets_bloques(df,
    cd, pallets_objetivo=N)` siempre devuelve exactamente N pallets -ni
    más ni menos- y cualquier demanda que no entró queda reportada en
    `metadata["sin_colocar"]` del último pallet, nunca se pierde en
    silencio (ni de más: total despachado + sin_colocar == demanda total)."""
    df, *_ = _armar_estado_dos_skus(92, 25)
    pallets = armar_pallets_bloques(df, "BK31", contador=[0], pallets_objetivo=1)
    assert len(pallets) == 1
    despachado = sum(t.cantidad for p in pallets for t in p.torres)
    sin_colocar = pallets[-1].metadata.get("sin_colocar", {})
    assert despachado + sum(sin_colocar.values()) == 92 + 25
    assert validar_geometria_v5(pallets) == []


def test_snapshot_restaurar_estado_pallets_es_identidad():
    """[invariante de undo, base del backtracking real -bug real
    encontrado y corregido en esta sesión] `_PalletEnConstruccion.colocar`
    muta `pallet.torres` con `.append()` en el MISMO objeto lista (a
    diferencia de `pc.libres`, que sí se reemplaza por una lista nueva en
    cada colocación) -un snapshot que solo guardara la LONGITUD de
    `torres` y después recortara la lista ACTUAL con `[:n]` fallaba en
    cuanto se restauraba un snapshot más viejo DESPUÉS de haber hecho
    backtrack más allá de él (la lista ya había sido truncada a algo más
    corto por un restore intermedio). Este test fija el contrato: colocar,
    tomar snapshot, colocar más, restaurar -el estado debe volver EXACTO
    al punto del snapshot, sin importar cuánto se avanzó después."""
    df = pd.DataFrame([_fila("A", 30, 20, 20.0, 20, cajas_cama=12, nivel=1)])
    candidatas = generar_torres_candidatas(df, config.ALTURA_PRODUCTO_MAX)
    cand = candidatas[0]
    pallet = PalletV5(id="P1", cd="BK31")
    pc = _PalletEnConstruccion(pallet=pallet)
    colocados_por_pallet = [{}]
    pendientes = {"A": 20}
    nivel_por_sku = {"A": 1}

    def _colocar_una():
        idx = _mejor_cuboide_para_sku(pallet, pc, cand, 12, 1, nivel_por_sku)
        pc.colocar(cand, 1, idx)
        pendientes["A"] -= 1
        colocados_por_pallet[0]["A"] = colocados_por_pallet[0].get("A", 0) + 1

    for _ in range(3):
        _colocar_una()

    snap = _snapshot_estado_pallets([pc], colocados_por_pallet, pendientes)
    torres_en_snapshot = len(pallet.torres)
    altura_en_snapshot = pallet.altura_final

    for _ in range(5):
        _colocar_una()
    assert len(pallet.torres) != torres_en_snapshot  # de verdad avanzó más allá del snapshot

    _restaurar_estado_pallets([pc], colocados_por_pallet, pendientes, snap)
    assert len(pallet.torres) == torres_en_snapshot
    assert pallet.altura_final == altura_en_snapshot
    assert colocados_por_pallet[0]["A"] == 3
    assert pendientes["A"] == 17
