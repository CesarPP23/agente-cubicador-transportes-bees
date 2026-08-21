import sys, traceback, math
sys.path.insert(0, ".")
import pandas as pd
import config

RESULTS = []

def run(name, fn):
    try:
        fn()
        RESULTS.append((name, "PASS", None))
    except AssertionError as e:
        RESULTS.append((name, "FAIL", str(e)[:300]))
    except Exception as e:
        RESULTS.append((name, "ERROR", f"{type(e).__name__}: {e}"[:300]))

# ---- conftest.py fixture, replicado a mano ----
ENVIOS_COLS = ["CD", "SKU", "Descripción", "Cajas Teóricas", "Unidades"]
MAESTRO_COLS = ["SKU", "Categoría", "Unidades por caja", "Cajas por cama", "Camas por PH", "Cajas por PH"]
UMA_COLS = ["SKU", "Largo de caja", "Ancho de caja", "Alto de caja", "Peso bruto por unidad"]

def _envio(cd="BK31", sku=1, descripcion="Producto", cajas=10, unidades=None):
    return {"CD": cd, "SKU": sku, "Descripción": descripcion, "Cajas Teóricas": cajas,
            "Unidades": unidades if unidades is not None else cajas}

def _maestro(sku=1, categoria="Licores", unidades_por_caja=1, cajas_por_cama=10, camas_por_ph=5, cajas_por_ph=50):
    return {"SKU": sku, "Categoría": categoria, "Unidades por caja": unidades_por_caja,
            "Cajas por cama": cajas_por_cama, "Camas por PH": camas_por_ph, "Cajas por PH": cajas_por_ph}

def _uma(sku=1, largo=30, ancho=20, alto=30, peso_unidad=1.0):
    return {"SKU": sku, "Largo de caja": largo, "Ancho de caja": ancho, "Alto de caja": alto,
            "Peso bruto por unidad": peso_unidad}

def dataset_factory(envios_overrides=None, maestro_overrides=None, uma_overrides=None):
    envios_overrides = envios_overrides or [{}]
    maestro_overrides = maestro_overrides or [{}]
    uma_overrides = uma_overrides or [{}]
    envios = pd.DataFrame([_envio(**o) for o in envios_overrides], columns=ENVIOS_COLS)
    maestro = pd.DataFrame([_maestro(**o) for o in maestro_overrides], columns=MAESTRO_COLS)
    uma = pd.DataFrame([_uma(**o) for o in uma_overrides], columns=UMA_COLS)
    return envios, maestro, uma

# ============================================================================
import importlib
tv = importlib.import_module("tests.test_validacion")
td = importlib.import_module("tests.test_derivados")
tp2d = importlib.import_module("tests.test_packing_2d")
ta3d = importlib.import_module("tests.test_apilado_3d")
tth = importlib.import_module("tests.test_topado_homogeneos")
tinv = importlib.import_module("tests.test_invariantes")
tprd = importlib.import_module("tests.test_pipeline_real_data")

# --- test_validacion.py ---
for fname in ["test_normaliza_casing_de_categoria","test_categoria_no_clasificada_se_loguea_pero_no_excluye",
              "test_sku_sin_maestro_se_excluye","test_sentinel_cajas_por_ph_se_marca_no_confiable",
              "test_dimension_imposible_se_excluye","test_altura_excesiva_se_excluye",
              "test_cajas_por_cama_cero_se_trata_como_nulo","test_peso_fuera_de_rango_se_marca_no_validable_sin_excluir",
              "test_cajas_teoricas_no_positivas_se_excluyen","test_duplicados_cd_sku_se_suman"]:
    fn = getattr(tv, fname)
    run(f"test_validacion::{fname}", lambda fn=fn: fn(dataset_factory))

# --- test_derivados.py ---
for fname in ["test_redondeo_hacia_arriba_de_cajas_fraccionarias","test_fallback_geometrico_cuando_falta_cajas_por_cama",
              "test_nivel_categoria_remate_es_el_nivel_mas_alto","test_nivel_categoria_asignado_para_categoria_estable"]:
    fn = getattr(td, fname)
    run(f"test_derivados::{fname}", lambda fn=fn: fn(dataset_factory))

