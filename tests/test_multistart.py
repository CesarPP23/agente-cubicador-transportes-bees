"""[V5-P7] Multi-start: varias estrategias + semillas, selección
lexicográfica, determinismo."""
import pandas as pd

from src.multistart import ESTRATEGIAS, generar_soluciones_cd, mejor_solucion


def _df_cd(n_skus=6, cd="BK31"):
    filas = []
    for i in range(n_skus):
        filas.append(
            {
                "SKU": f"S{i}", "CD": cd, "Cajas_Remanente": 5 + i,
                "Largo_Efectivo": 20 + i * 2, "Ancho_Efectivo": 15 + i,
                "Alto_Efectivo": 20 + i * 3, "Peso_Caja": 1.0 + i * 0.2,
                "Cajas_Cama_Efectivo": 10 - i, "Fuente_Geometria": "UMA_VALIDADA",
            }
        )
    return pd.DataFrame(filas)


def test_genera_una_solucion_por_estrategia_determinista_mas_seeds_random():
    df = _df_cd()
    soluciones = generar_soluciones_cd(df, "BK31", info_sku={}, seeds=5)
    deterministas = [s for s in soluciones if s.estrategia != "RANDOM"]
    aleatorias = [s for s in soluciones if s.estrategia == "RANDOM"]

    assert len(deterministas) == len(ESTRATEGIAS) - 1  # todas menos RANDOM
    assert len(aleatorias) == 5  # una por seed
    assert {s.estrategia for s in deterministas} == set(ESTRATEGIAS) - {"RANDOM"}


def test_todas_las_soluciones_despachan_la_misma_demanda_total():
    df = _df_cd()
    soluciones = generar_soluciones_cd(df, "BK31", info_sku={}, seeds=3)
    totales = set()
    for sol in soluciones:
        total = sum(t.cantidad for p in sol.pallets for t in p.torres)
        totales.add(total)
    assert len(totales) == 1, f"la demanda despachada no debería depender de la estrategia: {totales}"


def test_seleccion_lexicografica_elige_menos_pallets_primero():
    from src.multistart import SolucionCD

    peor = SolucionCD(cd="BK31", estrategia="A", seed=None, n_pallets=5, n_pallets_bajo_190=0, residual_total=0, altura_media=200, geometrias_inferidas=0)
    mejor = SolucionCD(cd="BK31", estrategia="B", seed=None, n_pallets=3, n_pallets_bajo_190=2, residual_total=50, altura_media=150, geometrias_inferidas=5)
    elegida = mejor_solucion([peor, mejor])
    assert elegida is mejor  # menos pallets gana aunque sea peor en todo lo demás


def test_mismo_input_mismas_seeds_da_mismo_resultado():
    df = _df_cd()
    s1 = generar_soluciones_cd(df, "BK31", info_sku={}, seeds=4)
    s2 = generar_soluciones_cd(df, "BK31", info_sku={}, seeds=4)

    assert [s.score for s in s1] == [s.score for s in s2]
    m1, m2 = mejor_solucion(s1), mejor_solucion(s2)
    assert m1.score == m2.score
    assert m1.estrategia == m2.estrategia
    assert m1.seed == m2.seed
