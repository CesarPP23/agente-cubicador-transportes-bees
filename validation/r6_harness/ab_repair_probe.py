"""A/B por llamada de `_candidatos_lote` (referencia vs variante rápida) sobre los estados REALES del Repair de un sondeo de OPEN. NO cablea la variante rápida al flujo:
el flujo sigue con el resultado de la referencia (idéntico al flujo normal); la rápida solo se ejecuta a la par sobre los mismos argumentos.

  R6_ROOT=<árbol> python ab_repair_probe.py --case SJ97 --n 6 --mode timing --parity-start 0 --out DIR
  R6_ROOT=<árbol> python ab_repair_probe.py --case SJ97 --n 6 --mode parity --out DIR

* Los sondeos de otros N se omiten (devuelven "sin colocar todo", como un sondeo UNKNOWN) para llegar directo al N pedido; el sondeo del N pedido corre de verdad
  (DFS inicial -> Rescue -> Repair) y la corrida termina al volver el Repair. El Repair corre dentro de `_candidatos_rapido()` (la caché se crea al abrir el contexto y
  se reutiliza durante toda la etapa, como en una ejecución real con la variante cableada); cada llamada ejecuta ambas variantes, alternando cuál va primero
  (`--parity-start` invierte la fase de la alternancia entre repeticiones).
* `--mode timing`: solo cronometra (perf_counter_ns por llamada y variante); NO compara salidas. `--mode parity`: compara cada par (contenido, orden, desempates, bits de
  floats, identidad de `TorreCandidate`); una diferencia aborta. Son corridas separadas.
"""
import argparse, json, os, struct, sys, time
from pathlib import Path

ROOT = Path(os.environ.get("R6_ROOT", Path(__file__).resolve().parents[2]))
ap = argparse.ArgumentParser()
ap.add_argument("--case", required=True); ap.add_argument("--n", type=int, required=True); ap.add_argument("--mode", choices=("timing", "parity"), required=True)
ap.add_argument("--parity-start", type=int, default=0); ap.add_argument("--out", required=True); ap.add_argument("--tag", default="")
args = ap.parse_args()
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
import pandas as pd  # noqa
import src.packing_bloques as pb, src.repair_solver as rp  # noqa
from src.validacion_multicd import preparar_demanda_por_cd  # noqa

PC = time.perf_counter_ns


class StopRun(BaseException):
    pass


def bits(x):
    if isinstance(x, float): return struct.pack("<d", x)
    if isinstance(x, (tuple, list)): return tuple(bits(i) for i in x)
    return x


def same(exp, got):
    if len(exp) != len(got): return False
    for e, g in zip(exp, got):
        if bits(e[0]) != bits(g[0]) or (e[1], e[2], e[3], e[5], e[6]) != (g[1], g[2], g[3], g[5], g[6]): return False
        if type(e[1]) is not type(g[1]) or type(e[6]) is not type(g[6]) or e[4] is not g[4]: return False
    return True


REC = {"calls": 0, "ref": [], "fast": [], "ref_first": [], "mismatch": 0, "stage": {}}


def ab(*a):
    i = REC["calls"]; REC["calls"] += 1
    ref_first = ((i + args.parity_start) % 2 == 0)
    if args.mode == "parity":
        r_ref = pb._candidatos_lote_referencia(*a); r_fast = pb._candidatos_lote_rapido(*a)
        if not same(r_ref, r_fast):
            REC["mismatch"] += 1
            raise SystemExit(f"PARITY MISMATCH call {i}")
        return r_ref
    if ref_first:
        t0 = PC(); r_ref = pb._candidatos_lote_referencia(*a); t1 = PC(); pb._candidatos_lote_rapido(*a); t2 = PC()
        REC["ref"].append(t1 - t0); REC["fast"].append(t2 - t1)
    else:
        t0 = PC(); pb._candidatos_lote_rapido(*a); t1 = PC(); r_ref = pb._candidatos_lote_referencia(*a); t2 = PC()
        REC["fast"].append(t1 - t0); REC["ref"].append(t2 - t1)
    REC["ref_first"].append(ref_first)
    return r_ref


