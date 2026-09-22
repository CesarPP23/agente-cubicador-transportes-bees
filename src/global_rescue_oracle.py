"""[PATCH V6.05, Fase 2.1] Oráculo de candidatos INDEPENDIENTE de MaxRects
-pedido explícito del usuario para la auditoría de completitud del espacio
de búsqueda: "un helper de diagnóstico que NO dependa de los cuboides_
libres de MaxRects para decidir dónde puede ir una caja."

Este módulo es SOLO DIAGNÓSTICO. No se conecta a `global_rescue.py` ni a
`packing_bloques.py` -sirve para responder, offline y sobre una muestra
acotada de estados, "¿el candidate generator basado en MaxRects (`_generar_
candidatos_multi_pallet`) está de acuerdo con lo que dicen las reglas
geométricas REALES aplicadas directamente, sin pasar por la representación
de cuboides libres?".

[Por qué NO reinventa las reglas] Un oráculo que reimplementara sus PROPIAS
versiones de overhang/soporte/jerarquía sería inútil como referencia -sus
propios bugs contaminarían la comparación. Este módulo reutiliza las MISMAS
funciones de validación que ya usa el resto del motor (`_solapa_con_torres`,
`_tiene_soporte_admisible`, `_soporte_viola_nivel`, `_altura_compatible_con_
cama`, `_capacidad_restante_en_capa`, todas de `packing_bloques.py`/
`validacion_v5.py`) -lo único que cambia es CÓMO se generan las posiciones
candidatas a validar: no a partir de la lista `libres` de MaxRects, sino de
un enumerador estructural directo (bordes del envelope + bordes de las
cajas ya puestas + Z=0 y tops existentes), como pide el usuario."""
from __future__ import annotations

from dataclasses import dataclass

import config
from models import PalletV5
from src.torres import TorreCandidate, crear_torre

TOL = 1e-6


@dataclass(frozen=True)
class PosicionOraculo:
    """Una posición candidata concreta ya validada por el oráculo."""

    x: float
    y: float
    z: float
    cand: TorreCandidate


def _generar_posiciones_estructurales(
    pallet: PalletV5, cand: TorreCandidate,
) -> list[tuple[float, float, float]]:
    """[sección 3 del pedido] Posiciones candidatas SIN mirar `libres`:

    - bordes del envelope/pallet: x=0, x=PALLET_LARGO; y=0, y=PALLET_ANCHO
      (con el margen de sobresaliente, igual que el resto del motor).
    - bordes X/Y de las cajas ya colocadas (`t.x`, `t.y`).
    - bordes MENOS largo/ancho de la caja candidata (`t.x + t.largo -
      cand.largo`, etc.) -así una caja puede "pegarse" contra el borde
      DERECHO de una ya puesta, no solo contra su borde izquierdo.
    - Z=0 (piso) y Z=tops de cajas/superficies existentes (`t.z + t.altura`).

    Es un enumerador de "puntos de esquina" clásico de bin-packing (no
    MaxRects, no guillotina) -deliberadamente más lento y más exhaustivo,
    para servir de referencia independiente."""
    margen = config.SOBRESALIENTE_MAX_CM
    xs = {-margen, config.PALLET_LARGO + margen - cand.largo}
    ys = {-margen, config.PALLET_ANCHO + margen - cand.ancho}
    zs = {0.0}
    for t in pallet.torres:
        xs.add(t.x)
        xs.add(t.x + t.largo - cand.largo)
        ys.add(t.y)
        ys.add(t.y + t.ancho - cand.ancho)
        zs.add(t.z + t.altura)

    return [(x, y, z) for x in xs for y in ys for z in zs]


def _dentro_de_bordes(x: float, y: float, cand: TorreCandidate) -> bool:
    """[overhang] Mismo margen simétrico que `_fit_directo_o_con_tolerancia`
    -hasta `SOBRESALIENTE_MAX_CM` por lado respecto de la base física."""
    margen = config.SOBRESALIENTE_MAX_CM
    return (
        x >= -margen - TOL and y >= -margen - TOL
        and x + cand.largo <= config.PALLET_LARGO + margen + TOL
        and y + cand.ancho <= config.PALLET_ANCHO + margen + TOL
    )


