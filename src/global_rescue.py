"""[PATCH V6.05] Global Rescue -reconstrucción desde cero con Beam Search +
Most-Constrained-First GLOBAL, para cuando baseline + Rescue V6.02 + Repair
V6.04 + Exact Local Repair YA fallaron y todavía queda demanda pendiente.

[ADDENDUM V6.04-R1, ratificado en la premisa de V6.05] `Pallets_Objetivo`
representa factibilidad física confirmada -si el motor no llega al 100%, el
problema es de búsqueda/modelado/datos, nunca de inviabilidad del objetivo.
Los repairs LOCALES (Rescue, Repair v2, Exact Local Repair) reparan un
layout ya fragmentado por decisiones tempranas del camino normal -a partir
de cierto punto (BK52, BK53) ese fragmento ya no tiene salida local. Global
Rescue no repara: tira todo el layout y vuelve a armar el CD entero desde N
pallets vacíos, compitiendo TODOS los SKUs y TODOS los pallets a la vez
(sección 5, 8).

[Instrucción explícita de esta sesión, PATCH V6.05 sección 2 y correcciones
del usuario] `AddNoOverlap2D` (OR-Tools CP-SAT, ver `src/exact_repair.py`)
NO se usa acá ni en ningún lado como solver global del pallet -el pallet
real es 3D (apilado, soporte, anti-flotación, jerarquía de categorías,
altura, Cajas por PH) y ese modelo 2D no lo captura. Este módulo no importa
`ortools` en absoluto: reconstruye SIEMPRE con las mismas primitivas
geométricas 3D que ya usa el resto del motor (`_PalletEnConstruccion`,
MaxRects 3D de `packing_columnar.py`, `_cuboide_admite_candidato` de
`packing_bloques.py`) -así toda solución que este módulo produce ya
garantiza, por construcción, soporte real, cero flotación, cero overlap,
jerarquía de categorías y altura dentro del presupuesto: la MISMA garantía
que ya vale para el camino normal, Rescue V6.02 y Repair V6.04. La
validación final (`validar_pallet_v5`) se corre igual, como red de
seguridad, no como el mecanismo que produce validez.

No reemplaza ninguna capa anterior -pipeline completo (sin cambios en las
capas previas):

    baseline -> Rescue V6.02 -> Repair V6.04 -> Exact Local Repair
    -> Global Rescue V6.05 (este módulo)

[Fase 1 de V6.05, alcance de este commit] Implementa el motor completo
(Beam Search, MRV global, candidatos multi-pallet, lotes parciales,
simetría/transposition table, poda segura, multi-start determinista,
timeout) y se verifica con tests SINTÉTICOS (`tests/test_global_rescue.py`).
Todavía NO se conecta a `packing_bloques._empacar_n_pallets` ni se corre
contra BK52/BK53 reales -eso es la Fase 2, una vez que esta arquitectura
quede revisada.

[Fase 1.1] Corrigió la poda/MRV/score para nunca matar un estado ni elegir
un SKU por un único SKU en 0 candidatos, ya que en 3D otro SKU podría
crearle soporte/espacio después -y corrigió, además, dos bugs reales
encontrados probando esa corrección (ver `_beam_search`, `_score_estado`).

[Fase 1.2] Formalizó con un test sobre el motor real
(`test_monotonicidad_candidatos_no_aumentan_al_colocar_otro_sku`) que, bajo
el subconjunto de reglas que este módulo reutiliza hoy, esa preocupación de
Fase 1.1 no aplica: un SKU nunca gana candidatos por la colocación de OTRO
SKU en un pallet que arrancó vacío. Con la propiedad confirmada, restauró
la poda por SKU individual (`_es_estado_inviable`) y reordenó `_score_
estado` para priorizar preservar opciones futuras (deuda de escasez) sobre
cajas colocadas -y descubrió, verificando con `packing_columnar`, que los
cuboides libres SÍ pueden depender del orden de colocación aunque las
torres finales sean idénticas, así que `_clave_estado` (transposition
table) ahora incluye también una firma de los libres, además de la demanda
pendiente explícita por seguridad redundante."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import config
from models import PalletV5
from src.global_rescue_structural import (
    CacheEstructural,
    contar_candidatos_estructurales,
    existe_candidato_estructural,
    generar_candidatos_estructurales,
)
from src.packing_columnar import _PalletEnConstruccion
from src.rescue_solver import (
    MAX_CANDIDATOS_PARA_SCARCITY,
    _contar_candidatos_factibles,
    _footprint_maximo,
    _generar_batch_sizes,
)
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_pallet_v5

TOL = 1e-6

# [PATCH V6.10, secciones 2-3 -"Beam por Estrategia"] Única fuente de
# verdad para el ancho de haz de CADA reinicio del multi-start -antes
# (V6.05-V6.09) la regla vivía duplicada e implícita en el propio loop de
# `global_rescue()` ("intento==0 -> 32, resto -> 64"), sin espacio para
# que una estrategia pidiera un valor distinto a las demás. Evidencia
# V6.09-S1 (BK52, corrida real vía harness): `footprint`=32 y
# `altura_critica`=64 seguían siendo los mejores valores para esos dos
# reinicios (subir su beam no cambiaba su resultado); `demanda`=128 sí
# marcó la diferencia -pasó de 101 (mismo tope que V6.08) a 114/114,
# dentro del presupuesto compartido de 180s (165.179s medidos). Ningún
# otro parámetro (TOP_K, score, MRV, batch, Zero-Only Structural, Critical
# Lookahead, poda, transposition, timeout, estrategias del multi-start)
# cambia en este parche -ver sección 13, "primero generalizar, después
# optimizar".
GLOBAL_BEAM_WIDTH_BY_STRATEGY: dict[str, int] = {
    "footprint": 32,
    "altura_critica": 64,
    "demanda": 128,
}
# [sección 3] Fallback seguro -mismo valor "duro" que V6.05-V6.09 ya usaban
# para cualquier reinicio que no fuera el primero. Nunca debería activarse
# con `GLOBAL_MULTI_START_ESTRATEGIAS` actual (las 3 claves de arriba lo
# cubren), pero evita un `KeyError` silencioso si se agrega una estrategia
# nueva sin actualizar el mapa.
GLOBAL_BEAM_WIDTH_FALLBACK = 64
# [sección 9] Candidatos DIVERSOS (no casi-idénticos) por SKU elegido en
# cada nivel del árbol.
GLOBAL_BRANCH_TOP_K = 5
# [sección 18] Presupuesto de reloj por CD problemático -compartido entre
# los hasta 3 reinicios del multi-start (sección 17), no por reinicio.
GLOBAL_RESCUE_TIME_SECONDS = 180.0
# [sección 16] Tope de la transposition table -más allá de esto se sigue
# comparando contra lo ya visto, pero no se registran entradas nuevas.
GLOBAL_VISITED_MAX = 100_000
# [sección 17] Multi-start determinista: hasta 3 reinicios, cada uno con un
# desempate MRV distinto como criterio secundario dominante (sección 7 sigue
# mandando "menor cantidad de candidatos" como criterio 1 SIEMPRE -esto solo
# reordena 2-4). Nombres, no índices, para que quede legible en `stats`.
GLOBAL_MULTI_START_ESTRATEGIAS = ("demanda", "altura_critica", "footprint")
GLOBAL_MULTI_START_MAX = len(GLOBAL_MULTI_START_ESTRATEGIAS)
# [PATCH V6.08, sección 1/3/4/5 -"Zero-Only Structural Rescue"] Hasta V6.07,
# Structural se consultaba con MaxRects <= 1 (0 obligatorio + 1 opcional
# "para diversidad") -V6.07 midió que eso dispara Structural cientos de
# miles de veces (624.774 exists_calls solos) y el resultado quedó PEOR que
# V6.05 sin ningún híbrido (89 contra 101): enriquecer MaxRects=1 no está
# demostrado que ayude, y sí demostrado que cuesta caro y cambia MRV/score
# aunque MaxRects YA tenía salida. V6.08 reduce el trigger a la ÚNICA
# afirmación que SÍ está confirmada con datos reales (Fase 2.1, SKU 15506;
# V6.06/V6.07, SKU 19022): "MaxRects=0 puede ser un falso negativo". Con
# MaxRects>=1 el SKU YA tiene salida -Structural no aporta nada a esa
# decisión y consultarlo sería pagar su costo sin necesidad (sección 6 del
# parche: "si Zero-Only sigue sin resolver BK52, el enriquecimiento de
# MaxRects>0 se tratará DESPUÉS como decisión de SEARCH, no como corrección
# de validez" -no en esta versión).
STRUCTURAL_ZERO_RESCUE_MAXRECTS_MAXIMO = 0
# [PATCH V6.09, secciones 1/6 -"Critical Precedence Lookahead"] Tope de
# víctimas a probar por evento de lookahead -evidencia S3: MRV eligió
# 22351 (rank 1, 2 candidatos) sobre 22353/23510 (rank 2-3, 4 candidatos
# cada uno) y ese ÚNICO candidato de 22351 mató a los DOS SKUs restantes a
# la vez (100% de sus hijos normales condenados); forzar 22353 primero, y
# devolver el control al solver normal, llegó a 114/114. El mecanismo es
# GENERAL (nunca referencia SKUs concretos) -este tope solo evita analizar
# el CD entero cuando una expansión normal muere por varias víctimas a la
# vez (sección 6: "no analizar todos los SKUs del CD").
CRITICAL_LOOKAHEAD_MAX_VICTIMS = 3


@dataclass
class _EstadoGlobal:
    """[sección 6] Un nodo del árbol de búsqueda: N construcciones (una por
    pallet, con sus propios cuboides libres MaxRects), cuánto se colocó de
    cada SKU por pallet (para los topes de Cajas por PH), la demanda
    pendiente global, y el total colocado. SIEMPRE geométricamente válido
    -se llega acá únicamente vía `_PalletEnConstruccion.colocar`, nunca se
    construye ni se mantiene un estado con overlap/flotación a propósito
    para "corregirlo después" (sección 6: "nunca conservar estados
    inválidos esperando corregirlos luego")."""

    construcciones: list[_PalletEnConstruccion]
    colocados_por_pallet: list[dict[str, int]]
    pendientes: dict[str, int]
    cajas_colocadas: int = 0


# [PATCH V6.12-2A2 -"Structural Cache Propagation"] Un `_EstadoGlobal` NUNCA
# se muta después de construido: los únicos 2 sitios de todo este archivo que
# asignan `.pendientes[...]`/`.colocados_por_pallet[...]`/`.cajas_colocadas`
# son las 2 líneas de `_expandir_sku_en_estado` que colocan la torre de un
# `hijo` recién clonado, ANTES de agregarlo a `hijos` y devolverlo (grep
# exhaustivo confirmado) -así que, una vez que un `estado` sale de esa
# función, su geometría queda congelada para siempre. Eso hace SEGURO atar
# una `CacheEstructural` directamente al objeto Python vía un atributo
# dinámico (`_EstadoGlobal` es un `@dataclass` sin `__slots__`): su lifetime
# es EXACTAMENTE el del objeto -nunca se hereda al clonar (un `hijo` es una
# instancia nueva, sin el atributo) y nunca se puede "filtrar" entre un
# `id()` reciclado y un objeto distinto (a diferencia de un diccionario
# externo keyed por `id()`, acá no hace falta ninguna protección de
# reciclaje: el atributo vive y muere con el objeto en sí).
_ATRIBUTO_CACHE_ESTRUCTURAL = "_cache_estructural_2a2"


def _cache_estructural_de_estado(estado: "_EstadoGlobal") -> CacheEstructural | None:
    """[PATCH V6.12-2A2] Lee la cache YA asociada a ESTE objeto `estado`
    exacto, si la hay -nunca crea una. `None` si este estado todavía no
    tuvo ninguna consulta Structural (o si es un estado recién clonado,
    que nunca hereda la del padre)."""
    return getattr(estado, _ATRIBUTO_CACHE_ESTRUCTURAL, None)


def _asociar_cache_estructural(estado: "_EstadoGlobal", cache: CacheEstructural) -> None:
    """[PATCH V6.12-2A2] Asocia esta cache a ESTE objeto `estado` exacto
    -válido para toda su vida útil (nunca se muta después de construido,
    ver comentario de arriba). Sobreescribir con la misma instancia (caso
    común: ya estaba asociada) es un no-op observable."""
    setattr(estado, _ATRIBUTO_CACHE_ESTRUCTURAL, cache)


def _clonar_construccion(pc: _PalletEnConstruccion) -> _PalletEnConstruccion:
    """Copia independiente de una `_PalletEnConstruccion` -necesaria porque
    `.colocar()` muta `self.libres` y `self.pallet.torres` in-place, y el
    beam search necesita ramificar el MISMO estado padre en varios hijos
    sin que uno pise al otro. Los elementos de `torres`/`libres` (Torre,
    _CuboidLibre) nunca se mutan in-place en ningún punto del motor una vez
    creados -siempre se reemplazan por instancias nuevas- así que copiar
    las LISTAS (no cada elemento) alcanza para el aislamiento real."""
    pallet_original = pc.pallet
    pallet_nuevo = PalletV5(
        id=pallet_original.id, cd=pallet_original.cd, torres=list(pallet_original.torres),
        altura_final=pallet_original.altura_final, peso_estimado=pallet_original.peso_estimado,
        ocupacion_xy=pallet_original.ocupacion_xy, volumen_utilizado=pallet_original.volumen_utilizado,
        metadata=dict(pallet_original.metadata),
    )
    return _PalletEnConstruccion(pallet=pallet_nuevo, libres=list(pc.libres))


def _clonar_estado(estado: _EstadoGlobal) -> _EstadoGlobal:
    return _EstadoGlobal(
        construcciones=[_clonar_construccion(pc) for pc in estado.construcciones],
        colocados_por_pallet=[dict(d) for d in estado.colocados_por_pallet],
        pendientes=dict(estado.pendientes),
        cajas_colocadas=estado.cajas_colocadas,
    )


def _beam_width_para_estrategia(estrategia: str) -> int:
    """[PATCH V6.10, sección 3] Única fuente de verdad para el ancho de
    haz de un reinicio -reemplaza la regla anterior, implícita en el loop
    de `global_rescue()` ("intento==0 -> 32, resto -> 64"), que no podía
    darle a una estrategia un valor propio. `GLOBAL_BEAM_WIDTH_FALLBACK`
    cubre cualquier estrategia no listada en `GLOBAL_BEAM_WIDTH_BY_
    STRATEGY` -nunca debería activarse con `GLOBAL_MULTI_START_
    ESTRATEGIAS` actual, es una red de seguridad, no un caso esperado."""
    return GLOBAL_BEAM_WIDTH_BY_STRATEGY.get(estrategia, GLOBAL_BEAM_WIDTH_FALLBACK)


def _reconstruir_demanda_total(
    pallets: list[PalletV5], sin_colocar: dict[str, int], por_sku: dict[str, list[TorreCandidate]],
) -> dict[str, int]:
    """[sección 5] "Global Rescue recibe demanda completa del CD" -no solo
    lo que quedó sin colocar. Se reconstruye sumando lo que YA está puesto
    en `pallets` (el resultado, ya fragmentado, de baseline+Rescue+Repair+
    Exact) más `sin_colocar` -el llamador no necesita pasar la demanda
    original aparte, este módulo la deriva de lo que ya tiene a mano."""
    total: dict[str, int] = {sku: 0 for sku in por_sku}
    for pallet in pallets:
        for torre in pallet.torres:
            total[torre.sku] = total.get(torre.sku, 0) + torre.cantidad
    for sku, cantidad in sin_colocar.items():
        total[sku] = total.get(sku, 0) + cantidad
    return total


def _crear_estado_inicial(
    n_pallets: int, cd: str, contador: list[int], demanda_total: dict[str, int],
) -> _EstadoGlobal:
    """[sección 5] Exactamente N pallets VACÍOS -no hereda ningún layout
    parcial anterior. IDs nuevos (via `contador`, compartido entre los
    reinicios del multi-start) para no chocar con los pallets del camino
    normal/Rescue/Repair/Exact que el llamador todavía conserva aparte."""
    construcciones: list[_PalletEnConstruccion] = []
    colocados_por_pallet: list[dict[str, int]] = []
    for _ in range(n_pallets):
        contador[0] += 1
        pallet = PalletV5(id=f"PV5-{cd}-GR-{contador[0]:03d}", cd=cd)
        construcciones.append(_PalletEnConstruccion(pallet=pallet))
        colocados_por_pallet.append({})
    pendientes = {sku: cantidad for sku, cantidad in demanda_total.items() if cantidad > 0}
    return _EstadoGlobal(construcciones=construcciones, colocados_por_pallet=colocados_por_pallet, pendientes=pendientes)


def _generar_candidatos_multi_pallet(
    construcciones: list[_PalletEnConstruccion], colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int], sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
) -> list[tuple[float, int, int, float, float, float, TorreCandidate, int]]:
    """[sección 8] TODAS las opciones (pidx, idx_libre, orientación, lote
    máximo) que admiten hoy al menos 1 caja de `sku`, en TODOS los pallets
    a la vez -"para BK53, ambos pallets compiten simultáneamente; no
    repartir primero la demanda entre pallet 1 y pallet 2": acá no se
    elige ninguno todavía, se listan TODAS las combinaciones (pallet,
    cuboide, orientación) admisibles; `_seleccionar_top_k_diverso` es quien
    filtra a un branching factor chico y diverso.

    Devuelve tuplas (sobra_area, pidx, idx_libre, z, x, y, cand, max_lote)
    -sobra/z/x/y se usan solo para ordenar/diversificar, no son parte de la
    decisión final (esa es (pidx, idx_libre, cand, max_lote))."""
    from src.packing_bloques import _cantidad_sin_solape, _capacidad_restante_en_capa, _cuboide_admite_candidato

    tope_capa = capacidad_cama_por_sku.get(sku)
    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
    tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
    pendiente = pendientes.get(sku, 0)
    if pendiente <= 0:
        return []

    opciones: list[tuple[float, int, int, float, float, float, TorreCandidate, int]] = []
    for pidx, pc in enumerate(construcciones):
        ya_en_pallet = colocados_por_pallet[pidx].get(sku, 0)
        if ya_en_pallet >= tope_pallet:
            continue
        pallet = pc.pallet
        for idx_libre, c in enumerate(pc.libres):
            mejor = None
            for cand in por_sku.get(sku, []):
                if not _cuboide_admite_candidato(pallet, c, cand, tope_capa, nivel_sku, nivel_por_sku):
                    continue
                max_lote = min(
                    pendiente, tope_pallet - ya_en_pallet,
                    _capacidad_restante_en_capa(pallet, sku, c.z, tope_capa),
                    int((c.d + TOL) // cand.alto_caja),
                )
                max_lote = _cantidad_sin_solape(pallet, c, cand, max_lote)
                if max_lote <= 0:
                    continue
                sobra = c.w * c.h - cand.largo * cand.ancho
                if mejor is None or sobra < mejor[0]:
                    mejor = (sobra, cand, max_lote)
            if mejor is not None:
                sobra, cand, max_lote = mejor
                opciones.append((sobra, pidx, idx_libre, c.z, c.x, c.y, cand, max_lote))
    return opciones


def _colocar_candidato_estructural(
    pc: _PalletEnConstruccion, cand: TorreCandidate, x: float, y: float, z: float, cantidad: int,
):
    """[PATCH V6.06, sección 7] Placement EXPLÍCITO para un candidato que
    puede NO estar contenido en ningún `_CuboidLibre` único -nunca se
    fuerza dentro de un cuboide padre (prohibido explícitamente por el
    parche). Misma contabilidad que `_PalletEnConstruccion.colocar`
    (altura_final, peso, ocupación XY, volumen), pero con `(x, y, z)`
    explícitos en vez de leerlos de `self.libres[idx_libre]` -no se toca
    `packing_columnar.py` (muchos otros callers usan `.colocar()` tal
    cual, sección 1 del parche: "no reemplazar todo MaxRects").

    `pc.libres` se sigue actualizando con `_actualizar_libres_maxrects`
    como ACELERADOR (sección 7: "mantener los libres MaxRects como
    acelerador pero NO como fuente exclusiva de verdad para futuras
    posiciones") -si esa actualización deja la huella de soporte
    fragmentada en vez de fusionada (mismo patrón ya documentado en Fase
    1.2, orden de fragmentación), el Structural Fallback sigue disponible
    para la SIGUIENTE colocación y puede volver a descubrir una posición
    de unión ahí también -no depende de que `libres` sea perfecto."""
    from src.packing_columnar import _actualizar_libres_maxrects, _area_union_xy

    torre = crear_torre(cand, x=x, y=y, z=z, cantidad=cantidad)
    assert torre.cantidad > 0  # [sección 11] nunca colocar un batch que terminó en 0 cajas reales

    pc.pallet.torres.append(torre)
    pc.pallet.altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in pc.pallet.torres)
    pc.pallet.peso_estimado += torre.peso
    area_ocupada = _area_union_xy(pc.pallet.torres)
    pc.pallet.ocupacion_xy = round(area_ocupada / (config.PALLET_LARGO * config.PALLET_ANCHO), 4)
    pc.pallet.volumen_utilizado = round(sum(t.area_base * t.altura for t in pc.pallet.torres), 2)
    pc.libres = _actualizar_libres_maxrects(pc.libres, x, y, z, torre.largo, torre.ancho, torre.altura)
    return torre


