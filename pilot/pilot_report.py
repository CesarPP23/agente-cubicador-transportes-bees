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
        "clasificacion", "pilot_exception", "motivos", "n_objetivo", "n_producido", "gate_a", "gate_b", "gate_c", "motivos_fail", "bat_handling", "gate_bat", "cobertura_operacional"]


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
                          "motivos_fail": ",".join(m.get("motivos_fail", []) or []), "reconciliacion": m.get("reconciliacion"), "bat": m.get("bat"), "motivos_bat": m.get("motivos_bat"),
                          "wall_batch_s": (r.get("wall_batch_s") or [None])[0], "cpu_batch_s": (r.get("cpu_batch_s") or [None])[0]})
    if not todas:
        ult: dict = {}
        for x in filas:
            ult[(x["case_id"], x["input_hash"], x["cd"])] = x  # sorted por run_id (fecha): gana la ultima
        filas = list(ult.values())
    return filas, fallidas


def gnum(x):
    return "-" if x is None else f"{x:g}"


def fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def reporte(filas: list[dict], fallidas: list[dict]) -> str:
    total = len(filas) + len([f for f in fallidas if f["tipo"] != "SOLVER_MISMATCH"])
    fixed = [x for x in filas if x.get("gate_a")]
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
    if fixed:
        L += reporte_fixed_n(fixed)
    if fallidas:
        L += ["", "## Corridas con excepcion o solver distinto de RC1", ""] + [f"- `{f['run_id']}` {f['tipo']}: {f['mensaje']}" for f in fallidas]
    if excep:
        L += ["", "## PILOT_EXCEPTION (input guardado en pilot/exceptions/<run_id>/)", ""] + [f"- `{x['run_id']}` {x['cd']}: {x['motivos']}" for x in excep]
    return "\n".join(l for l in L if l is not None) + "\n"