def _posicion_valida(
    pallet: PalletV5, x: float, y: float, z: float, cand: TorreCandidate,
    tope_capa: int | None, nivel_sku: int, nivel_por_sku: dict[str, int],
    tope_pallet: float, ya_en_pallet: int, presupuesto: float,
) -> bool:
    """[secciones geométricas reales, sección 3 del pedido] Valida UNA
    posición concreta contra las MISMAS reglas que ya usa el motor
    (reutilizadas, no reimplementadas):

    - overhang <=2cm/lado: `_dentro_de_bordes` (arriba).
    - overlap 3D = 0: `_solapa_con_torres` (packing_bloques.py, genérica,
      no depende de cuboides).
    - altura <=220: `z + alto_caja <= presupuesto` (presupuesto YA excluye
      la altura del pallet vacío, mismo criterio que `_altura_presupuesto`).
    - soporte completo por unión de superficies: `_tiene_soporte_admisible`
      (validacion_v5.py) contra TODAS las torres cuyo tope coincide con
      `z` -a diferencia de un único cuboide MaxRects, esto SÍ puede
      combinar el soporte de 2+ cajas vecinas distintas (ver sección 5 del
      pedido, `test_soporte_por_union_de_dos_cajas_*`).
    - jerarquía: `_soporte_viola_nivel` (packing_bloques.py).
    - orientación: implícita -el llamador solo pasa TorreCandidate ya
      filtradas a orientaciones permitidas.
    - Cajas por PH: tope de pallet (`tope_pallet`) y tope de cama
      (`_capacidad_restante_en_capa`, packing_bloques.py)."""
    from src.packing_bloques import (
        _altura_compatible_con_cama,
        _capacidad_restante_en_capa,
        _solapa_con_torres,
        _soporte_viola_nivel,
    )
    from src.validacion_v5 import _tiene_soporte_admisible

    if not _dentro_de_bordes(x, y, cand):
        return False
    if z + cand.alto_caja > presupuesto + TOL:
        return False
    if ya_en_pallet + 1 > tope_pallet + TOL:
        return False
    if _capacidad_restante_en_capa(pallet, cand.sku, z, tope_capa) < 1 - TOL:
        return False
    if _solapa_con_torres(pallet, x, y, z, cand.largo, cand.ancho, cand.alto_caja):
        return False
    if _soporte_viola_nivel(pallet, x, y, cand.largo, cand.ancho, z, nivel_sku, nivel_por_sku):
        return False
    if not _altura_compatible_con_cama(pallet, z, cand.alto_caja):
        return False

    if z > TOL:
        torre_tentativa = crear_torre(cand, x=x, y=y, z=z, cantidad=1)
        soportes = [t for t in pallet.torres if abs((t.z + t.altura) - z) <= TOL]
        if not _tiene_soporte_admisible(torre_tentativa, soportes):
            return False

    return True


def enumerar_candidatos_oraculo(
    pallet: PalletV5, sku: str, candidatas_sku: list[TorreCandidate],
    tope_capa: int | None, nivel_sku: int, nivel_por_sku: dict[str, int],
    tope_pallet: float, ya_en_pallet: int, presupuesto: float,
    max_count: int | None = None,
) -> list[PosicionOraculo]:
    """[punto 3 del pedido] Enumerador de diagnóstico LENTO -O(cajas² x
    orientaciones) posiciones candidatas por llamada, sin ningún límite de
    poda- pensado para correr sobre una MUESTRA acotada de estados, nunca
    en el camino caliente del solver real. `max_count` (opcional) corta
    apenas se encuentran esa cantidad de posiciones válidas, para no pagar
    el costo completo cuando solo hace falta el booleano "¿hay alguna?"."""
    encontrados: list[PosicionOraculo] = []
    vistos: set[tuple[float, float, float, str]] = set()
    for cand in candidatas_sku:
        for x, y, z in _generar_posiciones_estructurales(pallet, cand):
            clave = (round(x, 4), round(y, 4), round(z, 4), cand.orientacion)
            if clave in vistos:
                continue
            vistos.add(clave)
            if _posicion_valida(
                pallet, x, y, z, cand, tope_capa, nivel_sku, nivel_por_sku,
                tope_pallet, ya_en_pallet, presupuesto,
            ):
                encontrados.append(PosicionOraculo(x=x, y=y, z=z, cand=cand))
                if max_count is not None and len(encontrados) >= max_count:
                    return encontrados
    return encontrados
