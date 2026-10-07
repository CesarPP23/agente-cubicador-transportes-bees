"""[V6.12-R2-B] Búsqueda tri-state de la N mínima de pallets -reemplaza el
binary search "no encontrado => infactible" de `_empacar_optimizado`
(`packing_bloques.py`) por un modelo explícito de 4 estados por N
(`FEASIBLE`/`UNKNOWN`/`INFEASIBLE_PROVEN`/`UNTESTED`) más un hard lower
bound matemático (peso + volumen + Cajas por PH), y Policy A (descenso
lineal persistente, tope de 5 solves) como única política de propuesta
implementada -Policy B/C quedaron diseñadas (ver historial del chat de la
sesión V6.12-R2-B0/R2-B) pero SIN implementar: los 6 CDs reales medidos
(golden-6 + BK41) tienen gaps demasiado chicos (0-4) para justificar su
complejidad extra; se implementan si aparece en producción un CD con un
gap real grande que lo justifique.

[pedido explícito -sección A de la autorización] Separa estrictamente
BÚSQUEDA (decide únicamente `best_feasible_n` + `optimality_status`, NUNCA
corre LNS completo ni decide qué layout se exporta) de MATERIALIZACIÓN
(la corrida final con LNS completo en `best_feasible_n`, responsabilidad
exclusiva de `_empacar_optimizado`, no de este módulo).

NO toca: `_empacar`, `_empacar_n_pallets`, el camino de `Pallets_Objetivo`
fijo, ni ningún rescuer (rescue_solver/repair_solver/exact_repair/
global_rescue) -ver sección F de la autorización. `probe()` de abajo llama
a `_empacar_n_pallets(..., con_lns=False)` tal cual ya existía -sigue
disparando la cascada completa si hace falta (problema aparte, auditado en
V6.12-R1, fuera de alcance acá); lo único que cambia es la interpretación
del resultado."""
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from enum import Enum

import config
from models import PalletV5
from src.torres import TorreCandidate

# --- ceil_safe: nunca sobreestima por ruido de punto flotante -------------


def ceil_safe(numerador: float, denominador: float, margen_relativo: float = 1e-9) -> int:
    """Ceil "conservador" para bounds matemáticos: nunca redondea hacia
    arriba por ruido de precisión binaria. Un cociente que MATEMÁTICAMENTE
    es un entero exacto (p.ej. peso_total/PESO_TOPE == 3.0, sumando cientos
    de `Peso_Caja * Cajas_Remanente` en float64) puede llegar acá como
    3.0000000000003 por acumulación de error de redondeo -sin margen,
    `math.ceil(3.0000000000003)` da 4, SOBREESTIMANDO el bound (exactamente
    lo que se prohibió explícitamente: "jamás puede sobreestimar por ruido
    floating point"). Restar un margen relativo ANTES de redondear hacia
    arriba hace que ese caso siga dando 3 -el único costo posible es, en el
    peor caso YA real (cociente genuinamente 3.0000000001 -CD real que sí
    necesita 4), devolver 3 en vez de 4: el bound queda más FLOJO, nunca
    más ajustado de lo matemáticamente válido -la única dirección seguro.

    Usa `Decimal` (no float) para la división y el redondeo final -evita
    que el propio redondeo reintroduzca el mismo problema que se corrige;
    `Decimal(str(x))` (no `Decimal(x)` directo) toma la representación
    decimal "limpia" de python, no el valor binario exacto del float."""
    if denominador <= 0:
        raise ValueError(f"ceil_safe: denominador debe ser positivo, recibido {denominador}")
    razon = Decimal(str(float(numerador))) / Decimal(str(float(denominador)))
    razon_conservadora = razon * (Decimal(1) - Decimal(str(margen_relativo)))
    return int(razon_conservadora.to_integral_value(rounding=ROUND_CEILING))


