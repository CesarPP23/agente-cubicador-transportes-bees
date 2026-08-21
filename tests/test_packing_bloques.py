"""[SKU_BLOQUE, camas] El pallet se arma CAMA POR CAMA (piso por piso), no
por columnas verticales de un solo SKU -corrección explícita del usuario:
"nunca pero nunca se empieza haciendo columnas, siempre primero se van
llenando las filas de abajo hacia arriba". Dentro de una cama, otros SKUs
solo se agregan si su altura es compatible (hueco chico, cama estable)."""
import pandas as pd

from src.packing_bloques import TOLERANCIA_HUECO_CAMA_CM, armar_pallets_bloques
from src.validacion_v5 import validar_geometria_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_cama=None, cd="BK31"):
    fila = {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
    }
    if cajas_cama is not None:
        fila["Cajas_Cama_Efectivo"] = cajas_cama
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


def test_sku_muy_mas_bajo_no_comparte_cama_aunque_fisicamente_entre():
    """[bug real encontrado] Un SKU MUCHO más bajo que el ancla puede
    entrar físicamente en la profundidad de la cama (ej. una cama de 100cm
    fácilmente aloja una caja de 20cm) pero dejaría un hueco de 80cm por
    encima -exactamente lo que se quiere evitar. La tolerancia tiene que
    ser simétrica: no solo "no más alto", también "no mucho más bajo"."""
    df = pd.DataFrame(
        [
            _fila("ALTO", 100, 90, 100.0, 5, cajas_cama=1),  # más demanda -> ancla
            _fila("BAJITO", 15, 8, 20.0, 3, cajas_cama=50),  # 100 - 20 = 80cm >> tolerancia
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    grupos = _torres_por_z(pallets)
    for g in grupos.values():
        skus = {t.sku for t in g}
        assert skus != {"ALTO", "BAJITO"}, "ALTO y BAJITO no deberían compartir cama -el hueco sería enorme"


def test_sku_de_altura_incompatible_no_comparte_cama():
    """Un SKU mucho más alto que el ancla NO puede sumarse a esa cama -se
    saldría del hueco tolerado. Tiene que esperar su propia cama."""
    df = pd.DataFrame(
        [
            _fila("BAJO", 100, 90, 15.0, 5, cajas_cama=1),  # más demanda -> ancla
            _fila("ALTO", 15, 8, 40.0, 3, cajas_cama=50),  # 40 - 15 = 25cm > tolerancia
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    grupos = _torres_por_z(pallets)
    for g in grupos.values():
        skus = {t.sku for t in g}
        assert skus != {"BAJO", "ALTO"}, "BAJO y ALTO no deberían compartir cama -su diferencia de altura excede la tolerancia"


def test_ninguna_cama_tiene_huecos_mas_grandes_que_la_tolerancia():
    """Invariante central del pedido: dentro de una MISMA cama, ningún SKU
    puede quedar tan bajo que deje un hueco de aire grande -la diferencia
    entre la altura de la cama y la de cualquier torre que la comparte debe
    quedar dentro de TOLERANCIA_HUECO_CAMA_CM."""
    df = pd.DataFrame(
        [
            _fila("A", 40, 30, 25.0, 6, cajas_cama=10),
            _fila("B", 25, 20, 20.0, 8, cajas_cama=30),
            _fila("C", 15, 15, 22.0, 20, cajas_cama=60),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    grupos = _torres_por_z(pallets)
    for (pallet_id, z), torres in grupos.items():
        alturas = [t.altura for t in torres]
        assert max(alturas) - min(alturas) <= TOLERANCIA_HUECO_CAMA_CM + 1e-6, (
            f"{pallet_id} cama z={z}: hueco de {max(alturas) - min(alturas):.1f}cm supera la tolerancia"
        )


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