def reporte_fixed_n(fixed: list[dict]) -> list[str]:
    """Seccion FIXED_N: Pallets_Objetivo = posiciones reales y obligatorias del cubicador. Cigarros/Vapes (BAT) NO consumen N, no
    participan en geometria ni ocupacion y no son faltantes: es demanda ATENDIDA por otro flujo (hoja `Cigarros_Vapes`).
    Gates: A cubicaje, B peso, C determinismo, BAT ruteo; cobertura operacional = A y BAT."""
    cnt = lambda k, v: sum(1 for x in fixed if x.get(k) == v)  # noqa: E731
    L = ["", "## FIXED_N: resultados por CD", "",
         f"- RESULT (A/B/C): PASS_FULL_PHYSICAL_VALIDATION {cnt('clasificacion', 'PASS_FULL_PHYSICAL_VALIDATION')} | PASS_FIXED_N_GEOMETRY {cnt('clasificacion', 'PASS_FIXED_N_GEOMETRY')} | FAIL_FIXED_N {cnt('clasificacion', 'FAIL_FIXED_N')}",
         f"- Gate A (cubicaje): PASS {cnt('gate_a', 'PASS_FIXED_N_GEOMETRY')}/{len(fixed)} | Gate B (peso): WEIGHT_VALIDATED {cnt('gate_b', 'WEIGHT_VALIDATED')}, "
         f"WEIGHT_VALIDATION_INCOMPLETE {cnt('gate_b', 'WEIGHT_VALIDATION_INCOMPLETE')} | Gate C (determinismo): REPEAT_MATCH {cnt('gate_c', 'REPEAT_MATCH')}, "
         f"DETERMINISM_DIVERGENCE {cnt('gate_c', 'DETERMINISM_DIVERGENCE')}, NOT_CHECKED {cnt('gate_c', 'NOT_CHECKED')}",
         f"- Gate BAT (ruteo): PASS_BAT_ROUTING {cnt('gate_bat', 'PASS_BAT_ROUTING')}/{len(fixed)} | Cobertura operacional (A y BAT): PASS_OPERATIONAL_COVERAGE {cnt('cobertura_operacional', 'PASS_OPERATIONAL_COVERAGE')}/{len(fixed)}", "",
         "| CD | N obj. | N prod. | demanda original (cajas teor.) | demanda cubicable | efectiva solver | colocada | otras exclusiones (motivo) | faltantes | errores | peso max* | altura max | altura media | parciales | ocupacion | COMP | LAYOUT | wall s | CPU s | A | B | C | BAT | RESULT | cobertura operacional |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in sorted(fixed, key=lambda x: x["cd"]):
        r = x.get("reconciliacion") or {}
        mot = "; ".join(f"{k}: {v['skus']} SKU/{v['cajas_teoricas']} cj" for k, v in (r.get("otras_exclusiones_por_motivo") or {}).items()) or "ninguna"
        L.append(f"| {x['cd']} | {x.get('n_objetivo')} | {x.get('n_producido')} | {fmt(r.get('cajas_originales'), 3)} ({r.get('skus_originales', '-')} SKU) | {fmt(r.get('demanda_cubicable'), 3)} | {r.get('demanda_efectiva_solver', '-')} ({r.get('skus_solver', '-')} SKU) | "
                 f"{x['cajas_colocadas']} | {mot} | {x['faltantes']} | {x['errores']} | {fmt(x.get('peso_max'))} | {fmt(x.get('altura_max'))} | {fmt(x.get('altura_media'))} | {x.get('pallets_parciales')} | "
                 f"{fmt(x.get('ocupacion_media'), 3)} | `{x['comp']}` | `{x['layout']}` | {fmt(x.get('wall_s'))} | {fmt(x.get('cpu_s'))} | {x.get('gate_a')} | {x.get('gate_b')} | {x.get('gate_c')} | {x.get('gate_bat')} | **{x['clasificacion']}** | **{x.get('cobertura_operacional')}** |")
    L += ["", "\\* El peso maximo computa como 0 kg las cajas con peso no validable (WEIGHT_VALIDATION_INCOMPLETE): es un limite inferior, no un peso validado.", "",
          "## Cigarros / Vapes: demanda separada hacia la hoja `Cigarros_Vapes` (no es demanda excluida)", "",
          "Flujo: demanda total -> (demanda no BAT -> cubicador, consume N) + (Cigarros/Vapes -> hoja `Cigarros_Vapes` para el HUB). BAT no consume N, no modifica `Pallets_Objetivo`, "
          "no participa en geometria ni ocupacion y no cuenta como faltante. Artefacto por corrida: `pilot/runs/<run_id>/Cigarros_Vapes.xlsx` (hojas `Cigarros_Vapes` con detalle SKU y `Resumen_CD`).", "",
          "| CD | N obj. | cajas cubicadas | demanda Cigarros/Vapes separada (cajas teor.) | original = cubicable + BAT | SKUs BAT entrada / hoja | unidades BAT entrada / hoja | consolidaciones esperadas / hoja | BAT dentro del cubicaje | gate BAT |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in sorted(fixed, key=lambda x: x["cd"]):
        r, b = x.get("reconciliacion") or {}, x.get("bat") or {}
        L.append(f"| {x['cd']} | {x.get('n_objetivo')} | {x['cajas_colocadas']} en {x.get('n_producido')} pallets | {r.get('demanda_cigarros_vapes_cajas_teoricas', '-')} | "
                 f"{'OK' if r.get('identidad_original_cubicable_bat') else 'NO CIERRA'} | {b.get('skus_entrada', '-')} / {b.get('skus_hoja', '-')} | {gnum(b.get('unidades_entrada'))} / {gnum(b.get('unidades_hoja'))} | "
                 f"{b.get('consolidaciones_esperadas', '-')} / {b.get('consolidaciones_hoja', '-')} | {len(b.get('skus_bat_en_pallets', []))} | **{x.get('gate_bat')}** |")
    malos = [x for x in fixed if x.get("gate_bat") != "PASS_BAT_ROUTING"]
    if malos:
        L += ["", "### FAIL_BAT_ROUTING", ""] + [f"- {x['cd']}: {'; '.join(x.get('motivos_bat') or [])}" for x in malos]
    pw = [x for x in fixed if (x.get("reconciliacion") or {}).get("peso_no_validable_cajas_en_solver")]
    if pw:
        L += ["", "## WEIGHT_VALIDATION_INCOMPLETE", ""] + [f"- {x['cd']}: {x['reconciliacion']['peso_no_validable_skus_en_solver']} SKU / {x['reconciliacion']['peso_no_validable_cajas_en_solver']} cajas con peso no validable (computadas como 0 kg)" for x in sorted(pw, key=lambda x: x['cd'])]
    L += ["", "## Requerimientos de producto detectados (NO se modifican durante el piloto)", "",
          "El exportador productivo hoy emite la hoja `Cigarros` (`exportar.construir_demanda_cigarros_df`) con columnas `CD, Nombre_CD, SKU, Descripcion, Unidades_Demanda, Unidades_Por_Caja, Cajas_Teoricas, Total_Unidades_CD, Cajas_Consolidacion_Necesarias_CD`. Frente al contrato operacional:",
          "- la hoja se llama `Cigarros`, no `Cigarros_Vapes`;", "- faltan `Categoría` y `Subcategoría` en el detalle, y la columna se llama `Cajas_Consolidacion_Necesarias_CD` (contrato: `Cajas_Consolidacion_CD`);",
          "- `config.SUBCATEGORIAS_BAT = {\"vapes\"}` no coincide con la Subcategoría `Vape` (singular) del Maestro: hoy los vapes salen a BAT solo si su Categoría es `Cigarros`. Un vape con otra Categoría quedaría DENTRO del cubicaje (el gate BAT lo detecta con la definición de negocio).", ""]
    return L


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