def _generar_candidatos_multi_pallet_hibrido(
    estado: "_EstadoGlobal", sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float | None = None, stats: dict | None = None, cache_estructural: CacheEstructural | None = None,
) -> list[tuple[float, int, int | None, float, float, float, TorreCandidate, int]]:
    """[PATCH V6.06 secciones 3-4-8, PATCH V6.07 sección 2 "Generación"]
    MaxRects (`_generar_candidatos_multi_pallet`, SIN CAMBIOS) + Structural
    Fallback (ahora vía el motor eficiente de `global_rescue_structural.
    py`: streaming, cache, buffer -sección 10), deduplicados.

    `presupuesto=None` (default) -> devuelve exactamente lo mismo que
    `_generar_candidatos_multi_pallet` sola -0% cambio de comportamiento
    para cualquier caller que no pase `presupuesto` (todos los tests de
    Fase 1/1.1/1.2/2.1). El pipeline real (`global_rescue`) SÍ pasa
    `presupuesto` -ahí se activa el híbrido.

    [PATCH V6.07, sección 2] "Generación: uso SOLO para el SKU que
    realmente se expande" -este es exactamente ese punto de entrada,
    llamado UNA vez por nivel del árbol para el sku ya elegido por MRV
    (nunca para todos los pendientes, eso sería `_contar_...` en `_evaluar_
    movimientos_pendientes`).

    [PATCH V6.08, secciones 3-5 -"Zero-Only Structural Rescue"] Trigger:
    Structural SOLO corre si MaxRects dio EXACTAMENTE 0 opciones (`Caso B`
    del parche) -con MaxRects>=1 (`Caso A`) esta función devuelve las
    opciones de MaxRects tal cual, IDÉNTICO a V6.05, sin siquiera llamar al
    motor estructural. V6.07 consultaba Structural también con MaxRects=1
    ("para diversidad") -medido: costaba el 81.5% del presupuesto de 180s
    y terminaba peor que V6.05 sin ningún híbrido (89 contra 101, ver
    reporte V6.07). V6.08 es la integración MÍNIMA que corrige el falso
    cero confirmado (Fase 2.1 SKU 15506; V6.06/V6.07 SKU 19022) sin tocar
    la trayectoria de búsqueda cuando MaxRects YA tenía salida.

    Dedupe (sección 8 V6.06 / sección 15 V6.07, sigue vigente para el Caso
    B): un candidato estructural que coincide con uno de MaxRects en
    `(pidx, x, y, z, orientación)` (redondeado a 2 decimales) NO se cuenta
    dos veces -`batch_size` NO forma parte de esta clave (la cantidad de
    lote se decide DESPUÉS, por spot; el estado final -incluido el batch
    elegido- ya queda deduplicado aparte por la transposition table).
    Métricas separadas (sección 15 V6.07): `structural_candidates_valid_
    before_dedupe` (lo que devolvió el generador, ya deduplicado
    internamente contra sí mismo) vs `structural_candidates_unique_new_vs_
    maxrects` (lo que sobrevive el dedupe contra MaxRects -en Zero-Only
    esto siempre coincide con `valid_before_dedupe`, ya que `opciones`
    -MaxRects- está vacío en el Caso B por definición, nada contra qué
    deduplicar)."""
    opciones = _generar_candidatos_multi_pallet(
        estado.construcciones, estado.colocados_por_pallet, estado.pendientes, sku, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    )
    if presupuesto is None or len(opciones) > STRUCTURAL_ZERO_RESCUE_MAXRECTS_MAXIMO:
        return opciones  # [Caso A] MaxRects ya tiene salida -mismo camino que V6.05, Structural NUNCA se consulta

    # [Caso B] MaxRects == 0 -Zero Rescue.
    # [PATCH V6.12-2A2] Mismo criterio que en `_contar_candidatos_y_registrar`.
    if cache_estructural is None:
        cache_estructural = _cache_estructural_de_estado(estado) or CacheEstructural()
    _asociar_cache_estructural(estado, cache_estructural)
    if stats is not None:
        stats["zero_rescue_generate_calls"] = stats.get("zero_rescue_generate_calls", 0) + 1
    candidatos_estructurales = generar_candidatos_estructurales(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, cache_estructural, stats,
    )
    if stats is not None:
        stats["structural_candidates_valid_before_dedupe"] = (
            stats.get("structural_candidates_valid_before_dedupe", 0) + len(candidatos_estructurales)
        )

    vistos = {
        (pidx, round(x, 2), round(y, 2), round(z, 2), cand.orientacion)
        for _sobra, pidx, _idx_libre, z, x, y, cand, _max_lote in opciones
    }
    opciones_estructurales: list[tuple[float, int, None, float, float, float, TorreCandidate, int]] = []
    for pidx, x, y, z, cand, max_lote in candidatos_estructurales:
        clave = (pidx, round(x, 2), round(y, 2), round(z, 2), cand.orientacion)
        if clave in vistos:
            continue
        vistos.add(clave)
        # [sección 9 V6.06] sobra=-1 -sin cuboide de referencia; se
        # prioriza PRIMERO en `_seleccionar_top_k_diverso` (ordena por
        # sobra ascendente) porque, cuando aparece, es la ÚNICA forma de
        # mover a este sku hoy.
        opciones_estructurales.append((-1.0, pidx, None, z, x, y, cand, max_lote))

    if stats is not None:
        stats["structural_candidates_unique_new_vs_maxrects"] = (
            stats.get("structural_candidates_unique_new_vs_maxrects", 0) + len(opciones_estructurales)
        )
        # [PATCH V6.08, secciones 7-8] `false_zero_maxrects` -definición
        # ÚNICA: MaxRects==0 AND Structural>0 (MaxRects es SIEMPRE 0 acá,
        # Caso B). Nunca se cuenta con MaxRects>=1 -esa rama ya retornó
        # arriba, antes de tocar Structural.
        if opciones_estructurales:
            registro_fz = stats.setdefault("false_zero_maxrects", {})
            registro_fz[sku] = registro_fz.get(sku, 0) + 1
            stats["zero_rescue_successes"] = stats.get("zero_rescue_successes", 0) + 1
        else:
            stats["zero_rescue_failures"] = stats.get("zero_rescue_failures", 0) + 1

    return opciones + opciones_estructurales


