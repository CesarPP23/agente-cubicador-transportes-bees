"""Arnés de validación V6.13-R6 (observación pura: no cambia el comportamiento de lo medido; solo envuelve funciones para contar/cronometrar/comparar).

  R6_ROOT=<árbol> python harness.py --case SJ97 --tag nombre --out DIR [--dfs] [--shadow-cl] [--shadow-podar]

Por corrida guarda: resultado (N, cajas, faltantes, errores, COMP, LAYOUT, hash de atributos, fuente), hash de la metadata aplanada sin campos temporales
(floats a 6 decimales) + la metadata aplanada, contadores de trabajo, CPU de armado, pico de memoria (RSS), y por FASE (etiqueta = innermost de
probe/N#, final/N#, deep, fallback, other/N# + subetapas rescue/repair/exact/global, y el sufijo ':lns' dentro de `_lns_mejorar_pallets`):
llamadas y CPU de `_candidatos_lote` (total y con la variante rápida activa) y de `_podar_libres`, CPU de etapa. Sin `--dfs` no se envuelve el DFS
(envolverlo infla el CPU); con `--dfs` también cuenta nodos/paradas del DFS, iteraciones del LNS y un hash de secuencia por etapa.
`--shadow-cl`: cada llamada real a `_candidatos_lote` se vuelve a calcular con `_candidatos_lote_referencia` y se compara (contenido, orden, desempates,
bits de floats, identidad de `TorreCandidate`); una diferencia aborta la corrida.
"""
import argparse, dataclasses, hashlib, json, os, re, resource, struct, sys, time
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("R6_ROOT", Path(__file__).resolve().parents[2]))  # árbol a medir (raíz del repo o un `git archive` de la base)
PILOT_XLSX = os.environ.get("R6_PILOT_XLSX", "")  # solo BK35/BK46; archivo CONFIDENCIAL local, nunca se copia ni se versiona
ap = argparse.ArgumentParser()
ap.add_argument("--case", required=True); ap.add_argument("--tag", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--dfs", action="store_true"); ap.add_argument("--shadow-cl", action="store_true"); ap.add_argument("--shadow-podar", action="store_true")
args = ap.parse_args()
OUT = Path(args.out).resolve(); PT = time.process_time
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests")); os.chdir(ROOT)
import pandas as pd  # noqa
import src.exact_repair as ex, src.global_rescue as gr, src.packing_bloques as pb, src.packing_columnar as pc  # noqa
import src.pipeline_sku_bloque as psb, src.repair_solver as rp, src.rescue_solver as rs, src.validacion_v5 as v5  # noqa
from src.validacion_multicd import preparar_demanda_por_cd  # noqa

TAGS = ["other"]
POD = defaultdict(lambda: {"calls": 0, "cpu": 0.0})
CL = defaultdict(lambda: {"calls": 0, "cpu": 0.0, "calls_fast": 0, "cpu_fast": 0.0})
CNT = defaultdict(int)
STAGE_CPU = defaultdict(float)
DFS = defaultdict(lambda: {"calls": 0, "nodes": 0, "stops": defaultdict(int)})
LNS = defaultdict(lambda: {"calls": 0, "iterations": 0})
SEQ = []
LNSDEPTH = [0]
WIT = {"enp_returns": [], "witness_events": [], "witness_at_final": None}


def _patch(orig, new, name):
    for m in list(sys.modules.values()):
        if m is not None and getattr(m, name, None) is orig:
            setattr(m, name, new)


def push_wrap(mod, name, labelfn):
    f = getattr(mod, name)
    def w(*a, **k):
        t = labelfn(a, k); TAGS.append(t); t0 = PT()
        try: return f(*a, **k)
        finally: TAGS.pop(); STAGE_CPU[t] += PT() - t0
    setattr(mod, name, w); _patch(f, w, name)


def cand_fast_active():
    v = getattr(pb, "_CAND_PROFUNDIDAD", None)
    return (v.get() > 0) if v is not None else bool(getattr(pb, "_CAND_RAPIDO", 0))


def geom_fast_active():
    v = getattr(pc, "_GEOM_PROFUNDIDAD", None)
    return (v.get() > 0) if v is not None else bool(getattr(pc, "_GEOM_RAPIDA", 0))


def cur_tag(): return TAGS[-1] + (":lns" if LNSDEPTH[0] else "")


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


def install():
    def enp_label(a, k):
        n = a[7] if len(a) > 7 else k.get("n_pallets")
        if k.get("no_reserve_fallback"): return "deep"
        if k.get("solo_frente") and k.get("priorizar_grandes") is False: return "fallback"
        if k.get("presupuesto_global_expansiones") is not None: return f"final/N{n}"
        if k.get("presupuesto_repair_nodos") is not None: return f"probe/N{n}"
        return f"other/N{n}"
    push_wrap(pb, "_empacar_n_pallets", enp_label)
    # hashes de los resultados de cada _empacar_n_pallets (por etapa) y del witness (state.best_feasible_pallets)
    def sig(pals):
        if pals is None: return None
        return {"n": len(pals), "boxes": sum(t.cantidad for p in pals for t in p.torres),
                "comp": hash16(sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pals)),
                "layout": hash16(sorted(psb._firma_pallet_canonica(p) for p in pals))}
    e0 = pb._empacar_n_pallets
    def wenp(*a, **k):
        r = e0(*a, **k)
        try:
            tag = TAGS[-1] if TAGS[-1] != "other" else "other"
            WIT["enp_returns"].append({"tag": tag, **sig(r[0]), "sin_colocar": hash16(sorted(r[1].items()))})
        except Exception as ex_: WIT["enp_returns"].append({"tag": "err", "e": str(ex_)})
        return r
    pb._empacar_n_pallets = wenp; _patch(e0, wenp, "_empacar_n_pallets")
    import src.busqueda_n_pallets as bnp
    for nm in ("registrar_feasible_directo",):
        o = getattr(bnp.BusquedaState, nm)
        def mk(o, nm):
            def w(self, n, pallets, *a, **k):
                r = o(self, n, pallets, *a, **k); WIT["witness_events"].append({"ev": nm, "n": n, **sig(pallets)}); return r
            return w
        setattr(bnp.BusquedaState, nm, mk(o, nm))
    pd0 = bnp.politica_a_descenso
    def wpd(state, *a, **k):
        r = pd0(state, *a, **k)
        WIT["witness_at_final"] = {"best_feasible_n": state.best_feasible, **(sig(state.best_feasible_pallets) or {})}
        return r
    bnp.politica_a_descenso = wpd; _patch(pd0, wpd, "politica_a_descenso")
    sub = lambda nm: (lambda a, k: TAGS[-1] + "/" + nm)
    push_wrap(rs, "rescue_solver", sub("rescue")); push_wrap(rp, "repair_solver", sub("repair"))
    push_wrap(gr, "global_rescue", sub("global")); push_wrap(ex, "exact_repair_orquestado", sub("exact"))
    # _candidatos_lote: temporizador (+ shadow opcional)
    f = pb._candidatos_lote; ref = getattr(pb, "_candidatos_lote_referencia", None)
    def wcl(*a, **k):
        CNT["candidatos_lote"] += 1
        tag = cur_tag(); t0 = PT(); r = f(*a, **k); dt = PT() - t0
        rec = CL[tag]; rec["calls"] += 1; rec["cpu"] += dt
        fast = cand_fast_active()
        if fast: rec["calls_fast"] += 1; rec["cpu_fast"] += dt
        if args.shadow_cl and ref is not None:
            if not same(ref(*a, **k), r): raise SystemExit(f"CL SHADOW MISMATCH in {tag}")
            CNT["cl_shadow_checked"] += 1
            if fast: CNT["cl_shadow_fast"] += 1
        return r
    pb._candidatos_lote = wcl; _patch(f, wcl, "_candidatos_lote")
    # _podar_libres
    g = pc._podar_libres; pref = getattr(pc, "_podar_libres_referencia", None)
    def wpod(c, *a, **k):
        tag = TAGS[-1]; t0 = PT(); r = g(c, *a, **k); dt = PT() - t0
        rec = POD[tag]; rec["calls"] += 1; rec["cpu"] += dt
        if geom_fast_active(): CNT["podar_fast_calls"] += 1
        if args.shadow_podar and pref is not None:
            exp = pref(list(c))
            if bits([(x.x, x.y, x.z, x.w, x.h, x.d) for x in exp]) != bits([(x.x, x.y, x.z, x.w, x.h, x.d) for x in r]) or [id(x) for x in exp] != [id(x) for x in r]:
                raise SystemExit(f"PODAR SHADOW MISMATCH in {tag}")
            CNT["podar_shadow_checked"] += 1
        return r
    pc._podar_libres = wpod; _patch(g, wpod, "_podar_libres")
    count_wrap(pb, "_snapshot_estado_pallets", "snapshot")
    h = pb._lns_mejorar_pallets
    def wl(*a, **k):
        info = k.get("info_salida")
        if args.dfs and info is None: info = {}; k = dict(k); k["info_salida"] = info
        LNSDEPTH[0] += 1
        try: r = h(*a, **k)
        finally: LNSDEPTH[0] -= 1
        if args.dfs:
            l = LNS[TAGS[-1]]; l["calls"] += 1; l["iterations"] += int(info.get("iteraciones", 0))
            SEQ.append((TAGS[-1] + ":lnsend", int(info.get("iteraciones", 0)), None, r))
        return r
    pb._lns_mejorar_pallets = wl; _patch(h, wl, "_lns_mejorar_pallets")
    if args.dfs:
        d = pb._resolver_pallets_backtracking
        def wd(*a, **k):
            info = k.get("info_salida")
            if info is None: info = {}; k = dict(k); k["info_salida"] = info
            r = d(*a, **k); tag = cur_tag()
            x = DFS[tag]; x["calls"] += 1; x["nodes"] += int(info.get("nodos", 0)); x["stops"][info.get("motivo_parada")] += 1
            SEQ.append((tag, int(info.get("nodos", 0)), info.get("motivo_parada"), r))
            return r
        pb._resolver_pallets_backtracking = wd; _patch(d, wd, "_resolver_pallets_backtracking")


