"""Piloto controlado V6.12-RC1 -utilidades compartidas (SOLO medicion/reporte).
NO modifica el solver: lee resultados, calcula metricas y clasifica."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path

# Raiz del solver validado. Por defecto, este mismo checkout. `PILOT_SOLVER_ROOT` apunta el harness a OTRO checkout/worktree del solver
# (p.ej. el de v6.12-rc2) sin copiar archivos dentro de el. Solo cambia DONDE se lee el solver; el harness no lo modifica.
REPO = Path(os.environ.get("PILOT_SOLVER_ROOT") or Path(__file__).resolve().parents[1]).resolve()
RC_TAG = "v6.12-rc1"
# Commit funcional esperado del solver. Por defecto RC1 (tag). Con `PILOT_EXPECTED_SOLVER_COMMIT=<commit>` el solver esperado es ese commit
# (p.ej. d22691c = RC2): la corrida queda clasificada SOLVER_VERSION_EXPECTED_RC2 y NO es PILOT_EXCEPTION por version.
EXPECTED_SOLVER_COMMIT = os.environ.get("PILOT_EXPECTED_SOLVER_COMMIT") or None
SOLVER_PATHS = ["src", "config.py", "models.py"]  # lo que define el comportamiento del solver
CLASES = ("BETTER", "EQUIVALENT", "WORSE", "INVALID")
SIN_OPERACION = "NO_OPERATION_DATA"
# Modo FIXED_N (Pallets_Objetivo = posiciones reales y obligatorias de operacion). Gates:
#   A cubicaje:     PASS_FIXED_N_GEOMETRY / FAIL_FIXED_N
#   BAT:            PASS_BAT_ROUTING / FAIL_BAT_ROUTING
#   C determinismo: REPEAT_MATCH / DETERMINISM_DIVERGENCE / NOT_CHECKED (--repeat 1)
#   Cobertura operacional = A y BAT.
# PESO = INFORMATIONAL_ONLY: la semantica contractual de `Peso bruto por unidad` no esta validada, asi que el peso NO participa en ningun
# PASS/FAIL, factibilidad, cobertura ni clasificacion. Solo se muestra como observacion (WEIGHT_DATA_UNVALIDATED), sin interpretarlo.
BAT_MANEJO = ("A", "B", "C", "UNCONFIRMED")  # A: dentro de los N pallets; B: viaja fuera; C: posicion adicional


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()


def verificar_version() -> dict:
    """Congelamiento: el codigo del solver (src/, config.py, models.py) debe ser BIT A BIT el del solver ESPERADO (por defecto el tag RC1;
    con `PILOT_EXPECTED_SOLVER_COMMIT`, ese commit) y el arbol de trabajo no puede tener cambios sobre ellos.
    `solver_matches_rc1` conserva su nombre por compatibilidad: significa 'coincide con el solver esperado'."""
    ref = EXPECTED_SOLVER_COMMIT or RC_TAG
    ref_commit = _git("rev-parse", f"{ref}^{{commit}}")
    head = _git("rev-parse", "HEAD")
    diffs = []
    for p in SOLVER_PATHS:
        if _git("rev-parse", f"{ref}:{p}") != _git("rev-parse", f"HEAD:{p}"):
            diffs.append(f"{p} (HEAD != {ref})")
        if _git("status", "--porcelain", "--", p):
            diffs.append(f"{p} (cambios sin commitear)")
    if diffs:
        estado = "SOLVER_MISMATCH"
    elif EXPECTED_SOLVER_COMMIT:
        estado = "SOLVER_VERSION_EXPECTED_RC2"
    else:
        estado = "SOLVER_VERSION_EXPECTED_RC1"
    etiqueta = f"expected solver commit {ref_commit[:7]}" if EXPECTED_SOLVER_COMMIT else RC_TAG
    return {"version": f"{etiqueta} / {ref_commit[:7]}", "rc_commit": ref_commit, "head_commit": head,
            "head_branch": _git("rev-parse", "--abbrev-ref", "HEAD"), "solver_matches_rc1": not diffs, "solver_diffs": diffs,
            "solver_version_status": estado, "expected_solver_commit": ref_commit, "solver_root": str(REPO)}


def sha16(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def hash_archivo(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_comp(pallets) -> str:
    """RELEASE_CANONICAL_HASH: scripts/golden6_gate.py::hash_canonico (misma formula)."""
    return sha16(sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pallets))


def hash_layout(pallets, firma) -> str:
    """Control suplementario de geometria (`pipeline_sku_bloque._firma_pallet_canonica`, pasada como `firma`)."""
    return sha16(sorted(firma(p) for p in pallets))


def metricas_cd(pallets, firma, validar, config, area_union_xy) -> dict:
    """Metricas del resultado de UN CD a partir de sus PalletV5."""
    cajas = sum(t.cantidad for p in pallets for t in p.torres)
    falt: dict = {}
    for p in pallets:
        for sku, c in p.metadata.get("sin_colocar", {}).items():
            falt[sku] = falt.get(sku, 0) + c
    skus = {t.sku for p in pallets for t in p.torres} | set(falt)
    alturas = [p.altura_final for p in pallets] or [0.0]
    pesos = [p.peso_estimado for p in pallets] or [0.0]
    area_pallet = config.PALLET_LARGO * config.PALLET_ANCHO
    ocup = [area_union_xy(p.torres) / area_pallet for p in pallets] or [0.0]
    opt = next((p.metadata["optimality_status"] for p in pallets if "optimality_status" in p.metadata), None)
    if opt is None:
        origen = "GREEDY_O_PALLETS_OBJETIVO"  # un solo pallet greedy, o CD con Pallets_Objetivo fijo
    elif opt.get("fuente") == "witness_probe_no_reproducido_por_LNS_final":
        origen = "WITNESS_FALLBACK"
    else:
        origen = "FINAL_MATERIALIZATION"
    return {
        "demanda_cajas": cajas + sum(falt.values()), "skus": len(skus), "n_pallets": len(pallets), "cajas_colocadas": cajas,
        "faltantes": sum(falt.values()), "errores": sum(len(validar(p)) for p in pallets),
        "peso_max": max(pesos), "altura_max": max(alturas), "altura_media": sum(alturas) / len(alturas),
        "pallets_parciales": sum(1 for a in alturas if a < config.ALTURA_TOLERADO_MIN),
        "ocupacion_media": sum(ocup) / len(ocup),
        "weight_data_status": "WEIGHT_DATA_UNVALIDATED",  # informativo: peso_max es el valor calculado, sin interpretar
        "origen": origen, "optimality_status": (opt or {}).get("status"), "hard_lower_bound": (opt or {}).get("hard_lower_bound"),
        "n_greedy": (opt or {}).get("n_greedy"),
        "comp": hash_comp(pallets), "layout": hash_layout(pallets, firma),
    }


def leer_operacion(path: str | Path | None, case_id: str) -> dict:
    """CSV opcional con el plan real/manual. Columnas: cd, n_pallets_operacion, resultado_fisico, observaciones
    (y opcional `case_id`: si esta, solo se usan las filas de ese caso o las vacias). NUNCA altera el solver."""
    if not path:
        return {}
    out: dict = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if row.get("case_id") and row["case_id"] != case_id:
                continue
            if not row.get("cd"):
                continue
            n = row.get("n_pallets_operacion", "")
            out[row["cd"]] = {"n_pallets_operacion": int(float(n)) if n else None,
                              "resultado_fisico": row.get("resultado_fisico") or None, "observaciones": row.get("observaciones") or None}
    return out


def clasificar(m: dict | None, n_operacion: int | None, excepcion: bool = False) -> tuple[str, int | None]:
    """BETTER/EQUIVALENT/WORSE/INVALID (+ NO_OPERATION_DATA cuando no hay plan real con que comparar).
    INVALID: excepcion, errores de validacion, demanda sin colocar o sin resultado.
    Comparacion SOLO por cantidad de pallets (menos es mejor); `diferencia = N cubicador - N operacion`."""
    if excepcion or m is None or m["errores"] > 0 or m["faltantes"] > 0 or not m["n_pallets"]:
        return "INVALID", None
    if n_operacion is None:
        return SIN_OPERACION, None
    d = m["n_pallets"] - n_operacion
    return ("BETTER" if d < 0 else "EQUIVALENT" if d == 0 else "WORSE"), d


def percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


# ----------------------------------------------------------------------------------------------------------------
# FIXED_N
# ----------------------------------------------------------------------------------------------------------------
def cargar_pallets_objetivo(path: str | Path) -> dict | None:
    """Carga la hoja opcional `Pallets_Objetivo` con el cargador OFICIAL del pipeline (src/validacion.py)."""
    from src import validacion

    return validacion.cargar_pallets_objetivo(str(path))


def reconciliar_demanda(envios, maestro, uma, pobj: dict | None) -> dict:
    """Reconcilia, por CD, la demanda original contra la que REALMENTE entra al solver, ejecutando exactamente los
    pasos previos al solver de `pipeline_sku_bloque.ejecutar_core_sku_bloque` y `armar_pallets_bloques` con el solver
    sustituido por un stub que solo captura `pendientes` (no resuelve nada). No corrige datos."""
    import numpy as np

    import config
    import src.packing_bloques as pb
    from src import bat, demanda, derivados, reconciliacion_geometrica, validacion

    pobj = pobj or {}
    env = envios.copy()
    env["SKU"] = env["SKU"].astype(str).str.strip()
    orig = env.groupby("CD").agg(filas=("SKU", "size"), skus=("SKU", "nunique"), cajas=("Cajas Teóricas", "sum"))
    agr = env.groupby(["CD", "SKU"], as_index=False).agg({"Cajas Teóricas": "sum", "Unidades": "sum"})  # V9 suma duplicados
    agr["techo"] = np.ceil(agr["Cajas Teóricas"]).astype(int)

    df_val, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_der = derivados.calcular_derivados(reconciliacion_geometrica.reconciliar(demanda.normalizar_demanda(df_val))[0])
    df_no_bat, df_bat = bat.separar_bat(df_der)
    cls = df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    df_cls = df_no_bat[cls].copy()
    df_nc = df_no_bat[df_no_bat["Categoria_Normalizada"].isna()]
    df_gi = df_no_bat[df_no_bat["Categoria_Normalizada"].notna() & df_no_bat["Requiere_Revision_Geometria"]]
    df_cls["Cajas_Remanente"] = df_cls["Cajas_Teoricas_Redondeadas"].astype(int)

    cap: dict = {}
    orig_n, orig_opt = pb._empacar_n_pallets, pb._empacar_optimizado

    def _stub_n(pendientes, por_sku, *a, **k):
        cap["pend"], cap["por_sku"] = dict(pendientes), set(por_sku)
        return [], {}

    def _stub_opt(pendientes, por_sku, *a, **k):
        cap["pend"], cap["por_sku"] = dict(pendientes), set(por_sku)
        return []

    solver_in: dict = {}
    pb._empacar_n_pallets, pb._empacar_optimizado = _stub_n, _stub_opt
    try:
        for cd, g in df_cls.groupby("CD"):
            cap.clear()
            try:
                pb.armar_pallets_bloques(g, cd, contador=[0], pallets_objetivo=pobj.get(cd), paralelo_lns=False)
            except Exception:  # noqa: BLE001 -tras la captura el resto corre con pallets vacios; solo importa `cap`
                pass
            solver_in[cd] = dict(cap)
    finally:
        pb._empacar_n_pallets, pb._empacar_optimizado = orig_n, orig_opt

    logk: dict = {}
    for _, r in log_df.iterrows():
        logk.setdefault((r["cd"], r["sku"]), set()).add(r["regla"])
    excl_val = {k: v & {"V2", "V4", "V5", "V8"} for k, v in logk.items() if v & {"V2", "V4", "V5", "V8"}}
    bat_k = {(r["CD"], r["SKU"]): ("BAT_categoria_Cigarros" if r["Categoria_Normalizada"] in config.CATEGORIAS_BAT else "BAT_subcategoria_vapes")
             for _, r in df_bat.iterrows()}
    nc_k = {(r["CD"], r["SKU"]) for _, r in df_nc.iterrows()}
    gi_k = {(r["CD"], r["SKU"]) for _, r in df_gi.iterrows()}
    cls_k = {(r["CD"], r["SKU"]): r for _, r in df_cls.iterrows()}

    destinos = []
    for _, r in agr.iterrows():
        k = (r["CD"], r["SKU"])
        if k in excl_val:
            d = "validacion_" + "+".join(sorted(excl_val[k]))
        elif k in bat_k:
            d = bat_k[k]
        elif k in nc_k:
            d = "categoria_no_reconocida"
        elif k in gi_k:
            d = "geometria_insuficiente"
        elif k in cls_k:
            si = solver_in.get(r["CD"], {})
            if "pend" not in si:
                d = "solver_sin_captura"
            elif r["SKU"] not in si["por_sku"]:
                d = "sin_torre_candidata"
            elif si["pend"].get(r["SKU"], 0) <= 0 and cls_k[k]["Cajas_Remanente"] > 0:
                d = "no_cabe_en_pallet_vacio"
            else:
                d = "SOLVER"
        else:
            d = "desconocido"
        destinos.append(d)
    agr["destino"] = destinos

    cajas_bat = bat.consolidar_bat_por_cd(df_bat)
    out: dict = {}
    for cd in sorted(agr["CD"].unique()):
        t = agr[agr["CD"] == cd]
        es_bat = t["destino"].str.startswith("BAT_")
        s, ex, bt = t[t["destino"] == "SOLVER"], t[(t["destino"] != "SOLVER") & ~es_bat], t[es_bat]
        c = df_cls[df_cls["CD"] == cd]
        b = df_bat[df_bat["CD"] == cd]
        si = solver_in.get(cd, {})
        pend = int(sum(si.get("pend", {}).values())) if "pend" in si else None
        efectiva_ceil = int(s["techo"].sum())
        motivos = {}
        for m in sorted(ex["destino"].unique()):  # solo exclusiones reales; Cigarros/Vapes NO es demanda excluida
            q = ex[ex["destino"] == m]
            motivos[m] = {"skus": int(len(q)), "cajas_teoricas": round(float(q["Cajas Teóricas"].sum()), 3)}
        out[cd] = {
            "n_objetivo": pobj.get(cd), "cajas_originales": round(float(orig.loc[cd, "cajas"]), 3), "skus_originales": int(orig.loc[cd, "skus"]),
            "filas_originales": int(orig.loc[cd, "filas"]), "demanda_efectiva_solver": pend, "skus_solver": int(len(s)),
            "cajas_teoricas_solver": round(float(s["Cajas Teóricas"].sum()), 3), "redondeo_ascendente": round(efectiva_ceil - float(s["Cajas Teóricas"].sum()), 3),
            # demanda_original = demanda_cubicable (no BAT) + demanda Cigarros/Vapes separada; la cubicable se reparte entre lo que
            # entra al solver y las OTRAS exclusiones reales (validacion, categoria no reconocida, geometria, sin torre, no cabe).
            "demanda_cubicable": round(float(s["Cajas Teóricas"].sum()) + float(ex["Cajas Teóricas"].sum()), 3),
            "demanda_cigarros_vapes_cajas_teoricas": round(float(bt["Cajas Teóricas"].sum()), 3),
            "identidad_original_cubicable_bat": abs(float(orig.loc[cd, "cajas"]) - (float(s["Cajas Teóricas"].sum()) + float(ex["Cajas Teóricas"].sum()) + float(bt["Cajas Teóricas"].sum()))) < 1e-6,
            "otras_exclusiones_cajas": round(float(ex["Cajas Teóricas"].sum()), 3), "otras_exclusiones_skus": int(len(ex)), "otras_exclusiones_por_motivo": motivos,
            "bat_skus": int(b["SKU"].nunique()), "bat_cajas_teoricas": round(float(b["Cajas Teóricas"].sum()), 3), "bat_unidades": int(b["Unidades"].sum()),
            "bat_cajas_consolidacion": len(cajas_bat.get(cd, [])),
            # Informativo (WEIGHT_DATA_UNVALIDATED): no participa en ningun gate.
            "cajas_con_peso_0": int(c.loc[c["Peso bruto por unidad"] == 0, "Cajas_Remanente"].sum()),
            "skus_sin_peso_validable": int(c["Peso_No_Validable"].sum()),
            "peso_no_validable_skus_en_solver": int(c["Peso_No_Validable"].sum()),
            "peso_no_validable_cajas_en_solver": int(c.loc[c["Peso_No_Validable"], "Cajas_Remanente"].sum()),
            "geom_degradada_skus_en_solver": int((c["Fuente_Geometria"] == "MAESTRO_IMPOSIBLE_DEGRADADO").sum()),
            "identidad_ok": pend is not None and pend == efectiva_ceil,
        }
    return out


def gates_fixed_n(m: dict | None, rec: dict | None, n_objetivo: int | None, repeticion_ok: bool | None, excepcion: bool = False) -> dict:
    """Gate A (cubicaje N fijo), Gate C (determinismo) y RESULT (= Gate A). Los Cigarros/BAT separados NO son faltantes del solver. El peso es
    INFORMATIONAL_ONLY y no interviene en ningun gate."""
    if excepcion or m is None:
        return {"gate_a": "FAIL_FIXED_N", "gate_c": "NOT_CHECKED", "resultado": "FAIL_FIXED_N", "motivos_fail": ["EXCEPTION_O_SIN_RESULTADO"]}
    motivos = []
    if n_objetivo is None:
        motivos.append("SIN_N_OBJETIVO")
    elif m["n_pallets"] != n_objetivo:
        motivos.append(f"N_PRODUCIDO({m['n_pallets']})!=N_OBJETIVO({n_objetivo})")
    if m["faltantes"] > 0:
        motivos.append(f"FALTANTES({m['faltantes']})")
    if m["errores"] > 0:
        motivos.append(f"ERRORES_GEOMETRICOS({m['errores']})")
    if rec is not None and rec.get("demanda_efectiva_solver") is not None and m["cajas_colocadas"] != rec["demanda_efectiva_solver"]:
        motivos.append(f"COLOCADAS({m['cajas_colocadas']})!=DEMANDA_EFECTIVA({rec['demanda_efectiva_solver']})")
    if rec is not None and not rec.get("identidad_ok", False):
        motivos.append("RECONCILIACION_DEMANDA_NO_CIERRA")
    a = "FAIL_FIXED_N" if motivos else "PASS_FIXED_N_GEOMETRY"
    c = "NOT_CHECKED" if repeticion_ok is None else ("REPEAT_MATCH" if repeticion_ok else "DETERMINISM_DIVERGENCE")
    return {"gate_a": a, "gate_c": c, "resultado": a, "motivos_fail": motivos}


# ----------------------------------------------------------------------------------------------------------------
# Cigarros / Vapes (BAT): contrato operacional
#   demanda total -> demanda no BAT -> cubicador (consume N)   |   cigarros/vapes -> hoja `Cigarros_Vapes` (HUB)
# BAT no consume N, no modifica Pallets_Objetivo, no participa en geometria/ocupacion y no cuenta como faltante.
# Es demanda ATENDIDA por otro flujo (no "excluida"). Pilot-side: el exportador productivo NO se toca.
# ----------------------------------------------------------------------------------------------------------------
HOJA_BAT = "Cigarros_Vapes"
COLUMNAS_HOJA_BAT = ["CD", "SKU", "Descripción", "Categoría", "Subcategoría", "Unidades", "Cajas_Teoricas", "Cajas_Consolidacion_CD"]


def _es_bat_negocio(categoria, subcategoria) -> bool:
    """Definicion de NEGOCIO (independiente del pipeline): Categoria Cigarros, o Subcategoria vape/vapes (sin importar
    mayusculas ni espacios). Se usa para comprobar que el pipeline no deje vapes dentro del cubicaje."""
    import config

    cat = config.normalizar_categoria(categoria)
    sub = "" if subcategoria is None or subcategoria != subcategoria else str(subcategoria).strip().casefold()
    return cat in config.CATEGORIAS_BAT or sub in {"vape", "vapes"}


def bat_esperado(envios, maestro):
    """Cigarros/Vapes segun la definicion de negocio, calculado DIRECTO desde el input (sin pasar por el pipeline)."""
    env = envios.copy()
    env["SKU"] = env["SKU"].astype(str).str.strip()
    agr = env.groupby(["CD", "SKU"], as_index=False).agg({"Descripción": "first", "Cajas Teóricas": "sum", "Unidades": "sum"})
    m = maestro.copy()
    m["SKU"] = m["SKU"].astype(str).str.strip()
    m = m.drop_duplicates(subset="SKU")
    cols = ["SKU", "Categoría", "Unidades por caja"] + (["Subcategoría"] if "Subcategoría" in m.columns else [])
    df = agr.merge(m[cols], on="SKU", how="left")
    if "Subcategoría" not in df.columns:
        df["Subcategoría"] = None
    df = df[[_es_bat_negocio(c, sc) for c, sc in zip(df["Categoría"], df["Subcategoría"])]]
    return df.reset_index(drop=True)


def consolidaciones_contractuales(esperado) -> dict:
    """Cajas fisicas de consolidacion por CD con la logica BAT vigente (`bat.consolidar_bat_por_cd`)."""
    from src import bat

    if esperado.empty:
        return {}
    df = esperado.rename(columns={"Unidades": "Unidades"}).copy()
    return {cd: len(cajas) for cd, cajas in bat.consolidar_bat_por_cd(df).items()}


def hoja_cigarros_vapes(filas_pipeline: list[dict], maestro):
    """Arma la hoja `Cigarros_Vapes` (detalle por SKU + resumen por CD) a partir de lo que el pipeline REALMENTE emite
    (`ResultadoPipeline.demanda_cigarros_df`), agregando Categoria/Subcategoria del Maestro. Si el pipeline omitiera un SKU,
    la hoja lo omite tambien (la conciliacion lo detecta)."""
    import pandas as pd

    df = pd.DataFrame(filas_pipeline)
    if df.empty:
        return pd.DataFrame(columns=COLUMNAS_HOJA_BAT), pd.DataFrame(columns=["CD", "SKUs", "Unidades_Total_CD", "Cajas_Teoricas_Total_CD", "Cajas_Consolidacion_CD"])
    m = maestro.copy()
    m["SKU"] = m["SKU"].astype(str).str.strip()
    m = m.drop_duplicates(subset="SKU")
    cols = ["SKU", "Categoría"] + (["Subcategoría"] if "Subcategoría" in m.columns else [])
    df["SKU"] = df["SKU"].astype(str).str.strip()
    df = df.merge(m[cols], on="SKU", how="left")
    if "Subcategoría" not in df.columns:
        df["Subcategoría"] = None
    det = pd.DataFrame({"CD": df["CD"], "SKU": df["SKU"], "Descripción": df["Descripcion"], "Categoría": df["Categoría"], "Subcategoría": df["Subcategoría"],
                        "Unidades": df["Unidades_Demanda"], "Cajas_Teoricas": df["Cajas_Teoricas"],
                        "Cajas_Consolidacion_CD": df["Cajas_Consolidacion_Necesarias_CD"]}).sort_values(["CD", "SKU"]).reset_index(drop=True)
    res = det.groupby("CD", as_index=False).agg(SKUs=("SKU", "nunique"), Unidades_Total_CD=("Unidades", "sum"), Cajas_Teoricas_Total_CD=("Cajas_Teoricas", "sum"),
                                                Cajas_Consolidacion_CD=("Cajas_Consolidacion_CD", "max"))
    return det[COLUMNAS_HOJA_BAT], res


def conciliar_bat(cd: str, esperado, hoja_det, skus_en_pallets: set, consol_esperada: dict) -> dict:
    """Conciliacion de BAT por CD (perdida cero): SKUs, unidades, cajas teoricas y consolidaciones entre el input (definicion de
    negocio) y la hoja `Cigarros_Vapes` que emite el pipeline; ademas, ningun SKU BAT puede estar en un pallet cubicado."""
    e = esperado[esperado["CD"] == cd]
    h = hoja_det[hoja_det["CD"] == cd] if len(hoja_det) else hoja_det
    sk_e, sk_h = set(e["SKU"]), set(h["SKU"]) if len(h) else set()
    u_e, u_h = float(e["Unidades"].sum()), float(h["Unidades"].sum()) if len(h) else 0.0
    c_e, c_h = float(e["Cajas Teóricas"].sum()), float(h["Cajas_Teoricas"].sum()) if len(h) else 0.0
    k_e = consol_esperada.get(cd, 0)
    k_h = int(h["Cajas_Consolidacion_CD"].max()) if len(h) else 0
    en_pallets = sorted(sk_e & set(skus_en_pallets))
    motivos = []
    if sk_e - sk_h:
        motivos.append(f"SKUs_BAT_FALTAN_EN_HOJA({len(sk_e - sk_h)}): {sorted(sk_e - sk_h)[:8]}")
    if sk_h - sk_e:
        motivos.append(f"SKUs_EN_HOJA_NO_BAT({len(sk_h - sk_e)})")
    if abs(u_e - u_h) > 1e-6:
        motivos.append(f"UNIDADES_BAT_entrada({u_e:g})!=hoja({u_h:g})")
    if abs(c_e - c_h) > 1e-6:
        motivos.append(f"CAJAS_TEORICAS_BAT_entrada({c_e:g})!=hoja({c_h:g})")
    if k_e != k_h:
        motivos.append(f"CONSOLIDACION_esperada({k_e})!=hoja({k_h})")
    if en_pallets:
        motivos.append(f"SKUs_BAT_DENTRO_DEL_CUBICAJE({len(en_pallets)}): {en_pallets[:8]}")
    return {"skus_entrada": len(sk_e), "skus_hoja": len(sk_h), "unidades_entrada": u_e, "unidades_hoja": u_h, "cajas_teoricas_entrada": round(c_e, 6),
            "cajas_teoricas_hoja": round(c_h, 6), "consolidaciones_esperadas": k_e, "consolidaciones_hoja": k_h, "skus_bat_en_pallets": en_pallets,
            "gate_bat": "FAIL_BAT_ROUTING" if motivos else "PASS_BAT_ROUTING", "motivos_bat": motivos}


def cobertura_operacional(gate_a: str, gate_bat: str) -> str:
    """PASS_OPERATIONAL_COVERAGE solo si pasan el cubicaje (N fijo) Y el ruteo BAT. El peso es informativo (no participa)."""
    return "PASS_OPERATIONAL_COVERAGE" if gate_a == "PASS_FIXED_N_GEOMETRY" and gate_bat == "PASS_BAT_ROUTING" else "FAIL_OPERATIONAL_COVERAGE"


def etapa_cierre(pallets, faltantes: int) -> dict:
    """Etapa que cerro la demanda, SOLO desde la metadata que RC1 ya deja en los pallets finales (`rescue_stats`, `repair_stats`,
    `exact_repair_stats`, `global_rescue_stats`); sin monkeypatch, sin mirar tiempos. `rescue_stats` se escribe siempre al final de
    una cascada activada; `global_rescue_stats` solo si Global corrio. Repair/Exact no dejan una marca confiable en los pallets finales
    (pueden perderse si una etapa posterior reemplaza el pallet), asi que esos cierres quedan como NOT_EXPOSED_BY_RC1."""
    md: dict = {}
    for p in pallets:
        for k in ("rescue_stats", "repair_stats", "exact_repair_stats", "global_rescue_stats"):
            if k in p.metadata and k not in md:
                md[k] = p.metadata[k]
    rescue, glob = md.get("rescue_stats"), md.get("global_rescue_stats")
    colocadas = sum(t.cantidad for p in pallets for t in p.torres)
    det = {"cascada_activada": rescue is not None, "global_ejecutado": glob is not None,
           "global_motivo_stop": (glob or {}).get("motivo_stop"), "rescue_cajas_antes": (rescue or {}).get("rescue_cajas_antes"),
           "rescue_cajas_despues": (rescue or {}).get("rescue_cajas_despues")}
    if faltantes == 0:
        if rescue is None:
            etapa = "DFS_LNS"
        elif glob is not None:
            etapa = "GLOBAL"
        elif det["rescue_cajas_despues"] == colocadas:
            etapa = "RESCUE"
        else:
            etapa = "NOT_EXPOSED_BY_RC1"
            det["nota"] = "cerro tras Rescue (Repair o Exact); RC1 no expone cual"
    else:
        etapa = "SIN_CIERRE_CASCADA_AGOTADA" if glob is not None else "NOT_EXPOSED_BY_RC1"
    return {"closure_stage": etapa, **det}
