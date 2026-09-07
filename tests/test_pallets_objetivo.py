"""[conexión de `pallets_objetivo` al pipeline real -pedido explícito del
usuario: "conectalo al pipeline real"] Antes de este archivo,
`pallets_objetivo` solo se podía usar llamando a `armar_pallets_bloques`
directamente (sin ningún llamador de producción, ver Parches/v5/
PATCH_LOG.md). Estos tests cubren la conexión end-to-end: hoja opcional
"Pallets_Objetivo" -> `validacion.cargar_pallets_objetivo` ->
`pipeline.ejecutar_pipeline`/`ejecutar_desde_archivo` ->
`pipeline_sku_bloque.ejecutar_core_sku_bloque` -> `armar_pallets_bloques`.

Usan demanda chica que el motor exacto resuelve sin necesitar LNS (rápido)
-la potencia del solver (backtracking + ruina-y-reconstrucción) ya está
cubierta en `tests/test_packing_bloques.py`; acá solo se verifica que el
parámetro efectivamente llegue de punta a punta y que, si no se usa, el
comportamiento de siempre no cambia."""
import io

import pandas as pd

from src.pipeline import ejecutar_pipeline
from src.pipeline_sku_bloque import ejecutar_core_sku_bloque
from src.validacion import cargar_pallets_objetivo


def test_sin_hoja_pallets_objetivo_devuelve_none(dataset_factory):
    envios, maestro, uma = dataset_factory()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        envios.to_excel(writer, sheet_name="Envios_Julio", index=False)
        maestro.to_excel(writer, sheet_name="Maestro_SKUs", index=False)
        uma.to_excel(writer, sheet_name="UMA", index=False)
    buffer.seek(0)
    assert cargar_pallets_objetivo(buffer) is None


def test_con_hoja_pallets_objetivo_devuelve_el_dict_por_cd(dataset_factory):
    envios, maestro, uma = dataset_factory()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        envios.to_excel(writer, sheet_name="Envios_Julio", index=False)
        maestro.to_excel(writer, sheet_name="Maestro_SKUs", index=False)
        uma.to_excel(writer, sheet_name="UMA", index=False)
        pd.DataFrame([{"CD": "BK31", "Pallets_Objetivo": 3}]).to_excel(
            writer, sheet_name="Pallets_Objetivo", index=False
        )
    buffer.seek(0)
    assert cargar_pallets_objetivo(buffer) == {"BK31": 3}


def test_sin_pallets_objetivo_por_cd_no_cambia_nada(dataset_factory):
    """[no-regresión] `ejecutar_pipeline` sin el parámetro nuevo (o con
    `None`) tiene que comportarse EXACTO que antes de esta conexión -sigue
    usando `_empacar` (abre los pallets que hagan falta), nunca el motor
    de N fijos."""
    envios, maestro, uma = dataset_factory(envios_overrides=[{"cajas": 10}])
    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert len(resultado.pallets) == 1
    resultado_explicito_none = ejecutar_pipeline(envios, maestro, uma, pallets_objetivo_por_cd=None)
    assert len(resultado_explicito_none.pallets) == 1


def test_pallets_objetivo_por_cd_fuerza_la_cantidad_exacta(dataset_factory):
    """[conexión real] Un CD listado en `pallets_objetivo_por_cd` reparte
    TODA su demanda entre exactamente esa cantidad de pallets -acá se
    fuerza a 2 pallets una demanda que el barrido normal (`_empacar`)
    metería cómoda en 1 solo, para confirmar que el parámetro realmente
    cambia el camino de armado, no solo que no rompe nada."""
    envios, maestro, uma = dataset_factory(envios_overrides=[{"cajas": 10}])

    resultado_normal = ejecutar_core_sku_bloque(envios, maestro, uma)
    assert len(resultado_normal.pallets) == 1  # comportamiento de siempre: 1 solo pallet

    resultado_forzado = ejecutar_core_sku_bloque(envios, maestro, uma, pallets_objetivo_por_cd={"BK31": 2})
    assert len(resultado_forzado.pallets) == 2  # forzado a 2, aunque la demanda entraba en 1
    total_despachado = sum(l.cajas_demanda_oficial for p in resultado_forzado.pallets for l in p.lineas)
    assert total_despachado == 10  # ninguna caja se pierde repartiendo


def test_otro_cd_sin_pallets_objetivo_sigue_como_siempre(dataset_factory):
    """[alcance acotado] `pallets_objetivo_por_cd` solo afecta a los CDs
    que lista -un CD que no aparece ahí sigue con `_empacar` de siempre,
    aunque OTRO CD del mismo archivo sí tenga cantidad fija."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"cd": "BK31", "cajas": 10}, {"cd": "BK99", "cajas": 10, "sku": 2}],
        maestro_overrides=[{"sku": 1}, {"sku": 2}],
        uma_overrides=[{"sku": 1}, {"sku": 2}],
    )
    resultado = ejecutar_core_sku_bloque(envios, maestro, uma, pallets_objetivo_por_cd={"BK31": 2})
    pallets_bk31 = [p for p in resultado.pallets if p.cd == "BK31"]
    pallets_bk99 = [p for p in resultado.pallets if p.cd == "BK99"]
    assert len(pallets_bk31) == 2  # forzado
    assert len(pallets_bk99) == 1  # sin cambios, comportamiento de siempre