def _seleccionar_top_k_diverso(
    opciones: list[tuple[float, int, int | None, float, float, float, TorreCandidate, int]],
    top_k: int = GLOBAL_BRANCH_TOP_K,
) -> list[tuple[int, int | None, float, float, float, TorreCandidate, int]]:
    """[sección 9] Como mucho `top_k` opciones, priorizando menor sobra de
    área (mejor ajuste), pero sin repetir el mismo "bucket" de (pallet,
    franja de Z, región XY, orientación) -"evitar cinco candidatos casi
    idénticos". Si la diversidad deja huecos (pocas opciones realmente
    distintas) se rellena con las siguientes mejores aunque repitan bucket,
    en vez de desperdiciar branching.

    [PATCH V6.06] La selección ahora carga también `(x, y, z)`, no solo
    `idx_libre` -un candidato ESTRUCTURAL (`idx_libre=None`, sección 7 del
    parche) no tiene un `_CuboidLibre` del que `_expandir_estado` pueda
    releer su posición; con `idx_libre` de un `_CuboidLibre` real, `(x,
    y, z)` coincide exactamente con `c.x, c.y, c.z` (sigue siendo
    redundante en ese caso, no cambia nada), pero para uno estructural es
    la ÚNICA fuente de la posición."""
    ordenadas = sorted(opciones, key=lambda o: o[0])
    vistos_bucket: set[tuple] = set()
    seleccion: list[tuple[int, int | None, float, float, float, TorreCandidate, int]] = []
    for _sobra, pidx, idx_libre, z, x, y, cand, max_lote in ordenadas:
        bucket = (pidx, round(z / 10.0), round(x / 20.0), round(y / 20.0), cand.orientacion)
        if bucket in vistos_bucket:
            continue
        vistos_bucket.add(bucket)
        seleccion.append((pidx, idx_libre, x, y, z, cand, max_lote))
        if len(seleccion) >= top_k:
            return seleccion

    vistos_pos = {(pidx, idx_libre, cand.orientacion) for pidx, idx_libre, _x, _y, _z, cand, _ in seleccion}
    for _sobra, pidx, idx_libre, z, x, y, cand, max_lote in ordenadas:
        clave = (pidx, idx_libre, cand.orientacion)
        if clave in vistos_pos:
            continue
        vistos_pos.add(clave)
        seleccion.append((pidx, idx_libre, x, y, z, cand, max_lote))
        if len(seleccion) >= top_k:
            break
    return seleccion


def _contar_candidatos_y_registrar(
    estado: _EstadoGlobal, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    stats: dict | None, max_count: int = MAX_CANDIDATOS_PARA_SCARCITY, presupuesto: float | None = None,
    cache_estructural: CacheEstructural | None = None,
) -> int:
    """[sección 24] Envoltorio de `_contar_candidatos_factibles` (ya de por
    sí multi-pallet -recorre TODAS las `construcciones`) que además
    registra, si se pasa `stats`, el mínimo de candidatos vistos y cuántas
    veces este SKU llegó a 0 candidatos -instrumentación pedida por
    sección 24. `max_count` distinto (1 en la poda, sección 24 en el score)
    comparten el mismo contador `min_candidates_seen`: es un mínimo real
    entre cortes distintos, sigue siendo válido como señal de "qué tan
    ajustado estuvo este SKU en algún punto de la búsqueda".

    [PATCH V6.08, secciones 1/3/4 -"Zero-Only Structural Rescue"]
    `presupuesto=None` (default) -> comportamiento IDÉNTICO a Fase 2.1
    (solo MaxRects, ningún test existente que no pase `presupuesto` ve
    ningún cambio). Con `presupuesto` (el pipeline real lo pasa siempre),
    Structural SOLO se consulta si el conteo MaxRects dio EXACTAMENTE 0
    (`STRUCTURAL_ZERO_RESCUE_MAXRECTS_MAXIMO`) -con MaxRects>=1 el sku YA
    tiene salida, y esta función devuelve ese conteo tal cual, sin llamar
    a Structural (sección 4: "MaxRects >= 1 -> usar exclusivamente el
    conteo MaxRects... NO consultar Structural"). Esto vale tanto para la
    poda (`max_count=1`, sección 3) como para MRV/score (`max_count=4`,
    sección 4) -mismo trigger, mismo umbral, la ÚNICA diferencia entre
    ambos usos es a qué API de `global_rescue_structural.py` se enruta
    (ver abajo). El resultado HÍBRIDO (MaxRects + Zero Rescue cuando
    aplica) es el único número que se registra en `min_candidates_seen`/
    `veces_en_0_candidates`.

    [PATCH V6.07, sección 9] `cache_estructural=None` (default) -> se crea
    un cache DESCARTABLE de un solo uso (sin reaprovechamiento entre
    llamadas); el pipeline real (`_expandir_estado`) pasa un cache
    COMPARTIDO para esta llamada Y la generación posterior del sku que
    termine eligiéndose."""
    candidatos_maxrects = _contar_candidatos_factibles(
        estado.construcciones, estado.colocados_por_pallet, sku, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, max_count=max_count,
    )
    candidatos = candidatos_maxrects
    if presupuesto is not None and candidatos_maxrects <= STRUCTURAL_ZERO_RESCUE_MAXRECTS_MAXIMO:
        # [PATCH V6.12-2A2] Si el caller no pasó una cache explícita, busca
        # primero si ESTE `estado` exacto ya tiene una asociada (de una
        # consulta anterior sobre la MISMA geometría, ver `_cache_
        # estructural_de_estado`) antes de crear una descartable -mismo
        # comportamiento si nunca hubo una, cero riesgo si la hay: la
        # asociación es por objeto Python, nunca por geometría "parecida".
        if cache_estructural is None:
            cache_estructural = _cache_estructural_de_estado(estado) or CacheEstructural()
        _asociar_cache_estructural(estado, cache_estructural)
        # [PATCH V6.07, sección 2 -PATCH V6.08 sección 3/4] `max_count ==
        # 1` es exactamente el caso de uso de poda ("Existencia") -se
        # enruta a la API dedicada `existe_candidato_estructural`
        # (instrumentación `structural_exists_calls`/`structural_early_
        # exit_exists` propia), no a `contar_candidatos_estructurales`
        # (MRV/score, "Conteo limitado") -mismo cache compartido, mismo
        # resultado (`contar(limite=1)` y `existe()` son equivalentes en
        # valor), solo cambia a cuál contador de llamadas se atribuye.
        # Ambas rutas SOLO se alcanzan con MaxRects==0 (el `if` de arriba),
        # así que `zero_rescue_exists_calls`/`zero_rescue_count_calls`
        # (sección 7) se incrementan acá, en el único punto donde Zero
        # Rescue realmente se dispara.
        if max_count <= 1:
            if stats is not None:
                stats["zero_rescue_exists_calls"] = stats.get("zero_rescue_exists_calls", 0) + 1
            candidatos_estructurales = 1 if existe_candidato_estructural(
                estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                presupuesto, cache_estructural, stats,
            ) else 0
        else:
            if stats is not None:
                stats["zero_rescue_count_calls"] = stats.get("zero_rescue_count_calls", 0) + 1
            candidatos_estructurales = contar_candidatos_estructurales(
                estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                presupuesto, max(0, max_count - candidatos_maxrects), cache_estructural, stats,
            )
        candidatos = min(max_count, candidatos_maxrects + candidatos_estructurales)
        if stats is not None:
            by_sku = stats.setdefault("zero_rescue_by_sku", {})
            by_sku[sku] = by_sku.get(sku, 0) + 1
            # [PATCH V6.08, sección 7] `zero_rescue_successes`/`_failures` -
            # se registran acá TAMBIÉN (no solo en `_generar_candidatos_
            # multi_pallet_hibrido`) porque poda (`existe_candidato_
            # estructural`, vía `max_count=1`) y MRV (`contar_candidatos_
            # estructurales`) son intentos de Zero Rescue tan reales como
            # la generación -cada API que consulta Structural cuenta su
            # propio éxito/fracaso, a la misma granularidad que ya usan
            # `structural_exists_calls`/`_count_calls`/`_generate_calls`.
            if candidatos_estructurales > 0:
                stats["zero_rescue_successes"] = stats.get("zero_rescue_successes", 0) + 1
            else:
                stats["zero_rescue_failures"] = stats.get("zero_rescue_failures", 0) + 1
            if candidatos_maxrects == 0 and candidatos_estructurales > 0:
                registro_fz = stats.setdefault("false_zero_maxrects", {})
                registro_fz[sku] = registro_fz.get(sku, 0) + 1

    if stats is not None:
        registro = stats["por_sku"].setdefault(sku, {"min_candidates_seen": candidatos, "veces_en_0_candidates": 0})
        registro["min_candidates_seen"] = min(registro["min_candidates_seen"], candidatos)
        if candidatos == 0:
            registro["veces_en_0_candidates"] += 1
            # [Fase 2.1, instrumentación "first_depth_where_each_sku_
            # reaches_zero_candidates" pedida por el usuario] Puramente
            # aditivo -solo se activa si `_beam_search` publicó el
            # diccionario de ESTE reinicio en `stats["_zero_candidates_
            # actual"]`; no cambia `candidatos` ni ningún otro campo ya
            # existente. Se guarda la PRIMERA profundidad (por reinicio)
            # en la que este sku se vio en 0, nunca se sobreescribe.
            zero_ctx = stats.get("_zero_candidates_actual")
            if zero_ctx is not None and sku not in zero_ctx:
                zero_ctx[sku] = stats.get("_depth_actual", 0)
    return candidatos


