"""Piloto controlado V6.12-RC1 -runner. Corre el pipeline REAL (camino abierto, N elegido por el cubicador) sobre un
dataset real y guarda un registro por CD en pilot/runs/<run_id>/run.json.

Instrumentacion SOLA de medicion: envuelve `armar_pallets_bloques` con un cronometro (fork-safe, JSONL). No cambia
ningun resultado del solver (verificado en V6.12 F4 vs F2: hashes identicos). El runner se NIEGA a correr si
src/, config.py o models.py difieren del tag v6.12-rc1 (o tienen cambios sin commitear): el piloto no recalibra RC1.

Uso:
    .venv/bin/python pilot/pilot_runner.py --input RUTA/plan.xlsx [--case-id ID] [--operacion operacion.csv]
        [--cds BK31,SJ97] [--repeat 2] [--out-dir pilot/runs] [--nota "texto"]

Entrada: un .xlsx con las hojas `Envios_Julio`, `Maestro_SKUs` y `UMA` (mismo formato que Cubicaje18.07.2026.xlsx)."""
import argparse
import json
import os
import resource
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402

import pilot_common as pc  # noqa: E402


def _cronometrar_cds(timing_log: Path):
    """Envuelve `pipeline_sku_bloque.armar_pallets_bloques` (lo llama cada worker de CD) para registrar wall/CPU por CD."""
    import src.pipeline_sku_bloque as psb

    original = psb.armar_pallets_bloques

    def _wrap(grupo, cd, *a, **k):
        c0, w0 = time.process_time(), time.time()
        r = original(grupo, cd, *a, **k)
        with open(timing_log, "a") as f:
            f.write(json.dumps({"cd": cd, "cpu_s": round(time.process_time() - c0, 2), "wall_s": round(time.time() - w0, 2), "pid": os.getpid()}) + "\n")
        return r

    psb.armar_pallets_bloques = _wrap
    return original, psb


