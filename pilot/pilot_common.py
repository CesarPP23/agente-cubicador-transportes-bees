"""Piloto controlado V6.12-RC1 -utilidades compartidas (SOLO medicion/reporte).
NO modifica el solver: lee resultados, calcula metricas y clasifica."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RC_TAG = "v6.12-rc1"
SOLVER_PATHS = ["src", "config.py", "models.py"]  # lo que define el comportamiento del solver
CLASES = ("BETTER", "EQUIVALENT", "WORSE", "INVALID")
SIN_OPERACION = "NO_OPERATION_DATA"
# Modo FIXED_N (Pallets_Objetivo = posiciones reales y obligatorias de operacion). Tres gates independientes:
#   A cubicaje:   PASS_FIXED_N_GEOMETRY / FAIL_FIXED_N
#   B peso:       WEIGHT_VALIDATED / WEIGHT_VALIDATION_INCOMPLETE (cajas con peso 0/no validable se computan como 0 kg)
#   C determinismo: REPEAT_MATCH / DETERMINISM_DIVERGENCE / NOT_CHECKED (--repeat 1)
# RESULT final: FAIL_FIXED_N | PASS_FIXED_N_GEOMETRY | PASS_FULL_PHYSICAL_VALIDATION (solo si A, B y C pasan).
BAT_MANEJO = ("A", "B", "C", "UNCONFIRMED")  # A: dentro de los N pallets; B: viaja fuera; C: posicion adicional


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()


def verificar_version() -> dict:
    """Congelamiento: el codigo del solver (src/, config.py, models.py) debe ser BIT A BIT el del tag RC1 y el
    arbol de trabajo no puede tener cambios sobre ellos."""
    rc_commit = _git("rev-parse", f"{RC_TAG}^{{commit}}")
    head = _git("rev-parse", "HEAD")
    diffs = []
    for p in SOLVER_PATHS:
        if _git("rev-parse", f"{RC_TAG}:{p}") != _git("rev-parse", f"HEAD:{p}"):
            diffs.append(f"{p} (HEAD != {RC_TAG})")
        if _git("status", "--porcelain", "--", p):
            diffs.append(f"{p} (cambios sin commitear)")
    return {"version": f"{RC_TAG} / {rc_commit[:7]}", "rc_commit": rc_commit, "head_commit": head,
            "head_branch": _git("rev-parse", "--abbrev-ref", "HEAD"), "solver_matches_rc1": not diffs, "solver_diffs": diffs}


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
        s, ex = t[t["destino"] == "SOLVER"], t[t["destino"] != "SOLVER"]
        c = df_cls[df_cls["CD"] == cd]
        b = df_bat[df_bat["CD"] == cd]
        si = solver_in.get(cd, {})
        pend = int(sum(si.get("pend", {}).values())) if "pend" in si else None
        efectiva_ceil = int(s["techo"].sum())
        motivos = {}
        for m in sorted(ex["destino"].unique()):
            q = ex[ex["destino"] == m]
            motivos[m] = {"skus": int(len(q)), "cajas_teoricas": round(float(q["Cajas Teóricas"].sum()), 3)}
        out[cd] = {
            "n_objetivo": pobj.get(cd), "cajas_originales": round(float(orig.loc[cd, "cajas"]), 3), "skus_originales": int(orig.loc[cd, "skus"]),
            "filas_originales": int(orig.loc[cd, "filas"]), "demanda_efectiva_solver": pend, "skus_solver": int(len(s)),
            "cajas_teoricas_solver": round(float(s["Cajas Teóricas"].sum()), 3), "redondeo_ascendente": round(efectiva_ceil - float(s["Cajas Teóricas"].sum()), 3),
            "cajas_excluidas": round(float(ex["Cajas Teóricas"].sum()), 3), "skus_excluidos": int(len(ex)), "excluidos_por_motivo": motivos,
            "bat_skus": int(b["SKU"].nunique()), "bat_cajas_teoricas": round(float(b["Cajas Teóricas"].sum()), 3), "bat_unidades": int(b["Unidades"].sum()),
            "bat_cajas_consolidacion": len(cajas_bat.get(cd, [])),
            "peso_no_validable_skus_en_solver": int(c["Peso_No_Validable"].sum()),
            "peso_no_validable_cajas_en_solver": int(c.loc[c["Peso_No_Validable"], "Cajas_Remanente"].sum()),
            "geom_degradada_skus_en_solver": int((c["Fuente_Geometria"] == "MAESTRO_IMPOSIBLE_DEGRADADO").sum()),
            "identidad_ok": pend is not None and pend == efectiva_ceil,
        }
    return out


def gates_fixed_n(m: dict | None, rec: dict | None, n_objetivo: int | None, repeticion_ok: bool | None, excepcion: bool = False) -> dict:
    """Gate A (cubicaje), B (peso), C (determinismo) y RESULT. Los Cigarros/BAT excluidos por diseno NO son faltantes
    del solver, y los pesos 0 NO son fallo de cubicaje -pero impiden afirmar PASS_FULL_PHYSICAL_VALIDATION."""
    if excepcion or m is None:
        return {"gate_a": "FAIL_FIXED_N", "gate_b": "WEIGHT_VALIDATION_INCOMPLETE", "gate_c": "NOT_CHECKED", "resultado": "FAIL_FIXED_N",
                "motivos_fail": ["EXCEPTION_O_SIN_RESULTADO"]}
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
    sin_peso = (rec or {}).get("peso_no_validable_cajas_en_solver", 0)
    b = "WEIGHT_VALIDATED" if rec is not None and sin_peso == 0 else "WEIGHT_VALIDATION_INCOMPLETE"
    c = "NOT_CHECKED" if repeticion_ok is None else ("REPEAT_MATCH" if repeticion_ok else "DETERMINISM_DIVERGENCE")
    if a == "FAIL_FIXED_N":
        res = "FAIL_FIXED_N"
    elif b == "WEIGHT_VALIDATED" and c == "REPEAT_MATCH":
        res = "PASS_FULL_PHYSICAL_VALIDATION"
    else:
        res = "PASS_FIXED_N_GEOMETRY"
    return {"gate_a": a, "gate_b": b, "gate_c": c, "resultado": res, "motivos_fail": motivos}
