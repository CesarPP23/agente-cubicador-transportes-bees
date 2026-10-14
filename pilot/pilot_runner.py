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


def _una_corrida(envios, maestro, uma, timing_log: Path) -> dict:
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
        resultado = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())
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
        m["wall_s"], m["cpu_s"] = t.get("wall_s"), t.get("cpu_s")
        m["ids"] = sorted(p.id for p in pals)
        cds[cd] = m
    publico = {"plan_picking_sha": pc.sha16(resultado.plan_picking_df.to_csv(index=True)),
               "resumen_cd_sha": pc.sha16(resultado.resumen_cd_df.to_csv(index=True))}
    return {"wall_batch_s": round(wall, 1), "cpu_batch_s": round(cpu, 1), "cds": cds, "publico": publico}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--operacion", default=None)
    ap.add_argument("--cds", default=None, help="subconjunto de CDs (lista separada por comas)")
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

    registro = {"run_id": run_id, "fecha": datetime.now().isoformat(timespec="seconds"), "case_id": case_id,
                "input": {"archivo": str(inp), "sha256": h_full, "hash": h_full[:16], "filas_envios": None},
                "version": ver, "nota": a.nota, "repeat": a.repeat, "excepcion": None, "corridas": [], "cds": {}}
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
        for i in range(max(1, a.repeat)):
            try:
                corridas.append(_una_corrida(envios, maestro, uma, timing_log))
            except Exception as e:  # noqa: BLE001 -toda excepcion del pipeline se registra como PILOT_EXCEPTION
                registro["excepcion"] = {"tipo": type(e).__name__, "mensaje": str(e), "traceback": traceback.format_exc(), "repeticion": i + 1}
                break
    except Exception as e:  # noqa: BLE001 -input ilegible / hojas faltantes / CSV de operacion invalido
        registro["excepcion"] = {"tipo": type(e).__name__, "mensaje": str(e), "traceback": traceback.format_exc(), "repeticion": 0}
        operacion = {}
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

    exc_motivos: dict = {}
    ultimo = corridas[-1] if corridas else None
    if registro["excepcion"]:
        exc_motivos["_RUN"] = ["EXCEPTION"]
    if not ver["solver_matches_rc1"]:
        exc_motivos["_RUN"] = exc_motivos.get("_RUN", []) + ["SOLVER_MISMATCH"]
    for cd, m in (corridas[0]["cds"].items() if corridas else []):
        op = operacion.get(cd, {})
        clase, dif = pc.clasificar(m, op.get("n_pallets_operacion"))
        motivos = []
        if clase in ("INVALID", "WORSE"):
            motivos.append(clase)
        if cd in divergencia:
            motivos.append("DIVERGENCIA_ENTRE_REPETICIONES")
        registro["cds"][cd] = {**m, "clasificacion": clase, "n_pallets_operacion": op.get("n_pallets_operacion"), "diferencia_vs_operacion": dif,
                               "resultado_fisico": op.get("resultado_fisico"), "observaciones": op.get("observaciones"),
                               "wall_s_repeticiones": [c["cds"][cd]["wall_s"] for c in corridas if cd in c["cds"]], "pilot_exception": bool(motivos), "motivos": motivos}
        if motivos:
            exc_motivos[cd] = motivos
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
        print(f"  {cd}: N={r['n_pallets']} cajas={r['cajas_colocadas']}/{r['demanda_cajas']} falt={r['faltantes']} err={r['errores']} "
              f"{r['origen']} COMP={r['comp']} LAYOUT={r['layout']} wall={r['wall_s']}s -> {r['clasificacion']}{' PILOT_EXCEPTION' if r['pilot_exception'] else ''}")
    if registro["excepcion"]:
        print("  EXCEPCION:", registro["excepcion"]["tipo"], registro["excepcion"]["mensaje"][:200])
    print(f"  registro: {out / 'run.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