def _evaluar_movimientos_pendientes(
    estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], stats: dict | None,
    max_count: int = MAX_CANDIDATOS_PARA_SCARCITY, presupuesto: float | None = None,
    cache_estructural: CacheEstructural | None = None,
) -> dict[str, int]:
    """[Fase 1.1, corrección del punto 1/2/3 del usuario] Candidatos
    factibles HOY para cada SKU con demanda pendiente -única fuente de
    verdad compartida por `_ordenar_mrv`, `_score_estado` y `_es_estado_
    inviable`, para que las tres piezas vean SIEMPRE el mismo número
    (antes cada una lo recalculaba por separado, con riesgo de decisiones
    inconsistentes entre sí). [PATCH V6.06] `presupuesto` se reenvía tal
    cual a `_contar_candidatos_y_registrar` -`None` (default) mantiene el
    comportamiento MaxRects-only de Fase 2.1 sin cambios. [PATCH V6.07]
    `cache_estructural` también se reenvía -así los `MAX_CANDIDATOS_PARA_
    SCARCITY` pendientes de ESTE estado comparten un único cache."""
    return {
        sku: _contar_candidatos_y_registrar(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, max_count,
            presupuesto, cache_estructural,
        )
        for sku, cantidad in estado.pendientes.items() if cantidad > 0
    }


def _ordenar_mrv(
    skus: list[str], estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    estrategia: str, stats: dict | None, presupuesto: float | None = None,
    cache_estructural: CacheEstructural | None = None,
) -> list[str]:
    """[sección 7, CORREGIDO Fase 1.1] Most-Constrained global, pero SOLO
    entre SKUs con `candidatos_actuales > 0` -en un problema 3D, colocar
    OTRO sku puede crear soporte/espacio nuevo para uno que hoy tiene 0
    candidatos, así que un SKU en 0 nunca se elige (no puede producir
    movimiento) pero tampoco se descarta: queda "deferred", al FINAL del
    orden devuelto, para reevaluarse en la próxima llamada (tras la
    siguiente colocación). Entre los disponibles (candidatos>0): 1) menor
    cantidad de candidatos factibles (SIEMPRE el criterio dominante), 2-4)
    footprint / restricción vertical / demanda pendiente según `estrategia`
    (sección 17), 5) menos orientaciones. [PATCH V6.06, sección 9] Con
    `presupuesto`, `movimientos` ya es HÍBRIDO (MaxRects ∪ Structural) -un
    SKU con MaxRects=0 pero Structural>0 llega acá con `factibles>0`, así
    que MRV lo trata como disponible, no como "deferred". [PATCH V6.07]
    `cache_estructural` se reenvía tal cual -ver `_expandir_estado`."""
    movimientos = _evaluar_movimientos_pendientes(
        estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats,
        presupuesto=presupuesto, cache_estructural=cache_estructural,
    )
    if stats is not None:
        diferidos = sum(1 for sku in skus if movimientos.get(sku, 0) <= 0)
        stats["max_deferred_skus"] = max(stats.get("max_deferred_skus", 0), diferidos)

    def clave(sku: str) -> tuple:
        candidatas = por_sku.get(sku, [])
        factibles = movimientos.get(sku, 0)
        diferido = 1 if factibles <= 0 else 0  # [Fase 1.1] deferred siempre al final, nunca elegido
        footprint = _footprint_maximo(candidatas)
        restriccion_vertical = min((c.max_cajas_verticales for c in candidatas), default=0)
        pendiente = estado.pendientes.get(sku, 0)
        num_orientaciones = len({c.orientacion for c in candidatas})

        # [sección 17] "restricción vertical" = menor max_cajas_verticales
        # primero (más restringido); footprint y demanda ascienden en
        # sentido contrario (mayor primero) -se niegan para que "sorted"
        # (ascendente) siga tratando "primero" como "menor clave".
        secundarios = {
            "footprint": -footprint,
            "altura_critica": restriccion_vertical,
            "demanda": -pendiente,
        }
        orden_secundario = [secundarios[estrategia]]
        orden_secundario += [valor for clave_sec, valor in secundarios.items() if clave_sec != estrategia]

        return (diferido, factibles, *orden_secundario, num_orientaciones)

    return sorted(skus, key=clave)


def _expandir_estado(
    estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], estrategia: str, stats: dict | None,
    presupuesto: float | None = None,
) -> list[_EstadoGlobal]:
    """[secciones 7, 8, 9, 10] Un paso del árbol: elige el SKU más
    restringido (MRV global), genera sus candidatos multi-pallet, se queda
    con hasta `GLOBAL_BRANCH_TOP_K` diversos, y por cada uno prueba los
    lotes {1, ceil(max/2), max} (sección 10 -"no comprometer siempre una
    columna completa", mismo `_generar_batch_sizes` de Rescue V6.02). Lista
    vacía = este estado quedó estancado para el SKU más restringido (ningún
    candidato admisible HOY) -el caller decide si lo conserva tal cual o lo
    descarta.

    [PATCH V6.06] `presupuesto=None` (default) -> mismo camino de Fase
    2.1: MRV MaxRects-only, candidatos MaxRects-only (`_generar_
    candidatos_multi_pallet`), colocación vía `.colocar()`/`idx_libre`.
    Con `presupuesto` (pipeline real): MRV híbrido, candidatos híbridos
    (`_generar_candidatos_multi_pallet_hibrido`, sección 3-4), y un
    candidato ESTRUCTURAL (`idx_libre is None`) se coloca por el camino
    explícito `_colocar_candidato_estructural` (sección 7 -nunca forzado
    dentro de un `_CuboidLibre` que no lo contiene).

    [PATCH V6.06, sección 11 -corrección de cajas fantasma] La fuente de
    verdad para `cajas_colocadas`/`pendientes` es SIEMPRE `torre.cantidad`
    -la cantidad REAL que `crear_torre` terminó poniendo (puede ser MENOR
    que `batch` si `cand.max_cajas_verticales`/`cantidad_disponible` lo
    truncan, ver Fase 2.1 `test_bug_estructural_max_cajas_verticales_no_
    se_refleja_en_cajas_colocadas`) -nunca el `batch` solicitado.

    [PATCH V6.07, sección 8] `cache_estructural` se crea UNA vez acá -por
    cada expansión de ESTE `estado` padre- y se comparte entre `_ordenar_
    mrv` (que consulta count() para TODOS los pendientes, incluido el sku
    que termine eligiéndose) y `_generar_candidatos_multi_pallet_hibrido`
    (que después pide generate() para ESE mismo sku) -exactamente el reuso
    "exists/count -> expansion" pedido en la sección 9 del parche: si MRV
    ya avanzó el iterador estructural de este sku, generar() reutiliza ese
    trabajo en vez de recomputar desde cero."""
    pendientes_criticos = [sku for sku, cantidad in estado.pendientes.items() if cantidad > 0]
    if not pendientes_criticos:
        return []

    # [PATCH V6.12-2A2] Este `estado` (el padre a expandir) puede YA tener
    # una cache asociada -por ejemplo, si en la profundidad anterior ya se
    # evaluó su viabilidad/score (`_beam_search`, más abajo) antes de
    # entrar a la frontera- reusarla en vez de crear una nueva descartable.
    cache_estructural = (_cache_estructural_de_estado(estado) or CacheEstructural()) if presupuesto is not None else None
    if cache_estructural is not None:
        _asociar_cache_estructural(estado, cache_estructural)

    orden = _ordenar_mrv(
        pendientes_criticos, estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        estrategia, stats, presupuesto, cache_estructural,
    )
    sku = orden[0]

    hijos = _expandir_sku_en_estado(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
        cache_estructural,
    )
    if not hijos:
        return []

    # [PATCH V6.09, secciones 1-3 -"Critical Precedence Lookahead"] Solo en
    # modo híbrido (`presupuesto is not None`, igual que Zero-Only
    # Structural -sección 2: "no aumentar beam, no cambiar MRV normal").
    # Fase 1/1.1/1.2/2.1 (sin `presupuesto`) quedan bit-a-bit sin cambios.
    if presupuesto is not None:
        hijos = _critical_precedence_lookahead(
            estado, sku, hijos, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            presupuesto, stats, cache_estructural,
        )
    return hijos