def count_wrap(mod, name, key):
    f = getattr(mod, name)
    def w(*a, **k): CNT[key] += 1; return f(*a, **k)
    setattr(mod, name, w); _patch(f, w, name)


TIME_KEY = re.compile(r"tiempo|time|seconds|segundos|cpu|wall|_s$|duracion|elapsed", re.I)


def flat(d, pre=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if TIME_KEY.search(str(k)): continue
            out.update(flat(v, f"{pre}{k}."))
    elif isinstance(d, (list, tuple)):
        for i, v in enumerate(d): out.update(flat(v, f"{pre}{i}."))
    elif isinstance(d, (set, frozenset)): out[pre.rstrip(".")] = sorted(map(str, d))
    else:
        out[pre.rstrip(".")] = d if isinstance(d, (int, bool, str)) or d is None else (round(d, 6) if isinstance(d, float) else str(d))
    return out


def hash16(o): return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_case(case):
    if case in ("BK35", "BK46"):
        from src import validacion
        envios = pd.read_excel(PILOT_XLSX, sheet_name="Envios_Julio"); maestro = pd.read_excel(PILOT_XLSX, sheet_name="Maestro_SKUs"); uma = pd.read_excel(PILOT_XLSX, sheet_name="UMA")
        envios = envios[envios["CD"] == case]; pobj = validacion.cargar_pallets_objetivo(PILOT_XLSX)
        df = preparar_demanda_por_cd(envios, maestro, uma); return df[df["CD"] == case], case, int(pobj[case])
    if case in ("BK31", "BK52", "BK53"):
        from fixtures.multicd_validation import cargar_dataset
        envios, maestro, uma, pobj = cargar_dataset(); df = preparar_demanda_por_cd(envios, maestro, uma)
        return df[df["CD"] == case], case, int(pobj[case])
    if case in ("SJ87", "SJ97", "BK68", "BK43"):
        x = ROOT / "Cubicaje18.07.2026.xlsx"
        envios = pd.read_excel(x, sheet_name="Envios_Julio"); maestro = pd.read_excel(x, sheet_name="Maestro_SKUs"); uma = pd.read_excel(x, sheet_name="UMA")
        df = preparar_demanda_por_cd(envios, maestro, uma); return df[df["CD"] == case], case, None
    raise SystemExit("unknown case")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = PT(); df, cd, pobj = load_case(args.case); load_cpu = PT() - t0
    install()
    w0, c0 = time.time(), PT()
    pal = pb.armar_pallets_bloques(df, cd, contador=[0], pallets_objetivo=pobj, paralelo_lns=False)
    cpu, wall = PT() - c0, time.time() - w0
    dumped = [dataclasses.asdict(p) for p in pal]
    for d in dumped: d.pop("metadata", None)
    md = pal[-1].metadata if pal else {}
    fm = flat(md)
    sin = {}
    for p in pal:
        for s, c in p.metadata.get("sin_colocar", {}).items(): sin[s] = sin.get(s, 0) + c
    src_ = md.get("fixed_n_solution_source")
    if src_ is None and "optimality_status" in md: src_ = "OPEN_" + str(md["optimality_status"].get("fuente", "LNS_FINAL_MATERIALIZATION"))
    if src_ is None and "fixed_n_exact_n_incumbent" in md: src_ = "DEEP_PATH_" + str(md["fixed_n_exact_n_incumbent"].get("resultado"))
    opt = {k: v for k, v in fm.items() if k.startswith("optimality_status.")}
    seq_by = defaultdict(list)
    for e in SEQ: seq_by[e[0]].append(e)
    res = {
        "case": args.case, "tag": args.tag, "root": str(ROOT), "load_cpu_s": round(load_cpu, 2), "armar_cpu_s": round(cpu, 3), "armar_wall_s": round(wall, 3),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1),
        "n": len(pal), "boxes": sum(t.cantidad for p in pal for t in p.torres), "missing": sum(sin.values()),
        "errors": sum(len(v5.validar_pallet_v5(p)) for p in pal),
        "comp": hash16(sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pal)),
        "layout": hash16(sorted(psb._firma_pallet_canonica(p) for p in pal)),
        "attrs": hash16(dumped), "source": src_, "meta_hash": hash16(fm), "meta_n_keys": len(fm), "meta": fm, "optimality": opt,
        "counters": dict(CNT), "stage_cpu": {k: round(v, 3) for k, v in STAGE_CPU.items()},
        "cl": {k: {"calls": v["calls"], "cpu": round(v["cpu"], 3), "calls_fast": v["calls_fast"], "cpu_fast": round(v["cpu_fast"], 3)} for k, v in CL.items()},
        "cl_cpu_total": round(sum(v["cpu"] for v in CL.values()), 3),
        "podar": {k: {"calls": v["calls"], "cpu": round(v["cpu"], 3)} for k, v in POD.items()},
        "dfs": {k: {"calls": v["calls"], "nodes": v["nodes"], "stops": dict(v["stops"])} for k, v in DFS.items()},
        "lns": {k: dict(v) for k, v in LNS.items()},
        "witness": WIT,
        "seq_hash": hash16(SEQ), "seq_hash_by_tag": {k: hash16(v) for k, v in seq_by.items()}, "seq_len": len(SEQ),
    }
    json.dump(res, open(OUT / f"{args.case}_{args.tag}.json", "w"), indent=1, default=str)
    print(f"[{args.case}/{args.tag}] cpu={res['armar_cpu_s']} rss={res['peak_rss_mb']}MB N={res['n']} boxes={res['boxes']} miss={res['missing']} err={res['errors']} "
          f"comp={res['comp']} layout={res['layout']} attrs={res['attrs']} meta={res['meta_hash']} src={res['source']}", flush=True)


main()