def ceil_exacto_enteros(numerador: int, denominador: int) -> int:
    """Ceil division EXACTA para dos enteros genuinos (Cajas por PH,
    demanda en cajas) -sin floats, sin Decimal, sin ningún margen: no hace
    falta, la aritmética de enteros de Python es exacta siempre (a
    diferencia de `ceil_safe`, que existe justamente porque peso/volumen sí
    vienen de floats)."""
    if denominador <= 0:
        raise ValueError(f"ceil_exacto_enteros: denominador debe ser positivo, recibido {denominador}")
    return -(-numerador // denominador)


# --- Hard lower bound: peso + volumen + Cajas por PH -----------------------


def hard_lower_bound(
    pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    tope_pallet_por_sku: dict[str, int],
) -> int:
    """[V6.12-R2-B0, corregido tras auditoría] Piso matemático SEGURO de
    pallets -nunca puede sobreestimar (ver `ceil_safe`). Combina 3 bounds
    independientes, cada uno una relajación válida del problema real
    (ningún N por debajo del máximo de los 3 puede colocar el 100% de la
    demanda, sin importar el algoritmo/arreglo real):

    - peso: ningún pallet excede `PESO_TOPE_ELASTICO_KG` (cap YA duro en
      producción, ver `validacion_peso.py`).
    - volumen: ningún pallet excede su volumen físico máximo admisible
      -footprint CON overhang (`PALLET_LARGO_EFECTIVO x PALLET_ANCHO_
      EFECTIVO`, el MISMO que usa el propio solver como su canvas
      operativo real, ver `_cuboide_inicial` en `packing_columnar.py`) por
      altura de producto (`_altura_presupuesto()`, la misma función que ya
      usa el solver -incluye la resta de `ALTURA_PALLET_VACIO`, `220cm`
      YA incluye la parihuela). Asume 100% de eficiencia de empaque -por
      eso es un PISO, nunca una estimación realista; puede quedar flojo
      (fragmentación geométrica real), nunca ajustado de más.
    - Cajas por PH: `tope_pallet_por_sku` YA es un tope DURO por pallet por
      SKU dentro del propio solver -ningún SKU puede repartirse en menos
      pallets que `ceil(demanda_sku / tope_pallet_por_sku[sku])`.

    Deliberadamente NO incluye ningún bound de footprint/huella 2D-3D
    combinada -calcularlo bien es el mismo problema NP-hard que resuelve
    el solver; cualquier heurística barata para estimarlo podría
    sobreestimar factibilidad (subestimar el N real necesario) y dejaría
    de ser una prueba matemática."""
    from src.packing_columnar import _altura_presupuesto

    peso_total = 0.0
    volumen_total = 0.0
    for sku, cantidad in pendientes.items():
        if cantidad <= 0 or not por_sku.get(sku):
            continue
        # Cualquier candidata sirve: el volumen y el peso de UNA caja no
        # cambian con la orientación, solo se re-permutan sus 3 lados.
        candidata = por_sku[sku][0]
        peso_total += candidata.peso_unitario * cantidad
        volumen_total += candidata.largo * candidata.ancho * candidata.alto_caja * cantidad

    volumen_util_pallet = (
        config.PALLET_LARGO_EFECTIVO * config.PALLET_ANCHO_EFECTIVO * _altura_presupuesto()
    )

    n_peso = ceil_safe(peso_total, config.PESO_TOPE_ELASTICO_KG) if peso_total > 0 else 1
    n_volumen = ceil_safe(volumen_total, volumen_util_pallet) if volumen_total > 0 else 1

    n_ph = 0
    for sku, cantidad in pendientes.items():
        if cantidad <= 0:
            continue
        tope = tope_pallet_por_sku.get(sku)
        if tope and tope > 0:
            n_ph = max(n_ph, ceil_exacto_enteros(cantidad, tope))

    return max(n_peso, n_volumen, n_ph, 1)


# --- Tri-state probe + estado de búsqueda por N -----------------------------


class ProbeStatus(Enum):
    FEASIBLE = "FEASIBLE"
    UNKNOWN = "UNKNOWN"


class EstadoN(Enum):
    FEASIBLE = "FEASIBLE"
    UNKNOWN = "UNKNOWN"
    INFEASIBLE_PROVEN = "INFEASIBLE_PROVEN"
    UNTESTED = "UNTESTED"  # default -jamás se infiere como prueba, solo se lee


@dataclass(frozen=True)
class ProbeResult:
    n: int
    status: ProbeStatus
    pallets: list[PalletV5] | None
    cajas_colocadas: int
    demanda_total: int
    cpu_s: float


@dataclass
class BusquedaState:
    hard_lower_bound: int
    best_feasible: int | None = None
    best_feasible_pallets: list[PalletV5] | None = None
    estado_por_n: dict[int, EstadoN] = field(default_factory=dict)
    solves_realizados: int = 0
    trace: list[dict] = field(default_factory=list)  # diagnóstico -1 entrada por N consultado

    def estado(self, n: int) -> EstadoN:
        """`UNTESTED` es el default explícito -nunca se asume FEASIBLE ni
        INFEASIBLE_PROVEN para un N que no se probó. La única excepción es
        n < hard_lower_bound, que SIEMPRE es INFEASIBLE_PROVEN por el
        propio bound matemático, sin necesidad de gastar un solve."""
        if n < self.hard_lower_bound:
            return EstadoN.INFEASIBLE_PROVEN
        return self.estado_por_n.get(n, EstadoN.UNTESTED)

    def registrar_feasible_directo(self, n: int, pallets: list[PalletV5]) -> None:
        """Para el incumbente inicial (`n_greedy`) -ya se sabe FEASIBLE por
        construcción (el greedy siempre coloca el 100% de la demanda, ver
        `_empacar`), no gasta un solve nuevo ni pasa por `probe()`."""
        self.estado_por_n[n] = EstadoN.FEASIBLE
        self.best_feasible, self.best_feasible_pallets = n, pallets
        self.trace.append({"n": n, "estado": EstadoN.FEASIBLE.value, "fuente": "greedy_incumbente", "cpu_s": 0.0})

    def registrar(self, r: ProbeResult) -> None:
        self.solves_realizados += 1
        self.estado_por_n[r.n] = EstadoN[r.status.name]
        if r.status is ProbeStatus.FEASIBLE and (self.best_feasible is None or r.n < self.best_feasible):
            self.best_feasible, self.best_feasible_pallets = r.n, r.pallets
        self.trace.append({
            "n": r.n, "estado": r.status.value, "fuente": "probe",
            "cajas_colocadas": r.cajas_colocadas, "demanda_total": r.demanda_total,
            "cpu_s": round(r.cpu_s, 3),
        })

    def optimality_status(self) -> str:
        """[V6.12-R2-B, corregido] `PROVEN_MINIMUM` exige evidencia
        `INFEASIBLE_PROVEN` explícita para TODOS los N entre el hard bound
        y `best_feasible` -`UNTESTED` y `UNKNOWN` cuentan exactamente
        igual acá: ninguno de los dos prueba nada. Con el motor de hoy, la
        ÚNICA fuente de `INFEASIBLE_PROVEN` para un N es `n <
        hard_lower_bound` (no existe ningún mecanismo que pruebe
        infactibilidad de un N individual por encima del bound) -así que
        en la práctica esto colapsa exactamente a
        `best_feasible == hard_lower_bound`, pero se deja expresado en su
        forma general (vía `estado()`) para no romper si algún día se
        agrega una segunda fuente de prueba por N."""
        if self.best_feasible is None:
            return "SIN_SOLUCION"
        rango = range(self.hard_lower_bound, self.best_feasible)
        if all(self.estado(n) is EstadoN.INFEASIBLE_PROVEN for n in rango):
            return "PROVEN_MINIMUM"
        return "BEST_FEASIBLE_UNPROVEN"


# [PATCH V6.12-D7B-P1 -"Probe DFS work budget"] Tope de nodos del DFS inicial
# del SONDEO (`probe()`), SOLO en este contexto. Medido en V6.12-D7B-P (batch
# real de 9 CDs, 9 sondeos): el nodo donde el DFS inicial de un sondeo
# encuentra su mejor resultado nunca pasó de 5367 (SJ95 n=3, UNKNOWN sin
# remedio) y en los 3 sondeos FEASIBLE fue 759/85/86 -con 30000 el DFS gastaba
# ~80% de sus nodos DESPUÉS de haber encontrado su mejor resultado (el 83%
# de los DFS iniciales terminaba por `max_nodos`). Con 8000 el resultado del
# DFS es idéntico (el corte llega después del mejor nodo) y el sondeo cuesta
# ~1/4. El DFS de la materialización final (30000), el de `Pallets_Objetivo`
# fijo, el del LNS y el de Rescue/Repair NO se tocan. La unidad es CONTEO DE
# NODOS -determinista, independiente de la velocidad del reloj.
PROBE_DFS_MAX_NODES = 8000

# [PATCH V6.12-D7B-P2 -"Probe Rescue work budget"] Presupuesto de NODOS de
# Rescue, SOLO en el contexto del sondeo (`probe()`); la materialización final
# y `Pallets_Objetivo` fijo siguen con el presupuesto de CPU-time de siempre.
# Calibrado en V6.12-D7B-P2 (batch real de 9 CDs, 8 cascadas de Rescue en
# probes, cascada COMPLETA corriendo detrás: Rescue -> Repair -> Exact ->
# Global) contra 12000 / 14000 / 15000:
#   * 3 probes FEASIBLE (BK41 n=3, BK65 n=4, BK68 n=3) preservados con los 3
#     topes, mismos hashes finales y mismo hash de witness;
#   * último nodo que mejora el RESIDUAL en BK41 (único FEASIBLE cuyo Rescue
#     queda cortado por el tope): 9032 -> margen 1,66x con 15000;
#   * último nodo que mejora el SCORE COMPLETO en BK41: 12802 -> margen 1,17x
#     (12000 queda debajo, 0,94x; el desempate fino, aunque en este caso
#     igual se reproduce);
#   * 15000 reproduce el residual de Rescue del baseline en BK31 y SJ95 n=4
#     (12000 no: BK31 queda en 23 en vez de 18 faltantes) a +59 s de CPU de
#     Rescue sobre 12000 (~3,5% del CPU de probes UNKNOWN).
# Unidad y semántica de conteo: ver `src/medidor_trabajo.py`.
PROBE_RESCUE_MAX_NODES = 15000

# [PATCH V6.12-D7B-P3 -"Probe Repair work budget"] Presupuesto de NODOS de
# Repair, SOLO en el contexto del sondeo; propagado explícito `probe()` ->
# `_empacar_n_pallets(presupuesto_repair_nodos)` -> `repair_solver(
# presupuesto_nodos)`, con su PROPIO medidor (independiente del de Rescue).
# Calibrado en V6.12-D7B-P3 (batch real, 9 cascadas de Repair en probes,
# sobre P1 + P2, con Exact y Global sin tocar y la cascada completa detrás)
# contra 24000 / 26000 / 28000:
#   * los 3 topes preservan los 3 probes FEASIBLE, los 6 UNKNOWN, los hashes
#     finales y el hash de witness;
#   * el ÚNICO éxito de Repair en probes es BK65 n=4 (residual 3 -> 0, mejoras
#     en los nodos 13754 y 13799): margen 1,74x / 1,88x / 2,03x. BK41 n=3 no
#     recibe ninguna mejora de Repair (3 -> 3) y Global lo resuelve igual;
#   * Repair NO ahorra CPU con ningún tope (las instancias que hoy cortan por
#     tiempo antes de llegar al tope trabajan más): CPU Repair UNKNOWN 539 s
#     por tiempo contra 557 / 597 / 643 s -cada +2000 nodos de tope cuestan
#     ~+40-46 s y compran ~+0,14x de margen, sin punto de inflexión. 24000 es
#     el único que no encarece el CPU de forma material (+3%) y el margen
#     nominal es conservador: la unidad en curso termina al cruzar el tope.
# Unidad y semántica de conteo: ver `src/medidor_trabajo.py`.
PROBE_REPAIR_MAX_NODES = 24000
# Contrato (ver `src/medidor_trabajo.py`): `PROBE_RESCUE_MAX_NODES` y
# `PROBE_REPAIR_MAX_NODES` son "soft cap at work-unit boundary" -el tope se
# chequea ENTRE unidades de trabajo, así que una unidad ya iniciada puede
# terminar por encima del tope (en P3 un DFS llegó a 26365 con tope 24000).
# El comportamiento NO se modifica; el margen de calibración ya lo absorbe.

# [PATCH V6.12-D7B-P4 -"Probe Exact deterministic hardening"] NO es una fase de
# performance: elimina el reloj como fuente de decisión lógica en Exact dentro
# del probe, con riesgo mínimo. Dos niveles independientes:
#   A. Orquestador Python (`exact_repair_orquestado`): tope DURO de intentos,
#      compartido por todos los pallets del CD en la etapa, EN VEZ del deadline
#      de CPU-time. A diferencia de los topes de nodos (soft cap), se chequea
#      ANTES de cada intento: nunca se ejecuta el intento `max + 1`. Máximo
#      observado en probes reales: 144 (BK65 n=3: 48 intentos x 3 pallets) -el
#      tope es 3,5x ese máximo, no un ajuste fino. La etapa termina por
#      `solucion` / `espacio_agotado` / `max_attempts`, nunca por reloj.
#   B. CP-SAT nativo: `max_deterministic_time` (1 worker => reproducible) en
#      vez de depender de `max_time_in_seconds`, que queda como WATCHDOG
#      operacional (`OPERATIONAL_TIMEOUT` si alguna vez dispara, ver
#      `exact_repair._clasificar_parada_cp_sat`; deuda: el parcial no se
#      descarta, solo se registra). Calibración y por qué ese valor: ver el
#      comentario de `PROBE_EXACT_MAX_DET_TIME`.
PROBE_EXACT_MAX_ATTEMPTS = 500
# Calibración (V6.12-D7B-P4, shadow sobre 35 modelos CP-SAT REALES: 18 del
# batch histórico + 17 de golden BK52/BK53, todos OPTIMAL con 1 worker):
# `deterministic_time` máximo observado 0,0023 (mediana 0,0007) y resultado
# (status/objetivo/hash de solución) idéntico con 0,05 / 0,1 / 1,0 y sin
# inestabilidad entre repeticiones. 1,0 es el más conservador (428x el máximo
# observado; 0,05 serían 21x) y sigue siendo útil como safety budget: acota
# cada resolución a ~10 s de pared en estos modelos (antes 30 s). NO está
# ajustado al máximo observado: nunca debe atar en el trabajo real.
PROBE_EXACT_MAX_DET_TIME = 1.0

# [PATCH V6.12-D8A.1 -"Final materialization work budget"] Presupuestos de
# TRABAJO de la materialización FINAL (`_empacar_optimizado`, la corrida con LNS
# en la N ganadora). Contexto propio: NO son los del sondeo (arriba) ni los de
# `Pallets_Objetivo` fijo, que siguen con 30000 / 3000 / 40. Propagados
# explícitos `_empacar_optimizado` -> `_empacar_n_pallets(max_nodos_dfs,
# lns_recon_max_nodos, lns_sin_mejora_max)` -> `_lns_mejorar_pallets`.
# Calibrados en V6.12-D8A / D8A.1 desde BREAKPOINTS MEDIDOS de los 8 CDs cuya
# final tiene éxito (BK31, BK41, BK43, BK65, BK68, SJ86, SJ87, SJ95). Regla:
# un DFS con tope C reproduce el resultado de uno mayor si su último nodo que
# mejora el incumbente es <= C+1; en el LNS solo importan las iteraciones
# ACEPTADAS (las rechazadas se revierten). Breakpoints:
#   * DFS inicial: último nodo que mejora = 4275 (SJ86)  -> tope >= 4274;
#   * reconstrucción LNS: nodo máximo en iteraciones aceptadas = 2465 (BK43,
#     iteración 19)                                      -> tope >= 2464;
#   * iteraciones sin mejora: 38 antes de la primera mejora de SJ95 -> >= 39.
# Elegidos (shadow de batch completo, 9/9 hashes canónicos idénticos, 8/8
# éxitos, SJ97 sigue cayendo al witness, mismo recorrido de iteraciones LNS
# aceptadas en los 7 CDs con LNS): DFS 6500 (margen 1,5x, cuesta ~+7 s de CPU
# por CD), recon 2650 (margen 185 nodos = 7,5%; comparado con 2500, que sólo
# deja 35 nodos, cuesta +42 s de CPU en SJ97 (~+4%)), sin mejora 40 (sin
# cambio). Por DEBAJO de los breakpoints el layout cambia aunque se siga
# colocando el 100% (control de precipicio: FINAL_LAYOUT_CHANGED en BK43 y
# SJ86). Efecto medido: SJ97 final ~1109 -> ~964 s de CPU y batch ~1187 ->
# ~1004 s de pared.
FINAL_DFS_MAX_NODES = 6500
FINAL_LNS_RECON_MAX_NODES = 2650
FINAL_LNS_SIN_MEJORA = 40


def probe(
    n: int,
    pendientes_originales: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    cd: str,
    contador: list[int],
    paralelo_lns: bool,
) -> ProbeResult:
    """[V6.12-R2-B] Un solo sondeo de N. Corre `_empacar_n_pallets(...,
    con_lns=False)` -EXACTAMENTE el mismo camino que ya usaba el binary
    search viejo, sin cambios (sigue disparando la cascada rescue/repair/
    exact/global completa si hace falta -eso es un problema aparte, ver
    auditoría V6.12-R1, fuera de alcance de R2-B). La única diferencia
    real es la interpretación del resultado: "no llegó al 100%" ya NO se
    trata como prueba de infactibilidad -se reporta honestamente como
    `UNKNOWN`."""
    from src.packing_bloques import _empacar_n_pallets

    demanda_total = sum(pendientes_originales.values())
    t0 = time.process_time()
    pallets, sin_colocar = _empacar_n_pallets(
        dict(pendientes_originales), por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, n, paralelo_lns=paralelo_lns, con_lns=False, max_nodos_dfs=PROBE_DFS_MAX_NODES,
        presupuesto_rescue_nodos=PROBE_RESCUE_MAX_NODES, presupuesto_repair_nodos=PROBE_REPAIR_MAX_NODES,
        presupuesto_exact_intentos=PROBE_EXACT_MAX_ATTEMPTS, exact_max_deterministic_time=PROBE_EXACT_MAX_DET_TIME,
    )
    cpu_s = time.process_time() - t0
    colocadas = demanda_total - sum(sin_colocar.values())
    if not sin_colocar:
        return ProbeResult(n, ProbeStatus.FEASIBLE, pallets, colocadas, demanda_total, cpu_s)
    return ProbeResult(n, ProbeStatus.UNKNOWN, None, colocadas, demanda_total, cpu_s)


# --- Policy A: descenso lineal persistente ----------------------------------

# [pedido explícito -sección D] mismo tope que ya usaba el binary search
# viejo (`COMBINACION_ABIERTO_MAX_INTENTOS_BUSQUEDA`, packing_bloques.py) -
# no se cambia ningún presupuesto, solo se reusa el mismo número con otro
# nombre porque ahora gobierna una política distinta (descenso, no
# bisección).
POLICY_A_MAX_SOLVES = 5


def politica_a_descenso(
    state: BusquedaState,
    pendientes_originales: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    cd: str,
    contador: list[int],
    paralelo_lns: bool,
    max_solves: int = POLICY_A_MAX_SOLVES,
) -> None:
    """[V6.12-R2-B, Policy A] Descenso lineal PERSISTENTE desde
    `state.best_feasible - 1` hasta `state.hard_lower_bound` o
    `max_solves` -decrementa de a 1 SIEMPRE. Un `UNKNOWN` se registra
    (queda en `state.estado_por_n`), pero NUNCA corta el descenso ni
    modifica `state.hard_lower_bound` -el único que decide qué es
    matemáticamente infactible es el bound, calculado una sola vez ANTES
    de empezar a buscar; un `FEASIBLE` sí actualiza `state.best_feasible`.
    Muta `state` in-place; no devuelve nada -la decisión final se lee de
    `state.best_feasible` / `state.optimality_status()`."""
    assert state.best_feasible is not None, "requiere un incumbente FEASIBLE ya registrado (n_greedy)"
    candidato = state.best_feasible - 1
    while candidato >= state.hard_lower_bound and state.solves_realizados < max_solves:
        if state.estado(candidato) is EstadoN.UNTESTED:
            resultado = probe(
                candidato, pendientes_originales, por_sku, capacidad_cama_por_sku, nivel_por_sku,
                tope_pallet_por_sku, cd, contador, paralelo_lns,
            )
            state.registrar(resultado)
        candidato -= 1