def _expandir_sku_en_estado(
    estado: _EstadoGlobal, sku: str, por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float | None, stats: dict | None, cache_estructural: CacheEstructural | None,
) -> list[_EstadoGlobal]:
    """[PATCH V6.09, sección 5 -extraído SIN cambios de comportamiento del
    cuerpo que `_expandir_estado` ya usaba para expandir el sku elegido por
    MRV] Candidatos híbridos + TOP_K diverso + lotes + placement, para UN
    sku ya decidido -mismo generador de candidatos, mismo TOP_K, mismo
    batch que usa la expansión normal. Compartido por dos llamadores: la
    expansión normal (`sku` = elegido por MRV) y Critical Precedence
    Lookahead (`sku` = víctima -sección 5 del parche: "usando exactamente
    el candidate generator productivo... No inventar un generador
    especial")."""
    opciones = _generar_candidatos_multi_pallet_hibrido(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, stats, cache_estructural,
    )
    if stats is not None:
        stats["raw_candidates_generados"] += len(opciones)
    if not opciones:
        return []

    seleccion = _seleccionar_top_k_diverso(opciones, GLOBAL_BRANCH_TOP_K)
    if stats is not None:
        stats["candidates_retenidos_top_k"] += len(seleccion)
    hijos: list[_EstadoGlobal] = []
    for pidx, idx_libre, x, y, z, cand, max_lote in seleccion:
        for batch in _generar_batch_sizes(max_lote):
            hijo = _clonar_estado(estado)
            # [PATCH V6.08, sección 5] `candidate_source` -`idx_libre is
            # None` es exactamente la marca que ya usa `_generar_
            # candidatos_multi_pallet_hibrido` para un candidato del Caso B
            # (Zero Rescue); se traduce acá a la fuente elegida para ESTE
            # placement concreto, instrumentada en `_beam_search` (sección
            # 11: `placements_from_maxrects`/`placements_from_structural_
            # zero_rescue`, `structural_rescues_used` por sku).
            if idx_libre is None:
                torre = _colocar_candidato_estructural(hijo.construcciones[pidx], cand, x, y, z, batch)
                candidate_source = "STRUCTURAL_ZERO_RESCUE"
            else:
                torre = hijo.construcciones[pidx].colocar(cand, batch, idx_libre)
                candidate_source = "MAXRECTS"
            cantidad_real = torre.cantidad  # [sección 11] fuente de verdad, nunca `batch`
            if cantidad_real <= 0:
                continue  # defensivo -no debería pasar (ver assert en _colocar_candidato_estructural)
            hijo.pendientes[sku] = hijo.pendientes.get(sku, 0) - cantidad_real
            hijo.colocados_por_pallet[pidx][sku] = hijo.colocados_por_pallet[pidx].get(sku, 0) + cantidad_real
            hijo.cajas_colocadas += cantidad_real
            if stats is not None:
                if candidate_source == "MAXRECTS":
                    stats["placements_from_maxrects"] = stats.get("placements_from_maxrects", 0) + 1
                else:
                    stats["placements_from_structural_zero_rescue"] = (
                        stats.get("placements_from_structural_zero_rescue", 0) + 1
                    )
                    por_sku_rescates = stats.setdefault("structural_rescues_used", {})
                    por_sku_rescates[sku] = por_sku_rescates.get(sku, 0) + 1
            hijos.append(hijo)
    return hijos


def _critical_precedence_lookahead(
    estado: _EstadoGlobal, sku_s: str, hijos_normales: list[_EstadoGlobal], por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int], nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    presupuesto: float, stats: dict | None, cache_estructural: CacheEstructural | None,
) -> list[_EstadoGlobal]:
    """[PATCH V6.09 -evidencia S3, secciones 0-9] Rescue de UN paso: se
    activa ÚNICAMENTE cuando TODOS los hijos normales de `sku_s` (el SKU
    que MRV ya eligió) quedan permanentemente muertos por OTRO SKU
    pendiente (`sección 9`: nunca por simple escasez -un SKU con pocos
    candidatos, o poca demanda restante, NO dispara esto por sí solo).

    [sección 3, costo] La primera verificación (`¿hay al menos un hijo
    normal vivo?`) corta apenas encuentra uno -en el caso normal (la
    inmensa mayoría de las expansiones de toda la búsqueda) esto cuesta
    UNA llamada extra a `_evaluar_viabilidad` por expansión, nada más. El
    análisis de víctimas (mucho más caro -revisa TODOS los SKUs pendientes
    de TODOS los hijos muertos) solo corre en el caso raro donde ya se
    sabe que la rama normal está 100% condenada.

    [sección 8, anti-loop] Esta función corre UNA vez por llamada a
    `_expandir_estado` (para el `sku_s` de ESA expansión); los hijos
    `victim-first` que genera se devuelven como hijos normales más -en la
    SIGUIENTE profundidad, si a alguno de ellos le toca expandirse, corre
    su propia llamada independiente a `_expandir_estado`/MRV/lookahead,
    sin ningún estado compartido con esta invocación. No hay recursión
    directa ni indirecta dentro de esta función."""
    from src.packing_bloques import _capacidad_instalada

    veredictos: list[tuple[_EstadoGlobal, CacheEstructural]] = []
    algun_viable = False
    for hijo in hijos_normales:
        # [PATCH V6.12-2A2] Cada `hijo` es un objeto recién clonado por
        # `_expandir_sku_en_estado` -en el caso normal esta es su PRIMERA
        # consulta Structural, así que esto casi siempre crea una cache
        # nueva (correcto: nunca hereda la del padre). Pero si este MISMO
        # `hijo` ya fue evaluado antes en esta función (no debería, ver
        # anti-loop del docstring) o va a ser reevaluado más abajo por
        # `_beam_search`, la asociación permite que esa evaluación
        # posterior reutilice el trabajo hecho acá en vez de descartarlo.
        cache_hijo = _cache_estructural_de_estado(hijo) or CacheEstructural()
        _asociar_cache_estructural(hijo, cache_hijo)
        muerto, _sku_causante = _evaluar_viabilidad(
            hijo, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
            None, cache_hijo,
        )
        veredictos.append((hijo, cache_hijo))
        if not muerto:
            algun_viable = True
            break  # [sección 3] al menos un hijo normal vive -> comportamiento existente, sin más costo

    if algun_viable:
        return hijos_normales

    if stats is not None:
        stats["critical_lookahead_calls"] = stats.get("critical_lookahead_calls", 0) + 1

    # [sección 4] TODOS los hijos normales evaluados (siempre son TODOS
    # acá -si hubiera habido uno vivo, ya se hubiera retornado arriba)
    # están muertos -identificar qué SKU(s), distintos de `sku_s`, causan
    # esa muerte en cada uno (`dead_skus`), y con qué frecuencia.
    victim_frequency: dict[str, int] = {}
    for hijo, cache_hijo in veredictos:
        for sku_v, cantidad in hijo.pendientes.items():
            if cantidad <= 0 or sku_v == sku_s:
                continue
            candidatos = _contar_candidatos_y_registrar(
                hijo, sku_v, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats,
                max_count=1, presupuesto=presupuesto, cache_estructural=cache_hijo,
            )
            if candidatos > 0:
                continue
            capacidad_residual = sum(_capacidad_instalada(pc.pallet, sku_v, presupuesto) for pc in hijo.construcciones)
            if capacidad_residual <= 0:
                victim_frequency[sku_v] = victim_frequency.get(sku_v, 0) + 1

    if not victim_frequency:
        # Todos los hijos normales mueren, pero no por otro SKU rescatable
        # -son permanentemente inviables por sí mismos (o por `sku_s`
        # mismo, excluido a propósito). No hay víctima que probar primero.
        return hijos_normales

    n_hijos = len(veredictos)

    def _clave_orden(sku_v: str) -> tuple:
        # [sección 6] 1) mayor % de hijos normales que mata (más fuerte
        # primero) 2) menor candidate_count en el PARENT (más restringido)
        # 3) mayor footprint 4) mayor pendiente.
        kill_pct = victim_frequency[sku_v] / n_hijos
        candidate_count_parent = _contar_candidatos_y_registrar(
            estado, sku_v, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, None,
            max_count=4, presupuesto=presupuesto, cache_estructural=cache_estructural,
        )
        footprint = _footprint_maximo(por_sku.get(sku_v, []))
        pendiente = estado.pendientes.get(sku_v, 0)
        return (-kill_pct, candidate_count_parent, -footprint, -pendiente)

    victimas_ordenadas = sorted(victim_frequency, key=_clave_orden)[:CRITICAL_LOOKAHEAD_MAX_VICTIMS]

    hijos_rescate: list[_EstadoGlobal] = []
    for victima in victimas_ordenadas:
        if stats is not None:
            stats["victims_considered"] = stats.get("victims_considered", 0) + 1
        # [sección 5] "expandir V primero, desde el MISMO parent, usando
        # exactamente: candidate generator productivo, Zero-Only
        # Structural, TOP_K existente, batch existente" -reusa el MISMO
        # helper que la expansión normal, sin ningún generador especial.
        hijos_v = _expandir_sku_en_estado(
            estado, victima, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            presupuesto, stats, cache_estructural,
        )
        n_viables = 0
        for hv in hijos_v:
            # [PATCH V6.12-2A2] mismo criterio que `cache_hijo` arriba.
            cache_hv = _cache_estructural_de_estado(hv) or CacheEstructural()
            _asociar_cache_estructural(hv, cache_hv)
            muerto_hv, _ = _evaluar_viabilidad(
                hv, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
                None, cache_hv,
            )
            if not muerto_hv:
                n_viables += 1
        if stats is not None:
            stats["victim_first_children_generated"] = stats.get("victim_first_children_generated", 0) + len(hijos_v)
            stats["victim_first_children_viable"] = stats.get("victim_first_children_viable", 0) + n_viables
            if n_viables > 0:
                # [sección 10] "detectada" = confirmada con evidencia -al
                # menos un hijo victim-first sobrevive la MISMA poda que
                # mataba al 100% de los hijos normales.
                stats["precedence_constraints_detected"] = stats.get("precedence_constraints_detected", 0) + 1
            eventos = stats.setdefault("critical_lookahead_events", [])
            eventos.append({
                "depth": stats.get("_depth_actual", 0), "selected_sku": sku_s, "victim_sku": victima,
                "normal_children": n_hijos, "normal_children_killing_victim": victim_frequency[victima],
                "victim_parent_candidates": _contar_candidatos_y_registrar(
                    estado, victima, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, None,
                    max_count=4, presupuesto=presupuesto, cache_estructural=cache_estructural,
                ),
                "victim_first_children": len(hijos_v), "victim_first_children_viable": n_viables,
            })
        hijos_rescate.extend(hijos_v)

    # [sección 7] Los hijos normales (TODOS muertos, por construcción de
    # esta rama) se conservan en el resultado -no se les da trato especial
    # acá: `_beam_search` ya los saca de la frontera vía la MISMA poda sin
    # cambios (siguen compitiendo por `mejor_estado`, igual que cualquier
    # estado podado hoy). Los victim-first se agregan al mismo pool, sin
    # marca especial (sección 16: "entran al mismo score/transposition/
    # beam que cualquier otro hijo").
    return hijos_normales + hijos_rescate


def _signature_torres(pc: _PalletEnConstruccion) -> tuple:
    """[sección 15] Firma de las torres de UN pallet, independiente de su
    ID -solo lo que físicamente contiene."""
    return tuple(sorted(
        (torre.sku, round(torre.x, 2), round(torre.y, 2), round(torre.z, 2),
         round(torre.largo, 2), round(torre.ancho, 2), torre.cantidad, torre.orientacion)
        for torre in pc.pallet.torres
    ))


def _signature_libres(pc: _PalletEnConstruccion) -> tuple:
    """[Fase 1.2, punto 3 -agregado tras verificar el riesgo señalado por
    el usuario sobre `packing_columnar`] Firma de los cuboides LIBRES de UN
    pallet -ver `_signature_pallet` para por qué esto es obligatorio, no
    opcional."""
    return tuple(sorted(
        (round(c.x, 2), round(c.y, 2), round(c.z, 2), round(c.w, 2), round(c.h, 2), round(c.d, 2))
        for c in pc.libres
    ))


