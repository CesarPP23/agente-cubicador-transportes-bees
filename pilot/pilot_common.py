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
