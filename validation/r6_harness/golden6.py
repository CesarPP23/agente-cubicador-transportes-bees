"""Golden-6 con COMP + LAYOUT + N + cajas contra validation/v6.12_golden_baseline.json (mismas llamadas canónicas que scripts/golden6_gate.py)."""
import hashlib, json, os, sys, time
from pathlib import Path
ROOT = Path(os.environ.get("P0_SOLVER_ROOT", Path(__file__).resolve().parents[2]))
OUT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests")); os.chdir(ROOT)
import pandas as pd
from src.packing_bloques import armar_pallets_bloques
import src.pipeline_sku_bloque as psb
from src.validacion_multicd import preparar_demanda_por_cd
from src.validacion_v5 import validar_pallet_v5
base = json.load(open(ROOT / "validation/v6.12_golden_baseline.json"))["golden"]
def h16(o): return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]
res = {}
from fixtures.multicd_validation import cargar_dataset
envios, maestro, uma, pobj = cargar_dataset()
dfc = preparar_demanda_por_cd(envios, maestro, uma)
jobs = [(cd, dfc[dfc["CD"] == cd], dict(pallets_objetivo=pobj[cd], paralelo_lns=True)) for cd in ("BK31", "BK49", "BK50", "BK52", "BK53")]
X = ROOT / "Cubicaje18.07.2026.xlsx"
dh = preparar_demanda_por_cd(pd.read_excel(X, sheet_name="Envios_Julio"), pd.read_excel(X, sheet_name="Maestro_SKUs"), pd.read_excel(X, sheet_name="UMA"))
jobs.insert(1, ("BK43", dh[dh["CD"] == "BK43"], dict(contador=[0], pallets_objetivo=None, paralelo_lns=False)))
allok = True
for cd, df, kw in jobs:
    t0 = time.time()
    pallets = armar_pallets_bloques(df, cd, **kw)
    comp = h16(sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pallets))
    layout = h16(sorted(psb._firma_pallet_canonica(p) for p in pallets))
    cajas = sum(t.cantidad for p in pallets for t in p.torres); err = sum(len(validar_pallet_v5(p)) for p in pallets)
    b = base[cd]; ok = (len(pallets) == b["N"] and cajas == b["cajas"] and comp == b["COMP"] and layout == b["LAYOUT"] and err == 0)
    allok &= ok
    res[cd] = dict(N=len(pallets), cajas=cajas, COMP=comp, LAYOUT=layout, errores=err, wall_s=round(time.time() - t0, 1), **{"pass": ok})
    print(f"[golden6] {cd}: {'PASS' if ok else 'FAIL'} N={len(pallets)} cajas={cajas} COMP={comp} LAYOUT={layout} err={err} wall={res[cd]['wall_s']}s", flush=True)
json.dump(res, open(OUT, "w"), indent=1)
print("[golden6] ALL PASS" if allok else "[golden6] FAIL", flush=True)