def _signature_pallet(pc: _PalletEnConstruccion) -> tuple:
    """[sección 15, EXTENDIDO Fase 1.2] `(torres, libres)` de UN pallet.

    [Punto 3 -hallazgo real, verificado directamente sobre `packing_
    columnar._actualizar_libres_maxrects`, no solo argumentado] El usuario
    preguntó si dos estados con las MISMAS torres finales, pero puestas en
    ÓRDENES distintos, pueden terminar con conjuntos DISTINTOS de cuboides
    libres. Respuesta: SÍ pueden -MaxRects con partición+poda incremental
    no siempre converge a la misma descomposición maximal del espacio libre
    cuando la región libre resultante admite más de una descomposición
    válida (probado con una búsqueda exhaustiva sobre las 24 permutaciones
    de colocar 4 cajas fijas: 12 órdenes terminan con 10 cuboides libres,
    los otros 12 con 9 -mismas torres, MISMO volumen libre total, pero
    partido distinto). Concretamente, una región de 40x20 queda como UN
    solo cuboide en un orden y como DOS cuboides de 40x15 y 40x5 en otro
    -un candidato que necesite ancho=20 tiene sitio en el primer caso y NO
    en el segundo, aunque las torres ya puestas sean idénticas (ver
    `tests/test_global_rescue.py::
    test_transposition_libres_dependen_del_orden_de_colocacion`).

    Antes de este fix, `_clave_estado` solo miraba torres -así que estos
    dos estados (mismas torres, futuros DISTINTOS) se habrían tratado como
    el MISMO nodo en `visited`, y la transposition table podría haber
    descartado el que preservaba más candidatos futuros como si fuera un
    duplicado exacto del otro. Ahora la firma de cada pallet incluye
    también sus cuboides libres -dos estados con torres idénticas pero
    libres distintos ya NO son la misma clave."""
    return (_signature_torres(pc), _signature_libres(pc))


def _clave_estado(estado: _EstadoGlobal) -> tuple:
    """[sección 15, EXTENDIDO Fase 1.2 -contenido exacto de la clave
    canónica de transposition table]:

    `(firmas_pallets, firma_pendientes)`.

    `firmas_pallets` = `_signature_pallet` (torres + libres, ver ahí) de
    CADA pallet, ordenadas ENTRE SÍ para que intercambiar pallet 1 y
    pallet 2 dé la MISMA clave (sección 15, simetría -sigue verificado por
    `test_clave_estado_es_invariante_al_orden_de_los_pallets`).

    `firma_pendientes` = [Fase 1.2, punto 4 -pedido explícito del usuario:
    "prefiero redundancia segura a una equivalencia incorrecta"] tupla
    ORDENADA de `(sku, cantidad_pendiente)` para TODOS los SKUs en
    `estado.pendientes`. Fase 1.1 argumentaba que esto era derivable sin
    ambigüedad de las firmas de pallet más la demanda total fija de la
    corrida, y ESO sigue siendo cierto dentro de una única llamada a
    `global_rescue` -pero derivable-en-teoría no es lo mismo que
    protegido-en-el-código: nada en `_clave_estado` impedía, por ejemplo,
    reutilizar la tabla `visited` entre corridas con demanda total
    distinta, o pasar un estado con `pendientes` inconsistente con sus
    torres. Incluir `pendientes` explícitamente es redundante HOY (mismo
    resultado que antes en todos los tests existentes) pero cierra esa
    puerta sin costo real -ver `tests/test_global_rescue.py::
    test_transposition_misma_geometria_distinta_demanda_no_es_equivalente`.

    Se usa la TUPLA completa como key de `visited` directamente, nunca
    `hash(...)` de ella -así el dict compara por IGUALDAD EXACTA de
    contenido en cualquier colisión de hash interno (Python siempre
    verifica `==` antes de considerar dos keys iguales cuando compara dos
    tuplas; con un `int` como key ese chequeo de igualdad ya no existe)."""
    firmas_pallets = tuple(sorted(_signature_pallet(pc) for pc in estado.construcciones))
    firma_pendientes = tuple(sorted(estado.pendientes.items()))
    return (firmas_pallets, firma_pendientes)


def _score_estado(
    estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], stats: dict | None,
    presupuesto: float | None = None, cache_estructural: CacheEstructural | None = None,
) -> tuple:
    """[sección 12, RE-ordenado Fase 1.2] Orden final: 1) MENOR deuda de
    escasez -dominante-, 2) más cajas colocadas, 3) más SKUs completos, 4)
    menos fragmentación, 5) menor altura máxima.

    [Por qué la escasez vuelve a mandar sobre las cajas colocadas] Con la
    poda por SKU individual restaurada (Fase 1.2, `_es_estado_inviable`),
    cualquier estado que SIGUE VIVO en el beam todavía puede, en principio,
    llegar al 100% -pero "puede en principio" no es lo mismo que "el score
    lo va a guiar ahí": el corte barato de la poda (`max_count=1`) no
    detecta que una rama se está quedando SIN opciones para un SKU
    escaso hasta que llega literalmente a 0 -para entonces beam width ya
    se gastó. Exactamente el defecto que motivó Global Rescue en primer
    lugar (Rescue V6.02/Repair V6.04 tendían a colocar muchas cajas rápido
    y fragmentar el espacio de las SKUs difíciles) reaparecería acá si
    `cajas_colocadas` mandara: un estado que agarra cajas fáciles temprano
    y de paso reduce a 1 los candidatos de un SKU escaso le ganaría a un
    estado más conservador que preserva esos candidatos, aunque el segundo
    sea el único que realmente llega al 100% (ver `test_score_prioriza_
    preservar_escasez_sobre_mas_cajas_colocadas_temprano`). `deuda_de_
    escasez` sigue calculándose SOLO sobre SKUs actualmente colocables
    (candidatos>0, Fase 1.1 punto 3) -un SKU ya en 0 candidatos pero vivo
    (con capacidad instalada residual, no podado) no suma deuda; ese caso
    ya lo cubre `_es_estado_inviable`, no el score.

    [Qué se retira] El flag binario `estado_sin_movimientos_factibles`
    (Fase 1.1) se elimina del tuple -con la poda por SKU restaurada, un
    estado vivo por definición tiene siempre al menos un SKU pendiente con
    candidato o capacidad residual, así que el caso que ese flag distinguía
    ("nadie se puede mover hoy") ya no aporta información nueva sobre
    estados vivos; `deuda_de_escasez` es ahora la única señal de
    "qué tan cerca de la pared está esta rama"."""
    pendientes_con_demanda = {sku: cantidad for sku, cantidad in estado.pendientes.items() if cantidad > 0}
    movimientos = _evaluar_movimientos_pendientes(
        estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats,
        presupuesto=presupuesto, cache_estructural=cache_estructural,
    )

    deuda_de_escasez = sum(
        (MAX_CANDIDATOS_PARA_SCARCITY - candidatos) * pendientes_con_demanda[sku]
        for sku, candidatos in movimientos.items() if candidatos > 0
    )

    skus_completos = sum(1 for sku in por_sku if estado.pendientes.get(sku, 0) <= 0)
    fragmentacion = sum(len(pc.libres) for pc in estado.construcciones)
    altura_max = max((pc.pallet.altura_final for pc in estado.construcciones), default=0.0)

    return (
        -deuda_de_escasez,
        estado.cajas_colocadas,
        skus_completos,
        -fragmentacion,
        -altura_max,
    )


def _evaluar_viabilidad(
    estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], presupuesto: float, stats: dict | None,
    oracle_sampler=None, cache_estructural: CacheEstructural | None = None,
) -> tuple[bool, str | None]:
    """[Fase 2.1, extraído de `_es_estado_inviable` SIN cambiar su lógica -
    pedido de instrumentación del usuario: "prune_by_sku"] Misma regla
    exacta de poda (ver docstring de `_es_estado_inviable`, que ahora es un
    envoltorio de una línea sobre esta función), pero devuelve además el
    SKU que causó la poda (o `None` si el estado sigue vivo) -para que
    `_beam_search` pueda instrumentar POR QUÉ sku se podó cada rama, sin
    tocar el resultado booleano que ya usan todos los tests existentes.

    [Fase 2.1, punto 4 del pedido -"MaxRects vs oráculo"] `oracle_sampler`
    es un hook de diagnóstico OPCIONAL (default `None`, el único valor que
    usa el pipeline real y CUALQUIER test existente -cero cambio de
    comportamiento ni de costo cuando no se pasa). Si se pasa, se llama
    UNA vez por cada SKU que esta función esté a punto de declarar
    "permanentemente estancado" (justo antes del `return True, sku`), como
    `oracle_sampler(estado, sku, por_sku, capacidad_cama_por_sku,
    nivel_por_sku, tope_pallet_por_sku, presupuesto)` -es responsabilidad
    del CALLER decidir cuántas muestras tomar y dónde guardarlas (ver
    `src/global_rescue_oracle.py`, que es quien de verdad implementa la
    comparación); este módulo no sabe nada de oráculos ni de muestreo, solo
    ofrece el punto de enganche exacto donde MaxRects decidió podar.

    [PATCH V6.06, sección 10] `candidatos` ya es HÍBRIDO (MaxRects ∪
    Structural Fallback, ver `_contar_candidatos_y_registrar`) -la poda
    NUNCA se decide ya con MaxRects=0 a solas: si Structural encuentra >0,
    este SKU pasa el `continue` de arriba igual que si MaxRects ya hubiera
    dado >0. Esto corrige directamente la poda falsa confirmada en Fase
    2.1 (SKU 15506, 2/60 en la auditoría de BK52)."""
    from src.packing_bloques import _capacidad_instalada

    pendientes_con_demanda = [(sku, cantidad) for sku, cantidad in estado.pendientes.items() if cantidad > 0]
    if not pendientes_con_demanda:
        return False, None

    for sku, _cantidad in pendientes_con_demanda:
        candidatos = _contar_candidatos_y_registrar(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats,
            max_count=1, presupuesto=presupuesto, cache_estructural=cache_estructural,
        )
        if candidatos > 0:
            continue  # este SKU sí puede moverse hoy (MaxRects o, si aplica, Structural Fallback)
        capacidad_residual = sum(_capacidad_instalada(pc.pallet, sku, presupuesto) for pc in estado.construcciones)
        if capacidad_residual <= 0:
            if oracle_sampler is not None:
                oracle_sampler(
                    estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto,
                )
            return True, sku  # este SKU nunca va a poder completarse en esta rama -> la rama entera se poda
    return False, None  # ningún SKU pendiente está permanentemente estancado


