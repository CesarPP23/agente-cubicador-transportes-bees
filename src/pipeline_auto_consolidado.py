"""[V-AUTO-CONSOLIDADO] Igual que V-AUTO (`pipeline_auto.py`, que queda
intacto -instrucción explícita del usuario de no tocarlo mientras se prueba
esta variante), pero antes de comparar V4 vs V5 por CD, aplica
`consolidacion_sku.consolidar_sku` sobre el resultado crudo de V5 -para que
la comparación considere una versión de V5 con los SKUs repartidos ya
concentrados en menos pallets cuando es posible, no la versión cruda del
packer. Reusa `_score_cd`/`_es_armado` de `pipeline_auto.py` -mismo
criterio de comparación, no uno nuevo."""
import config
from models import Pallet, ResultadoPipeline
from src import benchmark, consolidacion_sku, exportar, pipeline_v5, soporte
from src.pipeline import ejecutar_core_v4
from src.pipeline_auto import _es_armado, _score_cd


def ejecutar_core_auto_consolidado(envios, maestro, uma) -> ResultadoPipeline:
    resultado_v4 = ejecutar_core_v4(envios.copy(), maestro.copy(), uma.copy())
    resultado_v5 = pipeline_v5.ejecutar_core_v5(envios.copy(), maestro.copy(), uma.copy())

    pallets_v5_consolidados = consolidacion_sku.consolidar_sku(resultado_v5.pallets_v5 or [])
    armados_v5 = [pipeline_v5._palletv5_a_pallet(p, resultado_v5.info_sku) for p in pallets_v5_consolidados]
    for pallet in armados_v5:
        soporte.clasificar_soporte_pallet(pallet)

    armados_v4 = [p for p in resultado_v4.pallets if _es_armado(p)]
    no_armados = [p for p in resultado_v4.pallets if not _es_armado(p)]

    pallets_v5_por_cd: dict[str, list] = {}
    for pv5 in pallets_v5_consolidados:
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
            eleccion_por_cd[cd] = "V5_CONSOLIDADO"
        else:
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