# --- test_packing_2d.py ---
for fname in ["test_densidad_maxima_limita_cajas_por_cama","test_clustering_por_altura_no_combina_alturas_dispares",
              "test_clustering_combina_alturas_similares","test_remate_nunca_comparte_cama","test_categorias_no_remate_pueden_compartir_cama_por_dimension","test_nabs_nunca_comparte_cama_con_niveles_base"]:
    fn = getattr(tp2d, fname)
    run(f"test_packing_2d::{fname}", lambda fn=fn: fn(dataset_factory))

# --- test_apilado_3d.py (sin fixtures) ---
for fname in ["test_orden_de_estabilidad_se_respeta_sin_importar_orden_de_entrada",
              "test_remate_nunca_comparte_pallet_y_prioriza_mayor_remanente",
              "test_cierre_forzado_bajo_altura_minima_se_marca_parcial",
              "test_consolidacion_nunca_mueve_una_cama_hacia_un_pallet_mas_chico"]:
    fn = getattr(ta3d, fname)
    run(f"test_apilado_3d::{fname}", fn)

# --- test_topado_homogeneos.py ---
run("test_topado_homogeneos::test_pallet_homogeneo_se_completa_con_remate_disponible",
    lambda: tth.test_pallet_homogeneo_se_completa_con_remate_disponible(dataset_factory))

# --- test_invariantes.py: orientacion (parametrize manual) + resultado/demanda_oficial fixtures ---
for largo, ancho, esperado in [(25,51,8), (51,25,8), (30,30,12), (110,40,2)]:
    run(f"test_invariantes::test_orientacion_maximiza_cajas_totales[{largo}-{ancho}]",
        lambda largo=largo, ancho=ancho, esperado=esperado: tinv.test_orientacion_maximiza_cajas_totales(largo, ancho, esperado))
run("test_invariantes::test_orientacion_nunca_peor_que_la_alternativa", tinv.test_orientacion_nunca_peor_que_la_alternativa)
run("test_invariantes::test_orientacion_devuelve_none_si_no_cabe", tinv.test_orientacion_devuelve_none_si_no_cabe)

from pathlib import Path
DATASET = Path(".") / "Cubicaje18.07.2026.xlsx"
if DATASET.exists():
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    maestro = pd.read_excel(DATASET, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(DATASET, sheet_name="UMA")
    from src.pipeline import ejecutar_pipeline
    resultado = ejecutar_pipeline(envios, maestro, uma)

    envios2 = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    envios2["SKU"] = envios2["SKU"].astype(str).str.strip()
    envios2 = envios2[envios2["Cajas Teóricas"] > 0]
    agrupado = envios2.groupby(["CD", "SKU"])["Cajas Teóricas"].sum()
    demanda_oficial = {clave: math.ceil(valor) for clave, valor in agrupado.items()}

    for fname in ["test_ningun_pallet_supera_el_tope_duro", "test_pallets_sobre_el_maximo_normal_son_pocos_y_justificados", "test_orden_vertical_de_categorias",
                  "test_remate_exclusivo", "test_nada_pesado_encima_de_nabs",
                  "test_peso_respetado_como_restriccion", "test_regla_de_soporte",
                  "test_ids_de_pallet_unicos"]:
        fn = getattr(tinv, fname)
        run(f"test_invariantes::{fname}", lambda fn=fn: fn(resultado))

    run("test_invariantes::test_nunca_se_despacha_por_encima_de_la_demanda",
        lambda: tinv.test_nunca_se_despacha_por_encima_de_la_demanda(resultado, demanda_oficial))
    run("test_invariantes::test_determinismo", lambda: tinv.test_determinismo(demanda_oficial))

    for fname in ["test_no_genera_pallets_homogeneos_con_demanda_de_julio","test_alturas_nunca_exceden_el_maximo",
                  "test_ningun_pallet_mezcla_comestibles_y_cigarros_como_remate",
                  "test_demanda_planificada_coincide_con_demanda_redondeada",
                  "test_log_validacion_registra_los_hallazgos_conocidos"]:
        fn = getattr(tprd, fname)
        run(f"test_pipeline_real_data::{fname}", fn)
else:
    print("AVISO: no está el dataset real, se saltean los tests que dependen de él")

# ---- reporte ----
ok = sum(1 for _,s,_ in RESULTS if s=="PASS")
print(f"\n{'='*70}\n{ok}/{len(RESULTS)} pasaron\n{'='*70}")
for name, status, msg in RESULTS:
    marker = "OK  " if status=="PASS" else ("FAIL" if status=="FAIL" else "ERR ")
    print(f"[{marker}] {name}" + (f"  -> {msg}" if msg else ""))