def load_case(case):
    x = ROOT / "Cubicaje18.07.2026.xlsx"
    df = preparar_demanda_por_cd(pd.read_excel(x, sheet_name="Envios_Julio"), pd.read_excel(x, sheet_name="Maestro_SKUs"), pd.read_excel(x, sheet_name="UMA"))
    return df[df["CD"] == case]


def main():
    df = load_case(args.case)
    enp0 = pb._empacar_n_pallets

    def enp(*a, **k):
        n = a[7] if len(a) > 7 else k.get("n_pallets")
        if k.get("presupuesto_repair_nodos") is not None and k.get("con_lns") is False and n != args.n:
            return [], dict(a[0])                      # sondeo de otro N: se omite (UNKNOWN)
        return enp0(*a, **k)

    pb._empacar_n_pallets = enp
    rp0 = rp.repair_solver

    def repair(*a, **k):
        if k.get("presupuesto_nodos") is None:
            return rp0(*a, **k)
        l0 = pb._candidatos_lote
        t0 = time.process_time()
        with pb._candidatos_rapido():
            pb._candidatos_lote = ab
            try:
                rp0(*a, **k)
            finally:
                pb._candidatos_lote = l0
        REC["stage"]["repair_cpu_s_incl_ab"] = round(time.process_time() - t0, 3)
        raise StopRun()

    rp.repair_solver = repair
    try:
        pb.armar_pallets_bloques(df, args.case, contador=[0], pallets_objetivo=None, paralelo_lns=False)
    except StopRun:
        pass
    else:
        raise SystemExit("el Repair de sondeo no se ejecutó")
    out = {"case": args.case, "n": args.n, "mode": args.mode, "parity_start": args.parity_start, "calls": REC["calls"], "mismatch": REC["mismatch"], "root": str(ROOT)}
    if args.mode == "timing":
        r, f, o = REC["ref"], REC["fast"], REC["ref_first"]
        out.update(ref_total_s=sum(r) / 1e9, fast_total_s=sum(f) / 1e9, **REC["stage"])
        out["saving_s"] = out["ref_total_s"] - out["fast_total_s"]; out["saving_pct"] = 100 * out["saving_s"] / out["ref_total_s"]
        for name, sel in (("ref_first", True), ("fast_first", False)):
            rr = sum(x for x, k in zip(r, o) if k is sel); ff = sum(x for x, k in zip(f, o) if k is sel)
            out[name] = {"calls": sum(1 for k in o if k is sel), "ref_s": rr / 1e9, "fast_s": ff / 1e9, "saving_pct": 100 * (rr - ff) / rr if rr else None}
        srt = sorted(zip(r, f)); q = lambda p: srt[int(p * (len(srt) - 1))]
        out["ref_us_per_call"] = out["ref_total_s"] * 1e6 / max(1, len(r)); out["fast_us_per_call"] = out["fast_total_s"] * 1e6 / max(1, len(f))
        out["fast_faster_fraction"] = sum(1 for x, y in zip(r, f) if y < x) / max(1, len(r))
        # ahorro por cuartiles de costo de la llamada de referencia
        n4 = len(srt) // 4
        out["by_ref_cost_quartile"] = [{"q": i + 1, "ref_us": sum(x for x, _ in srt[i * n4:(i + 1) * n4 if i < 3 else None]) / max(1, len(srt[i * n4:(i + 1) * n4 if i < 3 else None])) / 1e3,
                                        "saving_pct": 100 * (1 - sum(y for _, y in srt[i * n4:(i + 1) * n4 if i < 3 else None]) / max(1, sum(x for x, _ in srt[i * n4:(i + 1) * n4 if i < 3 else None])))} for i in range(4)]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    fn = Path(args.out) / f"ab_{args.case}_N{args.n}_{args.mode}_{args.parity_start}{args.tag}.json"
    json.dump(out, open(fn, "w"), indent=1)
    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items() if k not in ("by_ref_cost_quartile", "ref_first", "fast_first", "root")}), flush=True)


main()
