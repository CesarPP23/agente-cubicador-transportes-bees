"""[CIERRE V6.12-R2-A1] Golden-6 real -- definición OFICIAL del hash canónico
de regresión (BK31/BK43/BK49/BK50/BK52/BK53).

Esta es la ÚNICA canonicalización de hash que debe usarse para comparar
resultados de estos 6 CDs entre corridas/checkpoints. Los harnesses previos
de BK41 (Fase 1D-R1, R2-A0, R2-A1, en el scratchpad de esa sesión) usaban la
MISMA fórmula de hash por construcción independiente -pero de acá en
adelante, para golden-6, esta es la fuente de verdad; no se debe volver a
mezclar hashes calculados con otra función o con otro criterio de
serialización.

Fórmula del hash canónico (estable, independiente de layout/coordenadas):
    sha256(
        json.dumps(
            sorted(sorted((torre.sku, torre.cantidad) for torre in pallet.torres)
                   for pallet in pallets),
            sort_keys=True, default=str,
        )
    ).hexdigest()[:16]

Es decir: para cada pallet, la lista ordenada de (SKU, cantidad) de sus
torres; luego esas listas se ordenan entre sí. Dos corridas con la MISMA
composición SKU/cantidad por pallet dan el MISMO hash, sin importar en qué
ORDEN quedaron los pallets en la lista de salida, ni la posición XYZ exacta
de cada torre dentro del pallet (eso lo cubre `validar_pallet_v5`, no el
hash -el hash es de COMPOSICIÓN, no de geometría).

Cada CD corre por su camino canónico real de producción:
  - BK31/BK49/BK50/BK52/BK53: dataset `tests/fixtures/multicd_validation.xlsx`
    (5 CDs con `Pallets_Objetivo` explícito), mismo llamado que
    `src.validacion_multicd.evaluar_cd`:
        armar_pallets_bloques(df_cd, cd, pallets_objetivo=pobj[cd], paralelo_lns=True)
  - BK43: dataset `Cubicaje18.07.2026.xlsx` (el histórico de 9 CDs de
    `test_determinismo`, sin `Pallets_Objetivo` -pasa por la búsqueda binaria
    de N), aislado del resto de los 8 CDs del dataset, mismo llamado que
    `pipeline_sku_bloque._procesar_cd` para un CD dentro de un batch
    multi-CD:
        armar_pallets_bloques(grupo, cd, contador=[0], pallets_objetivo=None, paralelo_lns=False)

Uso:
    .venv/bin/python3 scripts/golden6_gate.py [--project RUTA] --out salida.json --label mi-corrida

`--project` es opcional -por default usa este mismo checkout (permite
además apuntar a otro checkout/worktree, p.ej. un tag anterior, para
comparar hashes baseline reales entre versiones, como se hizo para cerrar
V6.12-R2-A1 contra v6.11-multicd-pass)."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

_RAIZ_POR_DEFECTO = Path(__file__).resolve().parents[1]

_ap = argparse.ArgumentParser()
_ap.add_argument("--project", default=str(_RAIZ_POR_DEFECTO))
_ap.add_argument("--out", required=True)
_ap.add_argument("--label", required=True)
_ap.add_argument("--cds", default="BK31,BK43,BK49,BK50,BK52,BK53",
                  help="Lista separada por comas -por default los 6 golden.")
args = _ap.parse_args()

PROJECT = Path(args.project)
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))

import pandas as pd  # noqa: E402

from src.packing_bloques import armar_pallets_bloques  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402


def hash_canonico(pallets) -> str:
    """La ÚNICA función de hash que debe usarse para golden-6. Ver
    docstring del módulo para la definición exacta."""
    composicion = sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pallets)
    return hashlib.sha256(
        json.dumps(composicion, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _evaluar(cd: str, pallets: list) -> dict:
    cajas_final = sum(t.cantidad for p in pallets for t in p.torres)
    sin_colocar: dict[str, int] = {}
    for p in pallets:
        for sku, cant in p.metadata.get("sin_colocar", {}).items():
            sin_colocar[sku] = sin_colocar.get(sku, 0) + cant
    demanda_cajas = cajas_final + sum(sin_colocar.values())
    errores = []
    for p in pallets:
        errores += validar_pallet_v5(p)
    return {
        "cd": cd,
        "cajas_final": cajas_final,
        "demanda_cajas": demanda_cajas,
        "faltantes": sum(sin_colocar.values()),
        "pallets": len(pallets),
        "errores": len(errores),
        "errores_detalle": errores[:5],
        "hash": hash_canonico(pallets),
    }


def main() -> dict:
    cds_pedidos = [c.strip() for c in args.cds.split(",") if c.strip()]
    resultados = {}

    cds_multicd = [c for c in cds_pedidos if c != "BK43"]
    if cds_multicd:
        from fixtures.multicd_validation import cargar_dataset

        envios, maestro, uma, pobj = cargar_dataset()
        df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
        for cd in cds_multicd:
            t0 = time.time()
            df_cd = df_clasificado[df_clasificado["CD"] == cd]
            pallets = armar_pallets_bloques(df_cd, cd, pallets_objetivo=pobj[cd], paralelo_lns=True)
            fila = _evaluar(cd, pallets)
            fila["wall_s"] = round(time.time() - t0, 1)
            resultados[cd] = fila
            print(f"[{args.label}] {cd}: {fila['cajas_final']}/{fila['demanda_cajas']} cajas, "
                  f"{fila['pallets']} pallet(s), {fila['errores']} errores, hash={fila['hash']}, "
                  f"{fila['wall_s']}s", flush=True)

    if "BK43" in cds_pedidos:
        envios_h = pd.read_excel(PROJECT / "Cubicaje18.07.2026.xlsx", sheet_name="Envios_Julio")
        maestro_h = pd.read_excel(PROJECT / "Cubicaje18.07.2026.xlsx", sheet_name="Maestro_SKUs")
        uma_h = pd.read_excel(PROJECT / "Cubicaje18.07.2026.xlsx", sheet_name="UMA")
        df_clasificado_h = preparar_demanda_por_cd(envios_h, maestro_h, uma_h)

        t0 = time.time()
        grupo_bk43 = df_clasificado_h[df_clasificado_h["CD"] == "BK43"]
        pallets_bk43 = armar_pallets_bloques(
            grupo_bk43, "BK43", contador=[0], pallets_objetivo=None, paralelo_lns=False,
        )
        fila = _evaluar("BK43", pallets_bk43)
        fila["wall_s"] = round(time.time() - t0, 1)
        resultados["BK43"] = fila
        print(f"[{args.label}] BK43: {fila['cajas_final']}/{fila['demanda_cajas']} cajas, "
              f"{fila['pallets']} pallet(s), {fila['errores']} errores, hash={fila['hash']}, "
              f"{fila['wall_s']}s", flush=True)

    with open(args.out, "w") as f:
        json.dump(resultados, f, indent=2, default=str)
    print(f"[{args.label}] DONE -> {args.out}")
    return resultados


if __name__ == "__main__":
    main()