def _es_estado_inviable(
    estado: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], presupuesto: float, stats: dict | None,
) -> bool:
    """[sección 14, RESTAURADO Fase 1.2 -corrección sobre la corrección de
    Fase 1.1] Poda por SKU INDIVIDUAL: basta que UN SOLO SKU pendiente
    tenga (a) 0 candidatos nuevos factibles hoy (corte barato,
    `max_count=1`) Y (b) 0 capacidad instalada residual en columnas propias
    ya puestas (`_capacidad_instalada`) para declarar TODO el estado
    muerto -Global Rescue busca específicamente el 100% de la demanda
    (`Pallets_Objetivo` es factibilidad física confirmada, ADDENDUM
    V6.04-R1), así que una rama que ya nunca puede completar UN SKU nunca
    puede completar el CD entero, sin importar qué tan bien le vaya a los
    demás SKUs en esa misma rama.

    Fase 1.1 había relajado esto a "TODOS los SKUs pendientes deben estar
    estancados a la vez", por una preocupación legítima: en 3D, colocar un
    SKU podría crear soporte/espacio nuevo para otro que hoy está en 0
    candidatos. Se pidió formalizar esa propiedad con un test antes de
    volver a endurecer la poda (`tests/test_global_rescue.py::
    test_monotonicidad_candidatos_no_aumentan_al_colocar_otro_sku`) -el
    resultado, verificado sobre el motor REAL (no solo argumentado): el
    CONTEO crudo de candidatos (0..4, el que usan MRV/score) puede subir o
    bajar con la fragmentación -eso NO es lo que la poda necesita. Lo que
    SÍ es cierto, y es lo único que la poda usa: si NINGÚN cuboide libre
    admite a un SKU hoy (0 candidatos, corte barato `max_count=1`), ningún
    fragmento futuro de esos mismos cuboides lo va a admitir después, sea
    cual sea el orden en que se coloquen otros SKUs -"0 nunca vuelve a
    subir". Tres razones, todas verificadas, no solo supuestas:

    1. MaxRects (`packing_columnar.py`) solo FRAGMENTA -cada cuboide libre
       nuevo es un subconjunto geométrico (w/h/d) de aquel del que salió.
       El cuboide inicial de un pallet vacío es siempre un SUPERCONJUNTO de
       cualquier cuboide que pueda existir después.
    2. Las únicas reglas de `_cuboide_admite_candidato` que dependen de lo
       YA puesto (`_soporte_viola_nivel`, `_altura_compatible_con_cama`)
       son estrictamente MÁS permisivas en el piso (z=0) que en cualquier
       posición elevada -nunca al revés.
    3. `capacidad_cama_por_sku` (tope de cama) y `tope_pallet_por_sku`
       (tope de Cajas por PH) son topes POR SKU, independientes de lo que
       hagan otros SKUs -nunca se relajan por una colocación ajena.

    Con esta propiedad confirmada, "0 candidatos y 0 capacidad instalada"
    para un SKU HOY es una afirmación válida no solo sobre este nodo
    congelado, sino sobre TODA la subrama que sale de él -ese SKU jamás va
    a poder completarse mientras este subárbol siga construyendo sobre el
    mismo layout, así que podar de inmediato (en vez de esperar a que
    TODOS los SKUs se estanquen) ahorra beam width real para ramas que sí
    pueden llegar al 100% (ver `test_poda_A_mala_decision_deja_sku_
    estancado_y_se_poda` / `test_poda_B_otra_rama_preserva_espacio_y_
    llega_al_100`).

    [Se conserva de Fase 1.1] Podar sigue significando "no seguir
    EXPANDIENDO esta rama en `_beam_search`", nunca "descartar su valor
    como posible `mejor_estado`" -un estado que ya colocó mucho antes de
    toparse con un SKU imposible sigue siendo un resultado real y sigue
    compitiendo como mejor intento final (ver `_beam_search`).

    [Fase 2.1] Envoltorio de una línea sobre `_evaluar_viabilidad` -misma
    lógica exacta, sin cambios de comportamiento; se extrajo para que
    `_beam_search` pueda instrumentar además QUÉ sku causó cada poda, sin
    afectar el booleano que ya usan todos los tests de Fase 1/1.1/1.2."""
    return _evaluar_viabilidad(
        estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
    )[0]


def _beam_search(
    estado_inicial: _EstadoGlobal, por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], presupuesto: float,
    limite_tiempo: float, beam_width: int, estrategia: str, stats: dict, oracle_sampler=None,
    reloj: Callable[[], float] = time.process_time,
) -> tuple[_EstadoGlobal, str]:
    """[secciones 6, 11, 16] Un reinicio completo del multi-start (sección
    17 orquesta varios). Mantiene hasta `beam_width` estados vivos por
    nivel; cada uno se expande (MRV + candidatos diversos + lotes, sección
    7-10), los hijos que sobreviven a la poda segura (sección 14) y a la
    transposition table (sección 15/16 -duplicados/dominados descartados)
    compiten por los `beam_width` lugares del siguiente nivel según
    `_score_estado`. Un estado que queda ESTANCADO (0 candidatos para su
    SKU más restringido) NO se descarta -se conserva tal cual en la
    frontera, todavía puede ser el mejor global si nada más progresa.

    Devuelve (mejor_estado_encontrado, motivo_stop) -motivo_stop en
    {"completo", "timeout", "estancado"}.

    [Fase 2.1, instrumentación por profundidad -pedida explícitamente por
    el usuario para la auditoría de completitud, "sin cambiar su
    comportamiento"] Nada de lo agregado acá participa en NINGUNA decisión
    de control (qué se poda, qué entra al beam, cuál es `mejor_estado`) -
    son solo lecturas/conteos adicionales sobre exactamente las mismas
    variables que el algoritmo YA calculaba, escritas a
    `stats["depth_log_por_reinicio"][-1]` (una entrada por profundidad, de
    ESTE reinicio) y a `stats["first_depth_zero_candidates_por_reinicio"]`/
    `stats["first_depth_frontier_zero_por_reinicio"]`. Ver el reporte de
    Fase 2.1 para el significado exacto de cada etapa (`children_raw` ->
    `children_after_candidate_filter` -> `children_after_pruning` ->
    `children_after_transposition` -> `beam_kept`/`beam_dropped`).

    [PATCH V6.12-R2-A1] `reloj` default `time.process_time` -mismo dominio
    temporal que `limite_tiempo` (calculado por `global_rescue` con este
    mismo `reloj`); antes de este patch, `limite_tiempo` venía de
    `time.time()` (reloj de pared)."""
    # [PATCH V6.12-D8B-7.2] Con un `MedidorTrabajo` como `reloj` cada
    # `_expandir_estado` suma 1 expansión; con un reloj normal es no-op.
    registrar_expansion = getattr(reloj, "registrar_nodos", None)
    visited: dict[tuple, tuple] = {}
    frontera = [estado_inicial]
    mejor_estado = estado_inicial
    mejor_score = _score_estado(
        estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
    )
    motivo_stop = "timeout"

    # [Fase 2.1] Contexto de instrumentación de ESTE reinicio -listas/
    # dicts nuevos, nunca leídos por ninguna decisión de control de abajo.
    depth_log: list[dict] = []
    stats.setdefault("depth_log_por_reinicio", []).append(depth_log)
    zero_candidates_actual: dict[str, int] = {}
    stats.setdefault("first_depth_zero_candidates_por_reinicio", []).append(zero_candidates_actual)
    stats["_zero_candidates_actual"] = zero_candidates_actual
    stats.setdefault("first_depth_frontier_zero_por_reinicio", []).append(None)
    profundidad = 0

    while True:
        stats["_depth_actual"] = profundidad
        frontier_in = len(frontera)

        if reloj() > limite_tiempo:
            motivo_stop = "timeout"
            break
        if all(sum(c for c in e.pendientes.values() if c > 0) == 0 for e in frontera):
            motivo_stop = "completo"
            break

        raw_antes = stats["raw_candidates_generados"]
        topk_antes = stats["candidates_retenidos_top_k"]

        candidatos_hijos: list[_EstadoGlobal] = []
        algun_expandido = False
        for estado in frontera:
            if sum(c for c in estado.pendientes.values() if c > 0) == 0:
                candidatos_hijos.append(estado)
                continue
            hijos = _expandir_estado(
                estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, estrategia, stats,
                presupuesto,
            )
            if registrar_expansion is not None:
                registrar_expansion(1)
            stats["estados_generados"] += len(hijos)
            if not hijos:
                candidatos_hijos.append(estado)  # estancado -se conserva, puede seguir siendo el mejor
                continue
            algun_expandido = True
            candidatos_hijos.extend(hijos)

        # [Fase 2.1] Delta de esta profundidad -"children_raw" (combos
        # crudos generados por `_generar_candidatos_multi_pallet`) y
        # "children_after_candidate_filter" (tras `_seleccionar_top_k_
        # diverso`), ambos ANTES de expandirse en estados por lote.
        children_raw = stats["raw_candidates_generados"] - raw_antes
        children_after_candidate_filter = stats["candidates_retenidos_top_k"] - topk_antes

        # [Fase 1.1 -bug real encontrado probando el punto 4 del usuario]
        # "Podar" (sección 14) significa "no seguir EXPANDIENDO esta rama"
        # -NUNCA "descartar su valor". La versión anterior hacía `continue`
        # apenas `_es_estado_inviable` daba True, así que un estado que YA
        # había colocado toda la demanda DISPONIBLE (y solo le quedaba un
        # SKU permanentemente imposible, BLOQUEADO) se declaraba muerto Y
        # SE TIRABA ENTERO -perdiendo ese progreso real, porque nunca
        # llegaba a competir por `mejor_estado`. Ahora TODO hijo (muerto o
        # vivo) se puntúa y compite por `mejor_estado`; solo los VIVOS
        # entran a la frontera del próximo nivel (expandir un muerto sería
        # trabajo desperdiciado, ya se probó que no puede mejorar).
        vivos: list[tuple[tuple, _EstadoGlobal]] = []
        children_after_pruning = 0  # [Fase 2.1] vivos tras poda, ANTES de sacar dominados por transposition
        prune_by_sku_depth: dict[str, int] = {}  # [Fase 2.1]
        for hijo in candidatos_hijos:
            # [PATCH V6.07, sección 9] Un cache por HIJO -`_evaluar_
            # viabilidad` (poda) y `_score_estado` (deuda de escasez) se
            # consultan sobre el MISMO objeto `hijo` en el mismo instante,
            # así que comparten cache -si la poda ya avanzó el iterador
            # estructural de un sku, el score reutiliza ese trabajo.
            # [PATCH V6.12-2A2] Además, este `hijo` puede YA traer una cache
            # asociada -de `_critical_precedence_lookahead` (si acaba de
            # salir de ahí, ver ese pre-chequeo de viabilidad) o de un
            # `estado` estancado re-agregado tal cual (`candidatos_hijos.
            # append(estado)` más arriba, mismo objeto que ya se expandió) -
            # se reutiliza esa en vez de descartarla.
            if presupuesto is not None:
                cache_hijo = _cache_estructural_de_estado(hijo) or CacheEstructural()
                _asociar_cache_estructural(hijo, cache_hijo)
            else:
                cache_hijo = None
            muerto, sku_causante = _evaluar_viabilidad(
                hijo, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
                oracle_sampler, cache_hijo,
            )
            score_hijo = _score_estado(
                hijo, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
                cache_hijo,
            )
            # [sección 15/16, Fase 1.1] Clave CANÓNICA completa (tupla), no
            # `hash(...)` de ella -ver docstring de `_clave_estado`.
            clave = _clave_estado(hijo)
            si_dominado = False
            if clave in visited:
                stats["duplicados"] += 1
                stats["transposition_hits"] += 1
                if score_hijo <= visited[clave]:
                    si_dominado = True  # dominado por (o igual a) un estado equivalente ya visto
            if not si_dominado and len(visited) < GLOBAL_VISITED_MAX:
                visited[clave] = score_hijo

            if not si_dominado and score_hijo > mejor_score:
                mejor_score = score_hijo
                mejor_estado = hijo

            if muerto:
                stats["estados_pruned_no_moves"] += 1
                if sku_causante is not None:  # [Fase 2.1]
                    prune_by_sku_depth[sku_causante] = prune_by_sku_depth.get(sku_causante, 0) + 1
                continue  # no ocupa lugar en la frontera -pero ya compitió por mejor_estado arriba
            children_after_pruning += 1  # [Fase 2.1]
            if si_dominado:
                continue
            vivos.append((score_hijo, hijo))

        # [Fase 2.1] "deuda_best" se lee del propio `mejor_score` -criterio
        # 1 del score de Fase 1.2 es `-deuda_de_escasez` (ver `_score_
        # estado`), así que negarlo de nuevo recupera la deuda tal cual.
        cajas_colocadas_best = mejor_estado.cajas_colocadas
        deuda_best = -mejor_score[0]

        if not vivos:
            depth_log.append({
                "depth": profundidad, "frontier_in": frontier_in,
                "cajas_colocadas_best": cajas_colocadas_best, "deuda_best": deuda_best,
                "children_raw": children_raw, "children_after_candidate_filter": children_after_candidate_filter,
                "children_after_pruning": children_after_pruning, "children_after_transposition": len(vivos),
                "beam_kept": 0, "beam_dropped": 0, "prune_by_sku": prune_by_sku_depth, "frontier_out": 0,
            })
            if stats["first_depth_frontier_zero_por_reinicio"][-1] is None:
                stats["first_depth_frontier_zero_por_reinicio"][-1] = profundidad
            motivo_stop = "estancado"
            break

        children_after_transposition = len(vivos)  # [Fase 2.1]

        vivos.sort(key=lambda par: par[0], reverse=True)
        frontera = [hijo for _, hijo in vivos[:beam_width]]
        stats["max_frontier"] = max(stats["max_frontier"], len(frontera))

        depth_log.append({
            "depth": profundidad, "frontier_in": frontier_in,
            "cajas_colocadas_best": cajas_colocadas_best, "deuda_best": deuda_best,
            "children_raw": children_raw, "children_after_candidate_filter": children_after_candidate_filter,
            "children_after_pruning": children_after_pruning,
            "children_after_transposition": children_after_transposition,
            "beam_kept": len(frontera), "beam_dropped": children_after_transposition - len(frontera),
            "prune_by_sku": prune_by_sku_depth, "frontier_out": len(frontera),
        })
        profundidad += 1

        if sum(c for c in mejor_estado.pendientes.values() if c > 0) == 0:
            motivo_stop = "completo"  # [sección 18] detenerse YA al llegar al 100%
            break
        if not algun_expandido:
            motivo_stop = "estancado"
            break

    stats.pop("_zero_candidates_actual", None)
    return mejor_estado, motivo_stop