def _una_corrida(envios, maestro, uma, timing_log: Path, pobj: dict | None = None) -> dict:
    import config
    import src.pipeline_sku_bloque as psb
    from src.packing_bloques import _area_union_xy
    from src.pipeline import ejecutar_pipeline
    from src.validacion_v5 import validar_pallet_v5

    if timing_log.exists():
        timing_log.unlink()
    original, mod = _cronometrar_cds(timing_log)
    r0 = resource.getrusage(resource.RUSAGE_SELF); c0 = resource.getrusage(resource.RUSAGE_CHILDREN); w0 = time.time()
    try:
        resultado = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy(), pallets_objetivo_por_cd=pobj)
    finally:
        mod.armar_pallets_bloques = original
    wall = time.time() - w0
    r1 = resource.getrusage(resource.RUSAGE_SELF); c1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (r1.ru_utime + r1.ru_stime - r0.ru_utime - r0.ru_stime) + (c1.ru_utime + c1.ru_stime - c0.ru_utime - c0.ru_stime)

    tiempos: dict = {}
    if timing_log.exists():
        for line in timing_log.read_text().splitlines():
            t = json.loads(line)
            tiempos[t["cd"]] = t
    por_cd: dict = {}
    for p in resultado.pallets_v5 or []:
        por_cd.setdefault(p.cd, []).append(p)
    cds = {}
    for cd, pals in sorted(por_cd.items()):
        m = pc.metricas_cd(pals, psb._firma_pallet_canonica, validar_pallet_v5, config, _area_union_xy)
        t = tiempos.get(cd, {})
        if pobj and cd in pobj and m["origen"] == "GREEDY_O_PALLETS_OBJETIVO":
            m["origen"] = "PALLETS_OBJETIVO"  # CD resuelto por el camino de N fijo (sin witness ni materializacion abierta)
        m["wall_s"], m["cpu_s"] = t.get("wall_s"), t.get("cpu_s")
        m["ids"] = sorted(p.id for p in pals)
        cds[cd] = m
    cig = resultado.demanda_cigarros_df if resultado.demanda_cigarros_df is not None else pd.DataFrame()
    publico = {"plan_picking_sha": pc.sha16(resultado.plan_picking_df.to_csv(index=True)),
               "resumen_cd_sha": pc.sha16(resultado.resumen_cd_df.to_csv(index=True)),
               "cigarros_vapes_sha": pc.sha16(cig.to_csv(index=True))}
    skus_pallets = {cd: sorted({t.sku for p in pals for t in p.torres}) for cd, pals in por_cd.items()}
    return {"wall_batch_s": round(wall, 1), "cpu_batch_s": round(cpu, 1), "cds": cds, "publico": publico,
            "cigarros_filas": cig.to_dict("records"), "skus_en_pallets": skus_pallets}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--operacion", default=None)
    ap.add_argument("--cds", default=None, help="subconjunto de CDs (lista separada por comas)")
    ap.add_argument("--mode", choices=["OPEN", "FIXED_N"], default="OPEN",
                    help="FIXED_N: usa la hoja Pallets_Objetivo (posiciones reales y obligatorias) con el cargador oficial; gates A/B/C")
    ap.add_argument("--bat-handling", choices=list(pc.BAT_MANEJO), default="UNCONFIRMED",
                    help="como opera BAT: A dentro de los N pallets / B fuera de ellos / C posicion adicional. Solo se registra")
    ap.add_argument("--repeat", type=int, default=1, help=">1 compara las repeticiones (COMP/LAYOUT/N): divergencia => PILOT_EXCEPTION")
    ap.add_argument("--out-dir", default=str(HERE / "runs"))
    ap.add_argument("--nota", default=None)
    ap.add_argument("--allow-solver-mismatch", action="store_true", help="SOLO diagnostico: marca la corrida como invalida para el piloto")
    a = ap.parse_args()

    ver = pc.verificar_version()
    if not ver["solver_matches_rc1"] and not a.allow_solver_mismatch:
        print("ABORTADO: el solver no coincide con", pc.RC_TAG, "->", ver["solver_diffs"], file=sys.stderr)
        return 2

    inp = Path(a.input).resolve()
    case_id = a.case_id or inp.stem
    h_full = pc.hash_archivo(inp)
    run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{case_id}_{h_full[:8]}"
    out = Path(a.out_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)

    reconciliacion: dict = {}
    bat_esp, consol_esp, maestro = None, {}, None
    registro = {"run_id": run_id, "fecha": datetime.now().isoformat(timespec="seconds"), "case_id": case_id,
                "input": {"archivo": str(inp), "sha256": h_full, "hash": h_full[:16], "filas_envios": None},
                "version": ver, "nota": a.nota, "repeat": a.repeat, "mode": a.mode, "excepcion": None, "corridas": [], "cds": {}}
    envios = None
    corridas, timing_log = [], out / "_timing.jsonl"
    try:
        operacion = pc.leer_operacion(a.operacion, case_id)
        envios = pd.read_excel(inp, sheet_name="Envios_Julio")
        maestro = pd.read_excel(inp, sheet_name="Maestro_SKUs")
        uma = pd.read_excel(inp, sheet_name="UMA")
        if a.cds:
            keep = {c.strip() for c in a.cds.split(",")}
            envios = envios[envios["CD"].isin(keep)]
        registro["input"]["filas_envios"] = int(len(envios))
        pobj = None
        if a.mode == "FIXED_N":
            pobj_todo = pc.cargar_pallets_objetivo(inp)
            if not pobj_todo:
                raise ValueError("--mode FIXED_N pero el input no trae una hoja Pallets_Objetivo valida")
            cds_en = set(envios["CD"].astype(str).str.strip())
            pobj = {cd: n for cd, n in pobj_todo.items() if cd in cds_en}
            faltan = sorted(cds_en - set(pobj))
            if faltan:
                raise ValueError(f"CDs con demanda sin Pallets_Objetivo en modo FIXED_N: {faltan}")
        registro["pallets_objetivo"] = pobj
        registro["bat_handling"] = a.bat_handling
        reconciliacion = pc.reconciliar_demanda(envios, maestro, uma, pobj)
        registro["reconciliacion_demanda"] = reconciliacion
        bat_esp = pc.bat_esperado(envios, maestro)
        consol_esp = pc.consolidaciones_contractuales(bat_esp)
        for i in range(max(1, a.repeat)):
            try:
                corridas.append(_una_corrida(envios, maestro, uma, timing_log, pobj))
            except Exception as e:  # noqa: BLE001 -toda excepcion del pipeline se registra como PILOT_EXCEPTION
                registro["excepcion"] = {"tipo": type(e).__name__, "mensaje": str(e), "traceback": traceback.format_exc(), "repeticion": i + 1}
                break
    except Exception as e:  # noqa: BLE001 -input ilegible / hojas faltantes / CSV de operacion invalido
        registro["excepcion"] = {"tipo": type(e).__name__, "mensaje": str(e), "traceback": traceback.format_exc(), "repeticion": 0}
        operacion = {}
        reconciliacion = {}
    if timing_log.exists():
        timing_log.unlink()
    registro["corridas"] = [{"wall_batch_s": c["wall_batch_s"], "cpu_batch_s": c["cpu_batch_s"], **c["publico"]} for c in corridas]

    divergencia: dict = {}
    if len(corridas) > 1:
        base = corridas[0]
        for k, c in enumerate(corridas[1:], start=2):
            for cd in base["cds"]:
                x, y = base["cds"][cd], c["cds"].get(cd)
                if y is None or any(x[f] != y[f] for f in ("n_pallets", "cajas_colocadas", "faltantes", "errores", "comp", "layout", "ids")):
                    divergencia.setdefault(cd, []).append(k)
            if (c["publico"] != base["publico"]):
                divergencia.setdefault("_PUBLICO", []).append(k)

    bat_conc: dict = {}
    if corridas and bat_esp is not None:
        hoja_det, hoja_res = pc.hoja_cigarros_vapes(corridas[0]["cigarros_filas"], maestro)
        with pd.ExcelWriter(out / f"{pc.HOJA_BAT}.xlsx") as w:  # artefacto del piloto (datos reales: no se versiona)
            hoja_det.to_excel(w, sheet_name=pc.HOJA_BAT, index=False)
            hoja_res.to_excel(w, sheet_name="Resumen_CD", index=False)
        for cd in sorted(set(bat_esp["CD"]) | set(hoja_det["CD"]) | set(corridas[0]["cds"])):
            bat_conc[cd] = pc.conciliar_bat(cd, bat_esp, hoja_det, set(corridas[0]["skus_en_pallets"].get(cd, [])), consol_esp)
    registro["bat"] = bat_conc

    exc_motivos: dict = {}
    ultimo = corridas[-1] if corridas else None
    if registro["excepcion"]:
        exc_motivos["_RUN"] = ["EXCEPTION"]
    if not ver["solver_matches_rc1"]:
        exc_motivos["_RUN"] = exc_motivos.get("_RUN", []) + ["SOLVER_MISMATCH"]
    for cd, m in (corridas[0]["cds"].items() if corridas else []):
        op = operacion.get(cd, {})
        rec = reconciliacion.get(cd)
        bconc = bat_conc.get(cd)
        motivos = []
        extra: dict = {}
        if a.mode == "FIXED_N":
            n_obj = (registro.get("pallets_objetivo") or {}).get(cd)
            rep_ok = None if len(corridas) < 2 else (cd not in divergencia and "_PUBLICO" not in divergencia)
            g = pc.gates_fixed_n(m, rec, n_obj, rep_ok)
            clase, dif = g["resultado"], (None if n_obj is None else m["n_pallets"] - n_obj)
            gb = (bconc or {}).get("gate_bat", "FAIL_BAT_ROUTING")
            extra = {"n_objetivo": n_obj, "n_producido": m["n_pallets"], **{k: g[k] for k in ("gate_a", "gate_b", "gate_c", "motivos_fail")},
                     "gate_bat": gb, "motivos_bat": (bconc or {}).get("motivos_bat", ["SIN_CONCILIACION_BAT"]),
                     "cobertura_operacional": pc.cobertura_operacional(g["gate_a"], gb), "reconciliacion": rec, "bat": bconc, "bat_handling": a.bat_handling}
            if gb != "PASS_BAT_ROUTING":
                motivos.append("FAIL_BAT_ROUTING")
            if g["gate_a"] == "FAIL_FIXED_N":
                motivos.append("FAIL_FIXED_N")
            if g["gate_c"] == "DETERMINISM_DIVERGENCE":
                motivos.append("DETERMINISM_DIVERGENCE")
        else:
            clase, dif = pc.clasificar(m, op.get("n_pallets_operacion"))
            if clase in ("INVALID", "WORSE"):
                motivos.append(clase)
        if cd in divergencia and "DETERMINISM_DIVERGENCE" not in motivos:
            motivos.append("DIVERGENCIA_ENTRE_REPETICIONES")
        registro["cds"][cd] = {**m, **extra, "clasificacion": clase, "n_pallets_operacion": op.get("n_pallets_operacion"), "diferencia_vs_operacion": dif,
                               "resultado_fisico": op.get("resultado_fisico"), "observaciones": op.get("observaciones"),
                               "wall_s_repeticiones": [c["cds"][cd]["wall_s"] for c in corridas if cd in c["cds"]], "pilot_exception": bool(motivos), "motivos": motivos}
        if motivos:
            exc_motivos[cd] = motivos
    for cd, bc in bat_conc.items():  # CDs con solo Cigarros/Vapes (sin cubicaje) tambien se concilian
        if cd not in registro["cds"] and bc["gate_bat"] != "PASS_BAT_ROUTING":
            exc_motivos[cd] = ["FAIL_BAT_ROUTING"]
    registro["divergencia"] = divergencia
    registro["wall_batch_s"] = [c["wall_batch_s"] for c in corridas]
    registro["cpu_batch_s"] = [c["cpu_batch_s"] for c in corridas]
    registro["pilot_exception"] = bool(exc_motivos)
    registro["pilot_exception_motivos"] = exc_motivos
    if ultimo is not None:
        registro["publico_sha"] = ultimo["publico"]

    if exc_motivos:  # guardar el input EXACTO (+ extracto por CD) para analisis posterior
        d = Path(a.out_dir).parent / "exceptions" / run_id
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inp, d / inp.name)
        for cd in [c for c in exc_motivos if not c.startswith("_")]:
            if envios is not None:
                envios[envios["CD"] == cd].to_csv(d / f"envios_{cd}.csv", index=False)
        (d / "motivos.json").write_text(json.dumps({"motivos": exc_motivos, "excepcion": registro["excepcion"], "version": ver}, indent=2, default=str))
        registro["input_guardado_en"] = str(d)

    (out / "run.json").write_text(json.dumps(registro, indent=2, default=str))
    print(f"[{run_id}] {ver['version']}  wall_batch={registro['wall_batch_s']}  PILOT_EXCEPTION={registro['pilot_exception']}")
    for cd, r in registro["cds"].items():
        gates = f" [A={r['gate_a']} B={r['gate_b']} C={r['gate_c']} BAT={r['gate_bat']} -> {r['cobertura_operacional']}] N_obj={r['n_objetivo']}" if "gate_a" in r else ""
        print(f"  {cd}: N={r['n_pallets']} cajas={r['cajas_colocadas']}/{r['demanda_cajas']} falt={r['faltantes']} err={r['errores']} "
              f"{r['origen']} COMP={r['comp']} LAYOUT={r['layout']} wall={r['wall_s']}s -> {r['clasificacion']}{gates}{' PILOT_EXCEPTION' if r['pilot_exception'] else ''}")
    if registro["excepcion"]:
        print("  EXCEPCION:", registro["excepcion"]["tipo"], registro["excepcion"]["mensaje"][:200])
    print(f"  registro: {out / 'run.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
