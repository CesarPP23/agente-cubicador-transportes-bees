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
