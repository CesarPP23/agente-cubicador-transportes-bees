"""[PATCH V6.07] Structural Candidate Engine EFICIENTE -misma capacidad
representacional que V6.06 (soporte por unión de 2+ cajas, posiciones fuera
de `pc.libres`), órdenes de magnitud menos enumeración.

[Motivación, evidencia V6.06 sobre BK52 real] `structural_fallback_calls:
3059` -> `raw positions: 68.256.858` (~22.300 posiciones crudas por
llamada) -> solo `7.042` válidas, `13` únicas. El primer reinicio del
multi-start agotó el presupuesto compartido de 180s SOLO en profundidad
28, contra ~34.000 estados y 3 reinicios completos de V6.05 (sin híbrido).
La causa: `V6.06::_generar_candidatos_estructurales_para_pallet` armaba el
producto cartesiano COMPLETO de bordes X (de TODAS las torres) × bordes Y
(de TODAS las torres) × Z (tops de TODAS las torres) ANTES de filtrar nada
-incluso para `_existe_candidato_estructural` (que solo necesita 1), la
lista completa ya estaba construida.

[Qué cambia acá, sección por sección del parche]
1. Generador LAZY (`_iter_candidatos_estructurales_multi_pallet`, generator
   real con `yield`) -nunca materializa una lista completa; `existe`/
   `contar`/`generar` extraen de él solo lo que necesitan y cortan ahí.
2. Por PLANO Z, no producto cartesiano global: z=0 usa obstáculos que
   intersectan verticalmente la altura del candidato; z>0 usa SOLO las
   torres cuyo tope coincide EXACTO con ese z (nunca bordes de una torre
   que termina en otro Z).
3. Prefiltro por COMPONENTE de soporte (rectángulos tocantes/solapados en
   el mismo plano Z) -si el bbox del componente no puede contener la
   huella, o su área unión es menor que la huella, no se generan anclas
   para ese componente. Prefiltro conservador (puede aceptar de más, nunca
   descarta de más) -la validación final de soporte sigue siendo la MISMA
   `_tiene_soporte_admisible` exacta que ya usaba V6.06/`validar_pallet_
   v5`, nunca una tercera definición.
4. Prefiltros baratos ANTES del soporte exacto: bounds/overhang -> altura
   -> Cajas por PH/tope de cama -> overlap AABB -> (bounding support
   potencial, ya cubierto por el prefiltro de componente en 3) -> soporte
   exacto -> jerarquía/altura de cama.
5. Cache efímero POR ESTADO (una instancia de `CacheEstructural` por
   llamada a `_expandir_estado`, nunca global/persistente entre miles de
   estados -sección 8) que memoiza el generador YA AVANZADO por sku, así
   `existe -> contar -> generar` para el MISMO (estado, sku) reutilizan
   trabajo en vez de recomputar desde cero (sección 9).

[Qué NO cambia] La geometría/reglas de validación son las MISMAS de V6.06,
reutilizadas sin reimplementar (`_solapa_con_torres`, `_soporte_viola_
nivel`, `_altura_compatible_con_cama`, `_capacidad_restante_en_capa`,
`_tiene_soporte_admisible`, `_cantidad_sin_solape`). `src/global_rescue_
oracle.py` (el oráculo lento de referencia) NO se toca -sigue siendo la
fuente independiente para verificar paridad (sección 11)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator

import config
from models import PalletV5, Torre
from src.torres import TorreCandidate, crear_torre

TOL = 1e-6

# [sección 10] Buffer chico de candidatos estructurales VÁLIDOS antes de
# pasar a `_seleccionar_top_k_diverso` -no hace falta materializar miles,
# alcanza con una muestra razonable para que la selección diversa tenga
# margen de sobra sobre `GLOBAL_BRANCH_TOP_K` (5). Esto NO cambia
# `GLOBAL_BRANCH_TOP_K`.
STRUCTURAL_VALID_BUFFER = 32


def _stat_incr(stats: dict | None, clave: str, delta: int = 1) -> None:
    if stats is not None:
        stats[clave] = stats.get(clave, 0) + delta


@dataclass
class _Rect:
    x: float
    y: float
    w: float
    h: float


def _rects_tocan_o_solapan(a: _Rect, b: _Rect, tol: float = TOL) -> bool:
    """[sección 6] "Tocantes" incluye compartir borde (huecos de punto
    flotante) -umbral chico (`TOL`), no el margen de sobresaliente de 2cm
    (ese es una tolerancia de VALIDACIÓN final, no de agrupamiento; ver
    docstring del módulo -el prefiltro es conservador por diseño: agrupar
    de más nunca rechaza una ancla válida, la validación exacta de abajo
    sigue siendo la que decide)."""
    return not (
        a.x + a.w < b.x - tol or b.x + b.w < a.x - tol
        or a.y + a.h < b.y - tol or b.y + b.h < a.y - tol
    )


def _componentes_conectados(rects: list[tuple[_Rect, Torre]]) -> list[list[tuple[_Rect, Torre]]]:
    """[sección 6] Union-find O(n^2) sobre los rectángulos de UN plano Z
    -n es la cantidad de torres cuyo tope coincide con ese Z exacto,
    típicamente chico (no todas las torres del pallet)."""
    n = len(rects)
    padre = list(range(n))

    def _find(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def _unir(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            padre[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _rects_tocan_o_solapan(rects[i][0], rects[j][0]):
                _unir(i, j)

    grupos: dict[int, list[tuple[_Rect, Torre]]] = {}
    for i in range(n):
        grupos.setdefault(_find(i), []).append(rects[i])
    return list(grupos.values())


def _area_union_rects(rects: list[_Rect]) -> float:
    """Área de la unión de rectángulos -mismo sweep por coordenadas
    comprimidas que `_area_union_xy`/`_area_cubierta_por_soporte`, acá
    sobre un componente chico (no todo el pallet)."""
    if not rects:
        return 0.0
    xs = sorted({r.x for r in rects} | {r.x + r.w for r in rects})
    ys = sorted({r.y for r in rects} | {r.y + r.h for r in rects})
    area = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x1 - x0 <= TOL:
            continue
        mx = (x0 + x1) / 2
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            if y1 - y0 <= TOL:
                continue
            my = (y0 + y1) / 2
            if any(r.x - TOL <= mx <= r.x + r.w + TOL and r.y - TOL <= my <= r.y + r.h + TOL for r in rects):
                area += (x1 - x0) * (y1 - y0)
    return area


def _bordes_xy(rects: list[_Rect], cand_largo: float, cand_ancho: float, margen: float) -> tuple[set, set]:
    """[sección 4] Coordenadas X/Y candidatas SOLO desde los bordes
    relevantes (envelope + estos rects) -deduplicado ANTES del producto
    cartesiano X×Y (acá ya es chico: unos pocos rects por plano/
    componente, no todas las torres del pallet)."""
    xs = {-margen, config.PALLET_LARGO + margen - cand_largo}
    ys = {-margen, config.PALLET_ANCHO + margen - cand_ancho}
    for r in rects:
        xs.add(r.x)
        xs.add(r.x + r.w - cand_largo)
        ys.add(r.y)
        ys.add(r.y + r.h - cand_ancho)
    return xs, ys


def _iter_posiciones_estructurales_para_candidato(
    pallet: PalletV5, cand: TorreCandidate, presupuesto: float, stats: dict | None,
) -> Iterator[tuple[float, float, float, list[Torre]]]:
    """[secciones 3, 4, 6] Genera posiciones `(x, y, z, soportes_del_plano)`
    PLANO POR PLANO -nunca un cartesiano global. `soportes_del_plano` va
    vacío para z=0 (piso, siempre permisivo) y contiene solo las torres
    cuyo tope coincide EXACTO con ese z para z>0 (nunca bordes de una
    torre que termina en otro Z)."""
    margen = config.SOBRESALIENTE_MAX_CM
    torres = pallet.torres

    # --- Plano z=0 (piso) ---------------------------------------------
    # [sección 3] Obstáculos = torres cuyo rango Z se solapa con el que
    # ocuparía el candidato ([0, alto_caja)) -son los únicos relevantes
    # para elegir bordes X/Y a esta altura (overlap), el piso en sí NUNCA
    # exige soporte (jerarquía/altura de cama ya son permisivas en z=0).
    obstaculos_piso = [
        _Rect(t.x, t.y, t.largo, t.ancho) for t in torres
        if t.z < cand.alto_caja - TOL and t.z + t.altura > TOL
    ]
    xs0, ys0 = _bordes_xy(obstaculos_piso, cand.largo, cand.ancho, margen)
    for x in xs0:
        for y in ys0:
            yield (x, y, 0.0, [])

    # --- Planos z>0 (tops exactos de torres) ----------------------------
    tops: dict[float, list[Torre]] = {}
    for t in torres:
        top = t.z + t.altura
        if top <= TOL:
            continue
        tops.setdefault(round(top, 6), []).append(t)

    for z, torres_en_plano in tops.items():
        if z + cand.alto_caja > presupuesto + TOL:
            continue  # [prefiltro barato: altura] ni vale la pena procesar este plano
        rects = [(_Rect(t.x, t.y, t.largo, t.ancho), t) for t in torres_en_plano]
        for componente in _componentes_conectados(rects):
            rects_comp = [r for r, _t in componente]
            bbox_x0 = min(r.x for r in rects_comp)
            bbox_x1 = max(r.x + r.w for r in rects_comp)
            bbox_y0 = min(r.y for r in rects_comp)
            bbox_y1 = max(r.y + r.h for r in rects_comp)
            # [sección 6, prefiltro de componente -CONSERVADOR: si falla,
            # NINGUNA posición de este componente podría pasar el soporte
            # exacto (el bbox ni siquiera contiene la huella, o el área
            # unión ya es menor que lo que la huella necesita) -si pasa,
            # NO garantiza validez, la validación exacta de abajo decide.]
            if (bbox_x1 - bbox_x0) + 2 * margen + TOL < cand.largo:
                continue
            if (bbox_y1 - bbox_y0) + 2 * margen + TOL < cand.ancho:
                continue
            if _area_union_rects(rects_comp) + TOL < cand.largo * cand.ancho:
                continue
            xs, ys = _bordes_xy(rects_comp, cand.largo, cand.ancho, margen)
            soportes = [t for _r, t in componente]
            for x in xs:
                for y in ys:
                    yield (x, y, z, soportes)


def _validar_y_dimensionar(
    pallet: PalletV5, sku: str, cand: TorreCandidate, x: float, y: float, z: float, soportes_del_plano: list[Torre],
    tope_capa: int | None, nivel_sku: int, nivel_por_sku: dict[str, int],
    tope_pallet: float, ya_en_pallet: int, pendiente: int, presupuesto: float, stats: dict | None,
) -> int:
    """[sección 5] Cadena de prefiltros barato->caro. Devuelve `max_lote`
    (0 si la posición no es válida). Reutiliza EXACTAMENTE las mismas
    funciones de validación que V6.06 -ningún criterio nuevo, solo
    reordenado por costo y con instrumentación de en qué etapa se
    rechaza."""
    from src.packing_bloques import (
        _altura_compatible_con_cama,
        _cantidad_sin_solape,
        _capacidad_restante_en_capa,
        _soporte_viola_nivel,
        _solapa_con_torres,
    )
    from src.packing_columnar import _CuboidLibre
    from src.validacion_v5 import _tiene_soporte_admisible

    _stat_incr(stats, "structural_positions_tested")

    margen = config.SOBRESALIENTE_MAX_CM
    # 1. bounds/overhang -el más barato, ni siquiera mira `pallet.torres`.
    if x < -margen - TOL or y < -margen - TOL:
        _stat_incr(stats, "structural_positions_rejected_bounds")
        return 0
    if x + cand.largo > config.PALLET_LARGO + margen + TOL or y + cand.ancho > config.PALLET_ANCHO + margen + TOL:
        _stat_incr(stats, "structural_positions_rejected_bounds")
        return 0
    # 2. altura.
    if z + cand.alto_caja > presupuesto + TOL:
        _stat_incr(stats, "structural_positions_rejected_bounds")
        return 0
    # 3. Cajas por PH / tope de cama / tope de pallet.
    if ya_en_pallet + 1 > tope_pallet + TOL:
        _stat_incr(stats, "structural_positions_rejected_bounds")
        return 0
    if _capacidad_restante_en_capa(pallet, sku, z, tope_capa) < 1 - TOL:
        _stat_incr(stats, "structural_positions_rejected_bounds")
        return 0
    # 4. overlap AABB 3D -ya no es barato (recorre torres), pero sigue
    #    siendo más barato que el soporte exacto.
    if _solapa_con_torres(pallet, x, y, z, cand.largo, cand.ancho, cand.alto_caja):
        _stat_incr(stats, "structural_positions_rejected_overlap")
        return 0
    # 5. bounding support potencial: YA se filtró por componente en el
    #    generador (sección 6) -acá solo queda la validación EXACTA.
    # 6. soporte exacto por unión (el único punto de verdad, reutilizado).
    if z > TOL:
        torre_tentativa = crear_torre(cand, x=x, y=y, z=z, cantidad=1)
        if not _tiene_soporte_admisible(torre_tentativa, soportes_del_plano):
            _stat_incr(stats, "structural_positions_rejected_support")
            return 0
    # 7. jerarquía / altura de cama.
    if _soporte_viola_nivel(pallet, x, y, cand.largo, cand.ancho, z, nivel_sku, nivel_por_sku):
        _stat_incr(stats, "structural_positions_rejected_support")
        return 0
    if not _altura_compatible_con_cama(pallet, z, cand.alto_caja):
        _stat_incr(stats, "structural_positions_rejected_support")
        return 0

    max_lote = min(
        pendiente, tope_pallet - ya_en_pallet,
        _capacidad_restante_en_capa(pallet, sku, z, tope_capa),
        int((presupuesto - z + TOL) // cand.alto_caja),
    )
    cuboide_sintetico = _CuboidLibre(x, y, z, cand.largo, cand.ancho, presupuesto - z)
    max_lote = _cantidad_sin_solape(pallet, cuboide_sintetico, cand, max_lote)
    return max(0, max_lote)


def _iter_candidatos_estructurales_para_pallet(
    pallet: PalletV5, sku: str, candidatas_sku: list[TorreCandidate],
    tope_capa: int | None, nivel_sku: int, nivel_por_sku: dict[str, int],
    tope_pallet: float, ya_en_pallet: int, pendiente: int, presupuesto: float, stats: dict | None,
) -> Iterator[tuple[float, float, float, TorreCandidate, int]]:
    """Generador LAZY -une la enumeración por plano (arriba) con la
    validación (arriba), sin materializar nada. `yield (x, y, z, cand,
    max_lote)` solo para posiciones VÁLIDAS."""
    if pendiente <= 0 or ya_en_pallet >= tope_pallet:
        return
    vistos: set[tuple[float, float, float, str]] = set()
    for cand in candidatas_sku:
        for x, y, z, soportes_del_plano in _iter_posiciones_estructurales_para_candidato(
            pallet, cand, presupuesto, stats,
        ):
            clave = (round(x, 2), round(y, 2), round(z, 2), cand.orientacion)
            if clave in vistos:
                continue
            vistos.add(clave)
            max_lote = _validar_y_dimensionar(
                pallet, sku, cand, x, y, z, soportes_del_plano, tope_capa, nivel_sku, nivel_por_sku,
                tope_pallet, ya_en_pallet, pendiente, presupuesto, stats,
            )
            if max_lote > 0:
                yield (x, y, z, cand, max_lote)


def _iter_candidatos_estructurales_multi_pallet(
    estado, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float, stats: dict | None,
) -> Iterator[tuple[int, float, float, float, TorreCandidate, int]]:
    """Encadena el generador de arriba sobre TODOS los pallets de
    `estado.construcciones` -sigue siendo un generator, `yield (pidx, x,
    y, z, cand, max_lote)`."""
    tope_capa = capacidad_cama_por_sku.get(sku)
    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
    tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
    pendiente = estado.pendientes.get(sku, 0)
    candidatas_sku = por_sku.get(sku, [])
    for pidx, pc in enumerate(estado.construcciones):
        ya_en_pallet = estado.colocados_por_pallet[pidx].get(sku, 0)
        if ya_en_pallet >= tope_pallet:
            continue
        for x, y, z, cand, max_lote in _iter_candidatos_estructurales_para_pallet(
            pc.pallet, sku, candidatas_sku, tope_capa, nivel_sku, nivel_por_sku,
            tope_pallet, ya_en_pallet, pendiente, presupuesto, stats,
        ):
            yield (pidx, x, y, z, cand, max_lote)


@dataclass
class _EntradaCache:
    iterador: Iterator | None
    encontrados: list = field(default_factory=list)
    agotado: bool = False


class CacheEstructural:
    """[sección 8] Cache EFÍMERA POR ESTADO -antes de V6.12-2A2 se creaba
    una instancia nueva por cada llamada a `_expandir_estado` (un solo
    `estado` padre) Y otra descartable por cada chequeo de viabilidad sin
    cache explícita (`_es_estado_inviable`); desde V6.12-2A2 esas
    instancias se buscan/asocian por estado exacto (ver `global_rescue.
    _cache_estructural_de_estado`/`_asociar_cache_estructural`) -sigue
    siendo efímera (nunca global entre estados DISTINTOS: cada `estado`
    -objeto Python, nunca reusado tras clonarse- tiene a lo sumo UNA cache
    asociada, y un hijo clonado nunca hereda la del padre, ver docstring
    de esas 2 funciones). Memoiza, por `(id(estado), sku)`, un generador
    YA AVANZADO -`existe`/`contar`/`generar` para el MISMO (estado, sku)
    piden más elementos al MISMO iterador en vez de reconstruirlo
    (sección 9: "si count(limit=4) ya encontró 4, exists() debe responder
    desde cache"). Lógica de cache SIN CAMBIOS en V6.12-2A2 -solo se
    agregaron 3 contadores puramente diagnósticos
    (`structural_enumerations_started/resumed/avoided`, sección 2A1)."""

    def __init__(self) -> None:
        self._entradas: dict[tuple[int, str], _EntradaCache] = {}

    def _entrada(self, estado, sku: str, generador_factory) -> _EntradaCache:
        clave = (id(estado), sku)
        entrada = self._entradas.get(clave)
        if entrada is None:
            entrada = _EntradaCache(iterador=generador_factory())
            self._entradas[clave] = entrada
        return entrada

    def _avanzar_hasta(self, entrada: _EntradaCache, hasta: int) -> None:
        if entrada.agotado or entrada.iterador is None:
            return
        while len(entrada.encontrados) < hasta:
            try:
                entrada.encontrados.append(next(entrada.iterador))
            except StopIteration:
                entrada.agotado = True
                entrada.iterador = None
                break

    def existe(self, estado, sku: str, generador_factory, stats: dict | None) -> bool:
        entrada = self._entrada(estado, sku, generador_factory)
        if entrada.encontrados:
            _stat_incr(stats, "structural_cache_hits")
            _stat_incr(stats, "structural_enumerations_avoided")
            return True
        if entrada.agotado:
            _stat_incr(stats, "structural_cache_hits")
            _stat_incr(stats, "structural_enumerations_avoided")
            return False
        _stat_incr(stats, "structural_cache_misses")
        # [sección 2A1] `entrada.encontrados` está vacío acá siempre (si no,
        # ya se habría retornado arriba) -para existe() esta rama es SIEMPRE
        # "started", nunca "resumed" (1 es el mínimo, cualquier hallazgo
        # previo ya cubre la pregunta). Se deja la expresión condicional por
        # simetría con contar()/generar(), donde sí puede ser "resumed".
        _stat_incr(stats, "structural_enumerations_resumed" if entrada.encontrados else "structural_enumerations_started")
        antes = len(entrada.encontrados)
        self._avanzar_hasta(entrada, 1)
        if len(entrada.encontrados) == antes and not entrada.agotado:
            pass  # no debería pasar (avanzar_hasta o agota o encuentra 1)
        encontrado = len(entrada.encontrados) > 0
        if encontrado:
            _stat_incr(stats, "structural_early_exit_exists")
        return encontrado

    def contar(self, estado, sku: str, generador_factory, limite: int, stats: dict | None) -> int:
        entrada = self._entrada(estado, sku, generador_factory)
        if len(entrada.encontrados) >= limite or entrada.agotado:
            _stat_incr(stats, "structural_cache_hits")
            _stat_incr(stats, "structural_enumerations_avoided")
            return min(len(entrada.encontrados), limite)
        _stat_incr(stats, "structural_cache_misses")
        _stat_incr(stats, "structural_enumerations_resumed" if entrada.encontrados else "structural_enumerations_started")
        self._avanzar_hasta(entrada, limite)
        if entrada.agotado or len(entrada.encontrados) >= limite:
            _stat_incr(stats, "structural_early_exit_count")
        return min(len(entrada.encontrados), limite)

    def generar(self, estado, sku: str, generador_factory, buffer: int, stats: dict | None) -> list:
        entrada = self._entrada(estado, sku, generador_factory)
        if len(entrada.encontrados) < buffer and not entrada.agotado:
            _stat_incr(stats, "structural_cache_misses")
            _stat_incr(
                stats, "structural_enumerations_resumed" if entrada.encontrados else "structural_enumerations_started",
            )
            self._avanzar_hasta(entrada, buffer)
        else:
            _stat_incr(stats, "structural_cache_hits")
            _stat_incr(stats, "structural_enumerations_avoided")
        return list(entrada.encontrados[:buffer])


def existe_candidato_estructural(
    estado, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float, cache: CacheEstructural, stats: dict | None,
) -> bool:
    """[sección 2, "Existencia"] Uso: poda. Corta en el PRIMER candidato
    válido -nunca enumera más de lo necesario."""
    t0 = time.time()
    _stat_incr(stats, "structural_exists_calls")
    resultado = cache.existe(
        estado, sku,
        lambda: _iter_candidatos_estructurales_multi_pallet(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
        ),
        stats,
    )
    if stats is not None:
        stats["structural_time_seconds"] = stats.get("structural_time_seconds", 0.0) + (time.time() - t0)
    return resultado


def contar_candidatos_estructurales(
    estado, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float, limite: int, cache: CacheEstructural, stats: dict | None,
) -> int:
    """[sección 2, "Conteo limitado"] Uso: MRV/scarcity. Corta al llegar a
    `limite` (típicamente `MAX_CANDIDATOS_PARA_SCARCITY`)."""
    t0 = time.time()
    _stat_incr(stats, "structural_count_calls")
    resultado = cache.contar(
        estado, sku,
        lambda: _iter_candidatos_estructurales_multi_pallet(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
        ),
        limite, stats,
    )
    if stats is not None:
        stats["structural_time_seconds"] = stats.get("structural_time_seconds", 0.0) + (time.time() - t0)
    return resultado


def generar_candidatos_estructurales(
    estado, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float, cache: CacheEstructural, stats: dict | None,
    buffer: int = STRUCTURAL_VALID_BUFFER,
) -> list[tuple[int, float, float, float, TorreCandidate, int]]:
    """[sección 2, "Generación"] Uso: SOLO para el SKU que realmente se
    expande (nunca para todos los pendientes) -devuelve hasta `buffer`
    candidatos válidos `(pidx, x, y, z, cand, max_lote)` (sección 10,
    `STRUCTURAL_VALID_BUFFER`), reutilizando lo que `existe`/`contar` ya
    hayan encontrado para este mismo (estado, sku) en el cache."""
    t0 = time.time()
    _stat_incr(stats, "structural_generate_calls")
    resultado = cache.generar(
        estado, sku,
        lambda: _iter_candidatos_estructurales_multi_pallet(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
        ),
        buffer, stats,
    )
    if stats is not None:
        stats["structural_time_seconds"] = stats.get("structural_time_seconds", 0.0) + (time.time() - t0)
    return resultado
