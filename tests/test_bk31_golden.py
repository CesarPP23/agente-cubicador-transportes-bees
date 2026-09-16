"""Golden Case BK31 (PATCH V6.01, sección 4) -benchmark de regresión
principal antes de tocar heurísticas de búsqueda (DFS/LNS/orden de SKUs).

Demanda y reconstrucción manual en `tests/fixtures/bk31_manual.py` (12
SKUs, 98 cajas, CD Cañete, `Pallets_Objetivo=1` -ver
`Parches/v5/ejemplo_manual_bk31/README.md`)."""
import pytest

import config
from fixtures.bk31_manual import (
    DEMANDA_TOTAL_CAJAS,
    cajas_por_ph_bk31,
    cargar_pallet_manual_bk31,
    demanda_df,
    demanda_solver_df,
)
from src import diagnostico_no_colocadas
from src.packing_bloques import armar_pallets_bloques
from src.validacion_v5 import validar_pallet_v5


def test_bk31_demanda_total_es_98():
    assert DEMANDA_TOTAL_CAJAS == 98
    assert demanda_df()["Cajas"].sum() == 98


def test_bk31_respeta_cajas_por_ph():
    """`Cajas por PH` es el máximo TOTAL por SKU en un pallet (sección
    1.3) -acá, con demanda de UN solo pallet, el chequeo es que ningún SKU
    pida más de lo que su PH admite (si esto no se cumpliera, ni el
    armado manual ni el motor podrían cumplir la demanda en un pallet)."""
    ph = cajas_por_ph_bk31()
    for fila in demanda_df().itertuples():
        assert fila.Cajas <= ph[fila.SKU], f"{fila.SKU}: demanda {fila.Cajas} > Cajas por PH {ph[fila.SKU]}"


@pytest.mark.xfail(
    reason=(
        "PATCH V6.01, sección 10: el pallet manual BK31 NO pasa el validador "
        "todavía -35 violaciones (18 soporte insuficiente en la torre de "
        "Vino/Vodka de las camas 2-4, 17 overlaps de ~1cm en la repisa "
        "Picaras/Altomayo/KR de las camas 5-6). La reconstrucción viene de una "
        "sesión de chat sin medición exacta -son imprecisiones de la "
        "reconstrucción, no evidencia de que el patrón de armado sea "
        "físicamente inviable. Según sección 10 del patch: NO tocar DFS/LNS "
        "hasta reconciliar esto (corregir las coordenadas de la reconstrucción "
        "manual, con más precisión, o confirmar con fotos reales)."
    ),
    strict=True,
)
def test_bk31_manual_es_geometricamente_valido():
    """Test crítico (sección 4.3): valida el pallet armado A MANO -que
    demostró ser geométricamente posible (98/98 en 1 pallet, ver
    Parches/v5/ejemplo_manual_bk31/)- contra el validador digital actual.

    Si este test FALLA, el patch indica NO tocar DFS/LNS todavía: hay que
    reconciliar primero la regla digital que contradice al pallet físico
    (sección 10). Ver el resumen de PATCH V6.01 para el detalle de las
    violaciones encontradas en esta corrida."""
    pallet = cargar_pallet_manual_bk31()
    assert sum(t.cantidad for t in pallet.torres) == 98
    assert pallet.altura_final <= config.ALTURA_MAX_OBSERVADA
    errores = validar_pallet_v5(pallet)
    assert errores == [], f"{len(errores)} violaciones geométricas en el pallet manual BK31:\n" + "\n".join(errores)


def test_bk31_rescue_solver_98_de_98():
    """PATCH V6.02, sección 14: gate del solver -a diferencia de la
    geometría manual (arriba), ESTE test NO es xfail. `armar_pallets_
    bloques` corre el camino normal (greedy+DFS+LNS, baseline conocido
    87/98 -ver Parches/v5/PATCH_LOG.md, "Grandes primero") y, como quedó
    demanda sin colocar con `pallets_objetivo` fijado, el rescue solver
    (`src/rescue_solver.py`: Most-Constrained-First + branching adaptativo
    + Conflict-Directed LNS) entra a intentar mejorarlo -nunca reemplaza el
    camino normal, solo lo usa como fallback si no logra mejorarlo (sección
    3)."""
    df = demanda_solver_df()
    pallets = armar_pallets_bloques(df, "BK31", pallets_objetivo=1)

    colocadas = sum(t.cantidad for p in pallets for t in p.torres)
    sin_colocar: dict[str, int] = {}
    for p in pallets:
        for sku, cant in p.metadata.get("sin_colocar", {}).items():
            sin_colocar[sku] = sin_colocar.get(sku, 0) + cant

    print(f"\nBK31 rescue solver: {colocadas}/{DEMANDA_TOTAL_CAJAS} cajas colocadas en {len(pallets)} pallet(s)")
    if sin_colocar:
        print(f"SKUs sin colocar: {sin_colocar}")
    for p in pallets:
        print(f"  {p.id}: altura_final={p.altura_final:.1f}cm, {len(p.torres)} torres")

    diagnostico = pallets[-1].metadata.get("diagnostico_no_colocadas") if pallets else None
    if diagnostico:
        print("\n" + diagnostico_no_colocadas.formatear_reporte(diagnostico))
    print("\nrescue_stats:", pallets[-1].metadata.get("rescue_stats") if pallets else None)

    assert colocadas == 98
    assert sum(sin_colocar.values()) == 0
    assert len(pallets) == 1
    assert validar_pallet_v5(pallets[0]) == []
    assert pallets[0].altura_final <= config.ALTURA_MAX_OBSERVADA
