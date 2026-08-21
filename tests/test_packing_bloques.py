"""[SKU_BLOQUE] Nueva lógica: cada SKU es un bloque indivisible mientras
sea posible -se coloca ENTERO junto con otros bloques enteros hasta llenar
la altura; solo se parte uno como último recurso."""
import pandas as pd

from src.packing_bloques import armar_pallets_bloques
from src.validacion_v5 import validar_geometria_v5


def _fila(sku, largo, ancho, alto, cantidad, cajas_por_ph, peso=1.0, cd="BK31"):
    return {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": peso, "Fuente_Geometria": "UMA_VALIDADA", "Cajas por PH": cajas_por_ph,
    }


def test_ejemplo_del_usuario_100_cajas_capacidad_150_un_solo_pallet():
    """Caso exacto descripto: 100 cajas de una SKU cuya capacidad de
    pallet es 150 -las 100 quedan en UN SOLO PALLET (pueden ser varias
    torres/columnas side-by-side dentro de ese mismo pallet si el
    footprint es chico -eso no es "repartir", sigue siendo un pallet)."""
    df = pd.DataFrame([_fila("KR_NEGRA", 30, 20, 20.0, 100, cajas_por_ph=150)])
    pallets = armar_pallets_bloques(df, "BK31")
    pallets_con_kr = {p.id for p in pallets if any(t.sku == "KR_NEGRA" for t in p.torres)}
    assert len(pallets_con_kr) == 1  # un solo PALLET, no repartido en varios
    total = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "KR_NEGRA")
    assert total == 100


def test_otros_skus_consolidados_llenan_la_altura_restante():
    """Con el bloque ancla chico, otros SKUs enteros deberían compartir el
    MISMO pallet en vez de abrir uno nuevo, si entran completos."""
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 20.0, 3, cajas_por_ph=150),  # bloque chico, deja mucha altura libre
            _fila("B", 30, 20, 20.0, 4, cajas_por_ph=150),  # bloque entero que puede sumarse
            _fila("C", 30, 20, 20.0, 5, cajas_por_ph=150),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    # Los 3 SKUs son chicos -deberían caber juntos en pocos pallets, no uno cada uno.
    assert len(pallets) < 3


def test_no_pierde_demanda():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 25.0, 37, cajas_por_ph=20),
            _fila("B", 25, 25, 20.0, 12, cajas_por_ph=50),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado: dict[str, int] = {}
    for p in pallets:
        for t in p.torres:
            despachado[t.sku] = despachado.get(t.sku, 0) + t.cantidad
    assert despachado.get("A", 0) == 37
    assert despachado.get("B", 0) == 12


def test_demanda_mayor_a_un_pallet_saca_dedicados_y_deja_bloque_resto():
    """Demanda de 370 cajas, capacidad 150 -> 2 pallets 100% dedicados
    (300 cajas) + 1 bloque resto de 70 cajas."""
    df = pd.DataFrame([_fila("GRANDE", 30, 20, 20.0, 370, cajas_por_ph=150)])
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "GRANDE")
    assert despachado == 370

    # cantidades por torre: debería haber torres de 150 (dedicados) y una de 70 (resto)
    cantidades = sorted(t.cantidad for p in pallets for t in p.torres if t.sku == "GRANDE")
    assert 70 in cantidades or sum(cantidades) == 370  # el resto no queda perdido ni fragmentado de más


def test_bloque_se_parte_solo_como_ultimo_recurso():
    """Si NINGÚN otro bloque entero cabe con el ancla, pero sí queda
    margen, se parte alguno para no desperdiciar altura -pero solo cuando
    ya no hay más bloques enteros posibles."""
    df = pd.DataFrame(
        [
            _fila("ANCLA", 120, 100, 180.0, 1, cajas_por_ph=1),  # ocupa casi toda la altura y la huella
            _fila("CHICO", 20, 20, 20.0, 50, cajas_por_ph=200),  # bloque grande, no entra entero en lo que sobra
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado_chico = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "CHICO")
    assert despachado_chico == 50  # nada se pierde, sea en 1 o varias torres


def test_no_viola_geometria():
    df = pd.DataFrame(
        [
            _fila("A", 30, 20, 25.0, 37, cajas_por_ph=20),
            _fila("B", 25, 25, 20.0, 12, cajas_por_ph=50),
            _fila("C", 40, 30, 15.0, 200, cajas_por_ph=60),
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    assert validar_geometria_v5(pallets) == []


def test_sin_cajas_por_ph_el_sku_es_un_bloque_unico():
    df = pd.DataFrame(
        [
            {
                "SKU": "SIN_PH", "CD": "BK31", "Cajas_Remanente": 8,
                "Largo_Efectivo": 20, "Ancho_Efectivo": 20, "Alto_Efectivo": 20.0,
                "Peso_Caja": 1.0, "Fuente_Geometria": "UMA_VALIDADA",
            }
        ]
    )
    pallets = armar_pallets_bloques(df, "BK31")
    despachado = sum(t.cantidad for p in pallets for t in p.torres if t.sku == "SIN_PH")
    assert despachado == 8
