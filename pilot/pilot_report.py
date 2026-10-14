"""Piloto controlado V6.12-RC1 -reporte consolidado. Lee pilot/runs/*/run.json y genera
pilot/report/pilot_table.csv y pilot/report/pilot_report.md (BETTER / EQUIVALENT / WORSE / INVALID + resumen).

Uso:  .venv/bin/python pilot/pilot_report.py [--runs-dir pilot/runs] [--out-dir pilot/report] [--all-runs]
Por defecto se usa, por (case_id, input_hash, CD), solo la ultima corrida; `--all-runs` las incluye todas."""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pilot_common as pc  # noqa: E402

COLS = ["run_id", "fecha", "case_id", "input_hash", "cd", "demanda_cajas", "skus", "n_pallets", "cajas_colocadas", "faltantes", "errores",
        "peso_max", "altura_max", "pallets_parciales", "altura_media", "ocupacion_media", "origen", "optimality_status", "wall_s", "cpu_s",
        "comp", "layout", "version", "n_pallets_operacion", "diferencia_vs_operacion", "resultado_fisico", "observaciones",
        "clasificacion", "pilot_exception", "motivos"]


def cargar(runs_dir: Path, todas: bool) -> tuple[list[dict], list[dict]]:
    filas, fallidas = [], []
    for f in sorted(runs_dir.glob("*/run.json")):
        r = json.loads(f.read_text())
        base = {"run_id": r["run_id"], "fecha": r["fecha"], "case_id": r["case_id"], "input_hash": r["input"]["hash"], "version": r["version"]["version"]}
        if r.get("excepcion"):
            fallidas.append({**base, "tipo": r["excepcion"]["tipo"], "mensaje": r["excepcion"]["mensaje"][:160], "wall_batch_s": r.get("wall_batch_s")})
        if not r["version"]["solver_matches_rc1"]:
            fallidas.append({**base, "tipo": "SOLVER_MISMATCH", "mensaje": "; ".join(r["version"]["solver_diffs"]), "wall_batch_s": r.get("wall_batch_s")})
        for cd, m in r["cds"].items():
            filas.append({**base, "cd": cd, **{k: m.get(k) for k in COLS if k in m}, "motivos": ",".join(m.get("motivos", [])),
                          "wall_batch_s": (r.get("wall_batch_s") or [None])[0]})
    if not todas:
        ult: dict = {}
        for x in filas:
            ult[(x["case_id"], x["input_hash"], x["cd"])] = x  # sorted por run_id (fecha): gana la ultima
        filas = list(ult.values())
    return filas, fallidas


def fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def reporte(filas: list[dict], fallidas: list[dict]) -> str:
    total = len(filas) + len([f for f in fallidas if f["tipo"] != "SOLVER_MISMATCH"])
    cuenta = {c: sum(1 for x in filas if x["clasificacion"] == c) for c in (*pc.CLASES, pc.SIN_OPERACION)}
    cuenta["INVALID"] += len([f for f in fallidas if f["tipo"] != "SOLVER_MISMATCH"])  # una corrida que revento es un caso INVALID
    pct = lambda n: f"{100.0 * n / total:.1f}%" if total else "-"  # noqa: E731
    completos = sum(1 for x in filas if x["faltantes"] == 0 and x["cajas_colocadas"] == x["demanda_cajas"])
    sin_viol = sum(1 for x in filas if x["errores"] == 0)
    con_op = [x for x in filas if x.get("n_pallets_operacion") not in (None, "")]
    walls = [x["wall_s"] for x in filas if x.get("wall_s") is not None]
    batch = sorted({(x["run_id"], x["wall_batch_s"]) for x in filas if x.get("wall_batch_s") is not None})
    p = lambda v, q: fmt(pc.percentil(v, q))  # noqa: E731
    excep = [x for x in filas if x["pilot_exception"]]
    L = [f"# Piloto V6.12-RC1 -reporte consolidado", "", f"Version: {', '.join(sorted({x['version'] for x in filas})) or '-'}  |  casos (CD): {total}", "",
         "## Resumen", "",
         f"- Total casos: **{total}** ({len(filas)} CDs corridos + {total - len(filas)} corridas con excepcion)",
         f"- 100% demanda colocada: **{completos}/{total}** ({pct(completos)})",
         f"- Cero violaciones geometricas: **{sin_viol}/{total}** ({pct(sin_viol)})",
         f"- Clasificacion: BETTER {cuenta['BETTER']} | EQUIVALENT {cuenta['EQUIVALENT']} | WORSE {cuenta['WORSE']} | INVALID {cuenta['INVALID']} | sin dato de operacion {cuenta[pc.SIN_OPERACION]}"]
    if con_op:
        tc, to = sum(x["n_pallets"] for x in con_op), sum(int(x["n_pallets_operacion"]) for x in con_op)
        L.append(f"- Pallets cubicador vs operacion ({len(con_op)} CDs con plan real): **{tc} vs {to}** (diferencia {tc - to:+d}, {100.0 * (tc - to) / to:+.1f}%)" if to else "")
    else:
        L.append("- Pallets cubicador vs operacion: sin datos de operacion cargados")
    L += [f"- Runtime por CD (wall, s): p50 {p(walls, .5)} / p90 {p(walls, .9)} / max {fmt(max(walls) if walls else None)}",
          f"- Runtime del batch (wall, s): {', '.join(f'{w}' for _, w in batch) or '-'}",
          f"- Fallbacks al witness: **{sum(1 for x in filas if x['origen'] == 'WITNESS_FALLBACK')}**",
          f"- Excepciones: PILOT_EXCEPTION {len(excep)} CDs | corridas con excepcion/solver distinto {len(fallidas)}", "",
          "## Tabla consolidada", "",
          "| caso | CD | clase | N cub. | N oper. | dif | cajas | falt. | err | origen | wall s | COMP | LAYOUT | PILOT_EXCEPTION |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    orden = {c: i for i, c in enumerate(("WORSE", "INVALID", "EQUIVALENT", "BETTER", pc.SIN_OPERACION))}
    for x in sorted(filas, key=lambda x: (orden.get(x["clasificacion"], 9), x["case_id"], x["cd"])):
        L.append(f"| {x['case_id']} | {x['cd']} | {x['clasificacion']} | {x['n_pallets']} | {fmt(x.get('n_pallets_operacion'))} | {fmt(x.get('diferencia_vs_operacion'))} | "
                 f"{x['cajas_colocadas']}/{x['demanda_cajas']} | {x['faltantes']} | {x['errores']} | {x['origen']} | {fmt(x.get('wall_s'))} | `{x['comp']}` | `{x['layout']}` | "
                 f"{('SI: ' + x['motivos']) if x['pilot_exception'] else ''} |")
    if fallidas:
        L += ["", "## Corridas con excepcion o solver distinto de RC1", ""] + [f"- `{f['run_id']}` {f['tipo']}: {f['mensaje']}" for f in fallidas]
    if excep:
        L += ["", "## PILOT_EXCEPTION (input guardado en pilot/exceptions/<run_id>/)", ""] + [f"- `{x['run_id']}` {x['cd']}: {x['motivos']}" for x in excep]
    return "\n".join(l for l in L if l is not None) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", default=str(HERE / "runs"))
    ap.add_argument("--out-dir", default=str(HERE / "report"))
    ap.add_argument("--all-runs", action="store_true")
    a = ap.parse_args()
    filas, fallidas = cargar(Path(a.runs_dir), a.all_runs)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    with open(out / "pilot_table.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(filas)
    md = reporte(filas, fallidas)
    (out / "pilot_report.md").write_text(md)
    print(md)
    print(f"-> {out / 'pilot_report.md'}  |  {out / 'pilot_table.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