def global_rescue(
    pallets: list[PalletV5],
    sin_colocar: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    n_pallets: int,
    cd: str,
    presupuesto: float,
    deadline: float | None = None,
    contador: list[int] | None = None,
    oracle_sampler=None,
    presupuesto_expansiones: int | None = None,
) -> tuple[list[PalletV5], dict[str, int], dict]:
    """[sección 4] Punto de entrada. A diferencia de Rescue V6.02/Repair
    V6.04/Exact Local Repair (que reciben el MEJOR resultado ya obtenido y
    tratan de MEJORARLO), Global Rescue solo usa `pallets`/`sin_colocar`
    para reconstruir la demanda TOTAL del CD (sección 5) -no hereda ningún
    layout parcial. `n_pallets` es `Pallets_Objetivo`, la cantidad EXACTA
    con la que arranca (fija, no se abre ni se cierra ningún pallet más).

    No decide acá si el resultado es mejor que lo que ya tenía el llamador
    -eso (mismo criterio de score que usan las demás capas) lo hace quien
    conecte este módulo al pipeline de `packing_bloques.py` (Fase 2, ver
    docstring del módulo). Esta función siempre devuelve su MEJOR intento,
    aunque sea peor que lo que ya había.

    [Fase 2, punto 1 -agregado al conectar Global Rescue al pipeline]
    `contador`: contador compartido opcional para los IDs de pallet nuevos
    (mismo patrón que ya usan `_empacar_n_pallets`/`_empacar`). Si se omite
    (default, todos los tests de Fase 1/1.1/1.2), se usa un contador propio
    empezando en 0 -sin cambio de comportamiento para esos tests. El
    llamador real (`_empacar_n_pallets`) SÍ debe pasar su propio `contador`
    compartido: los IDs de Global Rescue ya llevan el infijo "-GR-" que los
    distingue de los IDs normales (`PV5-{cd}-{n}` vs `PV5-{cd}-GR-{n}`), así
    que no hay colisión entre ámbitos -pero SIN contador compartido, dos
    llamadas a `global_rescue` para el MISMO cd (ej. sondeos repetidos de
    `_empacar_optimizado`) reiniciarían su propio contador en 0 y podrían
    repetir el mismo ID entre sí.

    [Fase 2.1] `oracle_sampler`: hook de diagnóstico opcional, ver
    `_evaluar_viabilidad`. `None` (default, siempre en el pipeline real) ->
    cero cambio de comportamiento ni de costo.

    [PATCH V6.12-R2-A1] `reloj = time.process_time` explícito, mismo
    patrón de V6.11-R3/rescue_solver/repair_solver -antes `limite_tiempo`
    se calculaba con `time.time()` (reloj de pared, sensible a contención
    de otros CDs corriendo en paralelo). `deadline` (parámetro externo,
    ver `packing_bloques._empacar_n_pallets`) también debe venir ya en
    este dominio (CPU-time).

    [PATCH V6.12-D8B-7.2 -"Final Global work budget"] `presupuesto_expansiones`
    (default `None` = comportamiento de siempre, CPU-time): cuando se pasa, el
    `reloj` de TODO este Global es un `MedidorTrabajo` cuya unidad son
    EXPANSIONES DE ESTADO (cada llamada a `_expandir_estado` en el beam
    search) y `limite_tiempo = reloj() + presupuesto_expansiones`; `deadline`
    (un instante de CPU-time) se IGNORA en ese modo. Los puntos de control son
    los mismos de siempre (inicio de cada profundidad y de cada reinicio), así
    que es un SOFT CAP AT DEPTH BOUNDARY: la profundidad en curso termina y el
    total consumido puede superar el tope por, como máximo, esa profundidad.
    Lo pasa únicamente la materialización FINAL
    (`busqueda_n_pallets.FINAL_GLOBAL_MAX_EXPANSIONS`)."""
    reloj: Callable[[], float]
    t0_wall = time.time()  # solo para stats["tiempo_s"] (diagnóstico humano, no budget)
    if presupuesto_expansiones is not None:
        # [PATCH V6.12-D8B-7.2] ver el docstring (presupuesto de TRABAJO).
        from src.medidor_trabajo import MedidorTrabajo

        reloj = MedidorTrabajo()
        limite_tiempo = reloj() + presupuesto_expansiones
    else:
        reloj = time.process_time
        limite_tiempo = reloj() + GLOBAL_RESCUE_TIME_SECONDS
        if deadline is not None:
            limite_tiempo = min(limite_tiempo, deadline)

    stats: dict = {
        "activado": True, "cd": cd, "beam_width_por_estrategia": dict(GLOBAL_BEAM_WIDTH_BY_STRATEGY),
        "estados_generados": 0, "estados_pruned_no_moves": 0, "duplicados": 0, "transposition_hits": 0,
        "max_frontier": 0, "max_deferred_skus": 0,
        "raw_candidates_generados": 0, "candidates_retenidos_top_k": 0,
        "reinicios": [], "por_sku": {},
        # [PATCH V6.07, secciones 14-15] Instrumentación del Structural
        # Fallback -nombres separados por operación (sección 15: "no
        # mezclar candidatos válidos, únicos y nuevos frente a MaxRects").
        "structural_exists_calls": 0, "structural_count_calls": 0, "structural_generate_calls": 0,
        "structural_positions_tested": 0,
        "structural_positions_rejected_bounds": 0, "structural_positions_rejected_overlap": 0,
        "structural_positions_rejected_support": 0,
        "structural_early_exit_exists": 0, "structural_early_exit_count": 0,
        "structural_cache_hits": 0, "structural_cache_misses": 0, "structural_time_seconds": 0.0,
        "structural_candidates_valid_before_dedupe": 0, "structural_candidates_unique_new_vs_maxrects": 0,
        "false_zero_maxrects": {},
        # [PATCH V6.08, secciones 7, 11] Zero-Only Structural Rescue -estos
        # SOLO se incrementan cuando MaxRects dio 0 (el único caso en que
        # Structural se consulta desde V6.08 en adelante).
        "zero_rescue_exists_calls": 0, "zero_rescue_count_calls": 0, "zero_rescue_generate_calls": 0,
        "zero_rescue_successes": 0, "zero_rescue_failures": 0, "zero_rescue_by_sku": {},
        "placements_from_maxrects": 0, "placements_from_structural_zero_rescue": 0,
        "structural_rescues_used": {},
        # [PATCH V6.09, sección 10 -"Critical Precedence Lookahead"]
        "critical_lookahead_calls": 0, "precedence_constraints_detected": 0, "victims_considered": 0,
        "victim_first_children_generated": 0, "victim_first_children_viable": 0, "critical_lookahead_events": [],
    }

    demanda_total = _reconstruir_demanda_total(pallets, sin_colocar, por_sku)
    if contador is None:
        contador = [0]

    if n_pallets <= 0 or not any(cantidad > 0 for cantidad in demanda_total.values()):
        stats.update({
            "tiempo_s": round(time.time() - t0_wall, 3), "mejor_colocado": 0,
            "faltantes": {sku: cantidad for sku, cantidad in demanda_total.items() if cantidad > 0},
            "motivo_stop": "sin_demanda_o_sin_pallets", "errores_geometricos": 0,
        })
        return [], stats["faltantes"], stats

    mejor_global: _EstadoGlobal | None = None
    mejor_score_global: tuple | None = None
    motivo_stop_global = "timeout"

    for intento, estrategia in enumerate(GLOBAL_MULTI_START_ESTRATEGIAS[:GLOBAL_MULTI_START_MAX]):
        # [sección 18] El primer intento SIEMPRE corre, aunque `deadline` ya
        # haya vencido al entrar -`_beam_search` lo resuelve solo (corta en
        # su primera iteración, devuelve el estado inicial sin crashear).
        # Sin este intento garantizado, un deadline vencido de entrada
        # dejaría `mejor_global` en None.
        if intento > 0 and reloj() > limite_tiempo:
            break
        # [PATCH V6.10, sección 3] Única fuente de verdad -ver
        # `_beam_width_para_estrategia` y `GLOBAL_BEAM_WIDTH_BY_STRATEGY`.
        beam_width = _beam_width_para_estrategia(estrategia)
        estado_inicial = _crear_estado_inicial(n_pallets, cd, contador, demanda_total)
        resultado, motivo_stop = _beam_search(
            estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            presupuesto, limite_tiempo, beam_width, estrategia, stats, oracle_sampler,
            reloj=reloj,
        )
        score = _score_estado(
            resultado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
        )
        stats["reinicios"].append({
            "estrategia": estrategia, "beam_width": beam_width,
            "colocado": resultado.cajas_colocadas, "motivo_stop": motivo_stop,
        })
        if mejor_score_global is None or score > mejor_score_global:
            mejor_score_global = score
            mejor_global = resultado
            motivo_stop_global = motivo_stop
        if motivo_stop == "completo":
            break  # [sección 18] 100% ya encontrado -no hace falta más reinicios

    assert mejor_global is not None  # garantizado por el guard de arriba (al menos 1 reinicio corre)

    pallets_final = [pc.pallet for pc in mejor_global.construcciones]
    sin_colocar_final = {sku: cantidad for sku, cantidad in mejor_global.pendientes.items() if cantidad > 0}

    errores_geometricos: list[str] = []
    for pallet in pallets_final:
        errores_geometricos.extend(validar_pallet_v5(pallet))

    stats["tiempo_s"] = round(time.time() - t0_wall, 3)
    stats["mejor_colocado"] = mejor_global.cajas_colocadas
    stats["faltantes"] = dict(sin_colocar_final)
    stats["motivo_stop"] = motivo_stop_global
    stats["errores_geometricos"] = len(errores_geometricos)
    if errores_geometricos:
        stats["errores_geometricos_detalle"] = errores_geometricos

    return pallets_final, sin_colocar_final, stats
