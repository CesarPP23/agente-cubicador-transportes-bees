"""[V5-P4] Transforma demanda de cajas en candidatos verticales (torres).

DOCUMENTACION_TECNICA_V5.md sección 6.
"""
from dataclasses import dataclass

import pandas as pd

import config
from models import PlacementCaja, Torre


@dataclass(frozen=True)
class TorreCandidate:
    """Una combinación (SKU, orientación) posible como torre -todavía sin
    posición XY ni cantidad decidida, eso lo resuelve el packer (P5)."""

    sku: str
    cd: str
    orientacion: str
    largo: float
    ancho: float
    alto_caja: float
    max_cajas_verticales: int
    cantidad_disponible: int
    peso_unitario: float
    fuente_geometria: str = ""


def generar_torres_candidatas(
    df_cd: pd.DataFrame,
    altura_max_producto: float,
    permitir_rotacion_xy: bool = True,
) -> list[TorreCandidate]:
    """[sección 6] Por cada SKU del CD (con demanda pendiente y geometría
    efectiva ya reconciliada -Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo,
    ver reconciliacion_geometrica.py), arma las TorreCandidate posibles: una
    por orientación XY válida.

    `max_cajas_verticales = floor(altura_max_producto / alto_caja)` -el
    packer decide cuántas usar de verdad, esto es solo el techo físico.
    Nunca obliga a usar el máximo (DOCUMENTACION_TECNICA_V5.md sección 6)."""
    candidatas: list[TorreCandidate] = []

    col_cantidad = "Cajas_Remanente" if "Cajas_Remanente" in df_cd.columns else "Cajas_Teoricas_Redondeadas"

    for _, row in df_cd.iterrows():
        cantidad_disponible = int(row[col_cantidad]) if pd.notna(row[col_cantidad]) else 0
        if cantidad_disponible <= 0:
            continue

        largo, ancho, alto = row.get("Largo_Efectivo"), row.get("Ancho_Efectivo"), row.get("Alto_Efectivo")
        if pd.isna(largo) or pd.isna(ancho) or pd.isna(alto) or alto <= 0:
            continue

        max_vert = max(int(altura_max_producto // alto), 0)
        if max_vert <= 0:
            continue

        peso_unitario = row.get("Peso_Caja") or 0.0
        fuente = row.get("Fuente_Geometria", "")
        sku, cd = row["SKU"], row["CD"]

        orientaciones = [(largo, ancho, "L×A")]
        if permitir_rotacion_xy and ancho != largo:
            orientaciones.append((ancho, largo, "A×L"))

        for l, a, ori in orientaciones:
            candidatas.append(
                TorreCandidate(
                    sku=sku, cd=cd, orientacion=ori, largo=l, ancho=a, alto_caja=alto,
                    max_cajas_verticales=max_vert, cantidad_disponible=cantidad_disponible,
                    peso_unitario=peso_unitario, fuente_geometria=fuente,
                )
            )

    return candidatas


def generar_torres_candidatas_todas_orientaciones(
    df_cd: pd.DataFrame, altura_max_producto: float
) -> list[TorreCandidate]:
    """[llenado de huecos -pedido explícito del usuario] Como
    `generar_torres_candidatas`, pero para cada SKU genera las 6
    orientaciones posibles (cualquiera de las 3 dimensiones de la caja
    puede quedar vertical, con las otras dos en cualquier orden en el
    plano XY) -no solo las 2 "de pie" (Alto_Efectivo siempre vertical).
    Uso exclusivo del relleno de huecos: SKUs de Comestibles/Aseo/
    Cigarros pueden acostarse/voltearse para aprovechar espacios
    irregulares; NABs NUNCA usa esta función -siempre va de pie (usar
    `generar_torres_candidatas` normal para esos)."""
    candidatas: list[TorreCandidate] = []
    col_cantidad = "Cajas_Remanente" if "Cajas_Remanente" in df_cd.columns else "Cajas_Teoricas_Redondeadas"

    for _, row in df_cd.iterrows():
        cantidad_disponible = int(row[col_cantidad]) if pd.notna(row[col_cantidad]) else 0
        if cantidad_disponible <= 0:
            continue

        largo, ancho, alto = row.get("Largo_Efectivo"), row.get("Ancho_Efectivo"), row.get("Alto_Efectivo")
        if pd.isna(largo) or pd.isna(ancho) or pd.isna(alto) or alto <= 0:
            continue

        peso_unitario = row.get("Peso_Caja") or 0.0
        fuente = row.get("Fuente_Geometria", "")
        sku, cd = row["SKU"], row["CD"]

        combinaciones = [
            (largo, ancho, alto, "L×A(de pie)"),
            (ancho, largo, alto, "A×L(de pie)"),
            (largo, alto, ancho, "L×H(acostado)"),
            (alto, largo, ancho, "H×L(acostado)"),
            (ancho, alto, largo, "A×H(acostado)"),
            (alto, ancho, largo, "H×A(acostado)"),
        ]
        vistos: set[tuple[float, float, float]] = set()
        for l, a, h, ori in combinaciones:
            # cajas con dimensiones iguales entre sí (ej. cuadradas en
            # planta, o un cubo) generan combinaciones idénticas -evita
            # duplicar candidatas que no aportan nada nuevo.
            clave = (round(l, 6), round(a, 6), round(h, 6))
            if clave in vistos:
                continue
            vistos.add(clave)

            max_vert = max(int(altura_max_producto // h), 0)
            if max_vert <= 0:
                continue

            candidatas.append(
                TorreCandidate(
                    sku=sku, cd=cd, orientacion=ori, largo=l, ancho=a, alto_caja=h,
                    max_cajas_verticales=max_vert, cantidad_disponible=cantidad_disponible,
                    peso_unitario=peso_unitario, fuente_geometria=fuente,
                )
            )

    return candidatas


def crear_torre(
    candidata: TorreCandidate, x: float, y: float, cantidad: int, z: float = 0.0
) -> Torre:
    """Instancia una Torre concreta (posición XY fija) a partir de una
    TorreCandidate, con `cantidad` cajas apiladas -nunca más que
    `candidata.max_cajas_verticales` ni que `candidata.cantidad_disponible`.

    `z` (default 0.0, compatibilidad con torres que arrancan del piso): base
    del segmento dentro de la pila de producto -packing 3D (ver
    `packing_columnar.py`) la usa para apilar esta torre ENCIMA de otra
    distinta en el mismo (x, y)."""
    cantidad = max(0, min(cantidad, candidata.max_cajas_verticales, candidata.cantidad_disponible))
    placements = [
        PlacementCaja(
            sku=candidata.sku, x=x, y=y, z=z + i * candidata.alto_caja,
            largo=candidata.largo, ancho=candidata.ancho, alto=candidata.alto_caja,
            orientacion=candidata.orientacion, indice=i,
        )
        for i in range(cantidad)
    ]
    return Torre(
        sku=candidata.sku, cd=candidata.cd, x=x, y=y,
        largo=candidata.largo, ancho=candidata.ancho, alto_caja=candidata.alto_caja,
        cantidad=cantidad, peso=cantidad * candidata.peso_unitario,
        orientacion=candidata.orientacion, fuente_geometria=candidata.fuente_geometria,
        placements=placements, z=z,
    )


def dividir_torre(torre: Torre, cantidad_primera: int) -> tuple[Torre, Torre]:
    """[usado por residual_search, P8] Parte una torre en dos -misma
    posición XY (la segunda queda "flotando", el packer la reubica), mismo
    SKU/geometría, demanda total preservada. `cantidad_primera` cajas quedan
    en la primera torre, el resto en la segunda."""
    if not (0 <= cantidad_primera <= torre.cantidad):
        raise ValueError(f"cantidad_primera={cantidad_primera} fuera de rango para torre de {torre.cantidad} cajas")

    resto = torre.cantidad - cantidad_primera

    def _sub_torre(cantidad: int, placements: list[PlacementCaja]) -> Torre:
        return Torre(
            sku=torre.sku, cd=torre.cd, x=torre.x, y=torre.y,
            largo=torre.largo, ancho=torre.ancho, alto_caja=torre.alto_caja,
            cantidad=cantidad, peso=(cantidad * (torre.peso / torre.cantidad) if torre.cantidad else 0.0),
            orientacion=torre.orientacion, fuente_geometria=torre.fuente_geometria,
            placements=[PlacementCaja(**{**p.__dict__, "indice": i}) for i, p in enumerate(placements)],
            z=torre.z,
        )

    primera = _sub_torre(cantidad_primera, torre.placements[:cantidad_primera])
    segunda = _sub_torre(resto, torre.placements[cantidad_primera:])
    return primera, segunda


def torre_a_dict(torre: Torre) -> dict:
    """[serialización temporal, para debug/export antes de P13] Representación
    plana de una torre, sin sus placements individuales (eso es mucho detalle
    para un resumen -placements se exportan aparte, ver exportar.py)."""
    return {
        "sku": torre.sku,
        "cd": torre.cd,
        "x": torre.x,
        "y": torre.y,
        "largo": torre.largo,
        "ancho": torre.ancho,
        "alto_caja": torre.alto_caja,
        "cantidad": torre.cantidad,
        "altura": torre.altura,
        "peso": torre.peso,
        "orientacion": torre.orientacion,
        "fuente_geometria": torre.fuente_geometria,
    }
