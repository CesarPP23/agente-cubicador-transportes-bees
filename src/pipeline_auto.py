"""[V-AUTO] Corre V4 y V5 completos sobre la MISMA entrada y, CD por CD, se
queda con el que da mejor resultado -no un único ganador para todo el
dataset.

Justificación empírica (comparación contra datos reales del 18.08.2026,
6 CDs): ninguno de los dos motores gana siempre. V4 ganó en BK36, BK49,
BK50 y BK51; V5 empató o perdió en esos mismos CDs; en el dataset de
referencia grande (Cubicaje18.07.2026.xlsx, más CDs y más volumen) V5 le
ganó a V4 por un margen mucho más claro (49 vs 55). La ventaja de cada
motor depende de la escala/composición de cada CD, no es un ganador
universal -"elegir uno solo para todo el dataset" deja plata sobre la mesa
en cualquiera de los dos sentidos. AUTO nunca puede dar un resultado PEOR
que el mejor de los dos por CD, porque literalmente elige entre ellos.

Costo: corre el pipeline completo dos veces (más lento que cualquiera de
los dos solo). Aceptado a propósito -optimalidad por sobre velocidad, ver
instrucción del usuario ("que se quede con la más óptima siempre")."""
import config
from models import Pallet, ResultadoPipeline
from src import exportar
from src.pipeline import ejecutar_core_v4


def _es_armado(pallet: Pallet) -> bool:
    """Pallets 'Requiere Revisión' (sin clasificar / geometría insuficiente)
    son IDÉNTICOS entre V4 y V5 -salen de la misma validación/reconciliación
    compartida, antes de que exista ninguna diferencia de armado- así que no
    hace falta compararlos por CD, alcanza con tomarlos de cualquiera de los
    dos resultados."""
    return pallet.tipo != "Requiere Revisión"


def _score_cd(pallets_cd: list[Pallet]) -> tuple:
    """Mismo criterio lexicográfico que `multistart.SolucionCD.score`
    (DOCUMENTACION_TECNICA_V5.md sección 8), aplicado por CD en vez de por
    estrategia: menos pallets primero, después menos pallets bajo el
    nominal, después menos dedicados a BAT, después más cerca del target de
    altura en promedio. `min()` sobre esta tupla elige el mejor -determinista,
    sin aleatoriedad."""
    if not pallets_cd:
        return (0, 0, 0, 0.0)
    alturas = [p.altura_final for p in pallets_cd]
    n_bajo_nominal = sum(1 for a in alturas if a < config.ALTURA_NOMINAL_MIN)
    bat_dedicados = sum(1 for p in pallets_cd if p.id.startswith("PH-BAT-") or p.id.startswith("PV5-BAT-"))
    desviacion_media = sum(abs(a - config.ALTURA_TARGET) for a in alturas) / len(alturas)
    return (len(pallets_cd), n_bajo_nominal, bat_dedicados, round(desviacion_media, 3))


def ejecutar_core_auto(envios, maestro, uma) -> ResultadoPipeline:
    from src import benchmark, pipeline_v5

    resultado_v4 = ejecutar_core_v4(envios.copy(), maestro.copy(), uma.copy())
    resultado_v5 = pipeline_v5.ejecutar_core_v5(envios.copy(), maestro.copy(), uma.copy())

    armados_v4 = [p for p in resultado_v4.pallets if _es_armado(p)]
    armados_v5 = [p for p in resultado_v5.pallets if _es_armado(p)]
    no_armados = [p for p in resultado_v4.pallets if not _es_armado(p)]

    pallets_v5_por_cd: dict[str, list] = {}
    for pv5 in resultado_v5.pallets_v5 or []:
        pallets_v5_por_cd.setdefault(pv5.cd, []).append(pv5)

    cds = sorted({p.cd for p in armados_v4} | {p.cd for p in armados_v5})
    todos_armados: list[Pallet] = []
    pallets_v5_elegidos: list = []
    eleccion_por_cd: dict[str, str] = {}
    for cd in cds:
        pallets_v4_cd = [p for p in armados_v4 if p.cd == cd]
        pallets_v5_cd = [p for p in armados_v5 if p.cd == cd]
        if _score_cd(pallets_v5_cd) < _score_cd(pallets_v4_cd):
            todos_armados.extend(pallets_v5_cd)
            pallets_v5_elegidos.extend(pallets_v5_por_cd.get(cd, []))
            eleccion_por_cd[cd] = "V5"
        else:
            # Empate -> V4: es el motor probado en producción, no hay razón
            # para preferir V5 cuando el resultado es exactamente igual.
            todos_armados.extend(pallets_v4_cd)
            eleccion_por_cd[cd] = "V4"

    todos_pallets = todos_armados + no_armados

    fila_bench_v4 = resultado_v4.benchmark_df.iloc[0]
    bench_resultado = benchmark.calcular_kpis(
        todos_pallets,
        demanda_unidades_error=float(fila_bench_v4["demanda_unidades_error"]),
        geometria_inferida_count=int(fila_bench_v4["geometria_inferida_count"]),
    )
    bench_resultado.extras["eleccion_por_cd"] = eleccion_por_cd
    bench_df = benchmark.benchmark_df([bench_resultado])

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets, resultado_v4.info_sku)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=resultado_v4.log_validacion_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=resultado_v4.info_sku,
        auditoria_geometrica_df=resultado_v4.auditoria_geometrica_df,
        benchmark_df=bench_df,
        pallets_v5=pallets_v5_elegidos,
    )
