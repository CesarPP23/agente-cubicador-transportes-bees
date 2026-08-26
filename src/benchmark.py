"""[V3 / sección 18] Benchmark reproducible.

El objetivo no es "bajar el número de pallets" a secas -es reproducir
razonablemente la operación real (42 pallets, altura media 198.3cm, rango
170-215cm) y poder explicar cada divergencia, antes de intentar optimizar
por debajo de ese benchmark humano (sección 13 del doc lógico).
"""
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

import config
from models import Pallet

# [sección 18.1] Benchmark principal actual: "Cubicado Real", 42 pallets
# físicos (PALET=0 excluido -son cigarros/vapes pendientes de consolidación
# BAT, no un pallet físico adicional, ver DOCUMENTACION_LOGICA_V3.md 2.1/11.3).
PALLETS_REALES = 42
ALTURA_MEDIA_REAL = 198.3
ALTURA_MIN_REAL = 170.0
ALTURA_MAX_REAL = 215.0


@dataclass
class BenchmarkResultado:
    dataset_hash: str
    commit: str
    config_hash: str
    pallets: int
    altura_media: float
    altura_min: float
    altura_max: float
    parciales: int
    demanda_unidades_error: float
    geometria_inferida_count: int
    peso_medio: float = 0.0
    peso_max: float = 0.0
    error_pallets_pct: float = 0.0
    # [V5-P0] Conteo físico correcto: TODOS los pallets cuentan, incluidos los
    # PH-BAT-* dedicados -un pallet dedicado a cajas BAT es un pallet físico
    # más que Transporte tiene que mover, no una excepción a ignorar.
    pallets_bajo_190: int = 0
    pallets_bajo_170: int = 0
    bat_dedicados: int = 0
    pallets_por_cd: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


def _hash_archivo(ruta: str | Path | None) -> str:
    if ruta is None:
        return ""
    try:
        return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def _commit_actual() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except Exception:
        return ""


def _hash_config() -> str:
    """[sección 13] No es un hash criptográfico de todo config.py -solo de
    los parámetros que de verdad cambian el resultado del armado, para que
    dos corridas con la misma config den el mismo hash aunque cambien
    comentarios."""
    claves = [
        config.ALTURA_TARGET, config.ALTURA_MAX_OBSERVADA, config.ALTURA_HARD_VALIDADA,
        config.PESO_ALERTA_KG, config.PESO_HARD_KG,
        config.CAJA_BAT_LARGO, config.CAJA_BAT_ANCHO, config.CAJA_BAT_ALTO, config.CAJA_BAT_CAPACIDAD_UNIDADES,
    ]
    return hashlib.sha256(str(claves).encode()).hexdigest()[:12]


def calcular_kpis(
    pallets: list[Pallet],
    demanda_unidades_error: float = 0.0,
    geometria_inferida_count: int = 0,
    dataset_ruta: str | Path | None = None,
) -> BenchmarkResultado:
    """[sección 18 / V5-P0] Registra dataset, commit, config, cantidad de
    pallets FÍSICOS (TODOS -incluidos los PH-BAT-* dedicados, ver invariante
    11 de DOCUMENTACION_LOGICA_V5.md: "Pallet BAT dedicado cuenta como pallet
    físico"), parciales, altura/peso, demanda reconciliada y geometrías
    inferidas de una corrida. El caller (`pipeline.py`) debe pasar la lista
    COMPLETA de pallets armados -este módulo ya no filtra ni excluye nada."""
    if not pallets:
        return BenchmarkResultado(
            dataset_hash=_hash_archivo(dataset_ruta), commit=_commit_actual(), config_hash=_hash_config(),
            pallets=0, altura_media=0.0, altura_min=0.0, altura_max=0.0, parciales=0,
            demanda_unidades_error=demanda_unidades_error, geometria_inferida_count=geometria_inferida_count,
        )

    alturas = [p.altura_final for p in pallets]
    pesos = [p.peso_estimado for p in pallets]
    parciales = sum(1 for a in alturas if a < config.ALTURA_TOLERADO_MIN)
    bat_dedicados = sum(1 for p in pallets if p.id.startswith("PV5-BAT-"))

    pallets_por_cd: dict[str, int] = {}
    for p in pallets:
        pallets_por_cd[p.cd] = pallets_por_cd.get(p.cd, 0) + 1

    return BenchmarkResultado(
        dataset_hash=_hash_archivo(dataset_ruta),
        commit=_commit_actual(),
        config_hash=_hash_config(),
        pallets=len(pallets),
        altura_media=round(sum(alturas) / len(alturas), 2),
        altura_min=round(min(alturas), 2),
        altura_max=round(max(alturas), 2),
        parciales=parciales,
        demanda_unidades_error=demanda_unidades_error,
        geometria_inferida_count=geometria_inferida_count,
        peso_medio=round(sum(pesos) / len(pesos), 2),
        peso_max=round(max(pesos), 2),
        error_pallets_pct=round((len(pallets) - PALLETS_REALES) / PALLETS_REALES, 4),
        pallets_bajo_190=sum(1 for a in alturas if a < config.ALTURA_NOMINAL_MIN),
        pallets_bajo_170=sum(1 for a in alturas if a < config.ALTURA_PARCIAL_OPERATIVA_MIN),
        bat_dedicados=bat_dedicados,
        pallets_por_cd=pallets_por_cd,
    )


def comparar_contra_real(resultado: BenchmarkResultado) -> dict:
    """[sección 18.2] Compara un BenchmarkResultado contra el benchmark real."""
    return {
        "pallets_modelo": resultado.pallets,
        "pallets_reales": PALLETS_REALES,
        "error_pallets_pct": resultado.error_pallets_pct,
        "altura_media_modelo": resultado.altura_media,
        "altura_media_real": ALTURA_MEDIA_REAL,
        "delta_altura_media": round(resultado.altura_media - ALTURA_MEDIA_REAL, 2),
        "altura_min_modelo": resultado.altura_min,
        "altura_min_real": ALTURA_MIN_REAL,
        "altura_max_modelo": resultado.altura_max,
        "altura_max_real": ALTURA_MAX_REAL,
    }


def auditar_pallet(pallet: Pallet) -> dict:
    """[sección 18.3] Auditoría de un pallet del MODELO (no del real -para
    cruzar contra un pallet real específico hace falta el detalle CD/SKU/
    Pallet del archivo de referencia, que se mapea aparte, ver el análisis
    manual ya hecho contra "Plan de acción 10.08"). Devuelve un resumen de
    por qué este pallet quedó como quedó: geometría, altura, peso, categoría,
    soporte, BAT, regla de mezcla -sección 18.3."""
    return {
        "id": pallet.id,
        "cd": pallet.cd,
        "tipo": pallet.tipo,
        "altura_final": round(pallet.altura_final, 2),
        "zona_altura": config.estado_altura(pallet.altura_final),
        "peso_estimado": round(pallet.peso_estimado, 2),
        "peso_bajo_hard": pallet.peso_estimado <= config.PESO_HARD_KG,
        "n_camas": len(pallet.camas),
        "categorias": sorted({cat for c in pallet.camas for cat in c.categorias}),
        "es_host_bat": pallet.es_host_bat,
        "altura_target_delta": pallet.altura_target_delta,
        "support_ratio_min": pallet.support_ratio_min,
        "geometria_inferida_en_alguna_cama": any(c.geometria_inferida for c in pallet.camas),
        "estado": pallet.estado,
    }


GATE_V5_PALLETS_MIN = 42
GATE_V5_PALLETS_MAX = 45


@dataclass
class GateV5Resultado:
    """[V5-P14] Veredicto del gate formal (DOCUMENTACION_TECNICA_V5.md
    sección 15): V5 no reemplaza a V4 por defecto hasta que esto dé
    `aprobado=True`. `razones` queda vacía solo si aprueba -cada entrada es
    un motivo de rechazo independiente, no se detiene en el primero para
    poder reportar todo lo que falta de una sola corrida."""

    aprobado: bool
    razones: list[str]
    pallets: int
    altura_max: float
    demanda_unidades_error: float
    violaciones_geometria: int


def evaluar_gate_v5(resultado: BenchmarkResultado, violaciones_geometria: list[str] | None = None) -> GateV5Resultado:
    """[sección 15] Ninguno de estos criterios se relaja para hacer pasar el
    benchmark -son los mismos que impone el plan: rango de pallets, demanda
    exacta, altura dentro del tope duro real, y cero violaciones geométricas
    (overlap/overflow, ver `validacion_v5.validar_geometria_v5`). Los BAT
    dedicados no se auditan aparte -desde P0 cuentan dentro de `pallets`
    por construcción, no hay forma de que este gate los "esconda"."""
    violaciones_geometria = violaciones_geometria or []
    razones: list[str] = []

    if not (GATE_V5_PALLETS_MIN <= resultado.pallets <= GATE_V5_PALLETS_MAX):
        razones.append(
            f"pallets={resultado.pallets}, fuera del rango [{GATE_V5_PALLETS_MIN}, {GATE_V5_PALLETS_MAX}]"
        )
    if resultado.demanda_unidades_error != 0:
        razones.append(f"demanda_unidades_error={resultado.demanda_unidades_error} (debe ser 0)")
    if resultado.altura_max > ALTURA_MAX_REAL:
        razones.append(f"altura_max={resultado.altura_max} supera el tope real {ALTURA_MAX_REAL}")
    if violaciones_geometria:
        razones.append(f"{len(violaciones_geometria)} violaciones geométricas (overlap/overflow)")

    return GateV5Resultado(
        aprobado=not razones,
        razones=razones,
        pallets=resultado.pallets,
        altura_max=resultado.altura_max,
        demanda_unidades_error=resultado.demanda_unidades_error,
        violaciones_geometria=len(violaciones_geometria),
    )


def benchmark_df(resultados: list[BenchmarkResultado]) -> pd.DataFrame:
    """[sección 20] Hoja benchmark del output: real vs modelo, corridas
    sucesivas si se llama con más de un BenchmarkResultado."""
    filas = []
    for r in resultados:
        comp = comparar_contra_real(r)
        fila = {**vars(r), **{f"real_{k}": v for k, v in comp.items()}}
        # dict/objetos no serializan bien en una celda de Excel -se guardan
        # como texto legible ("BK31=5, BK41=4, ...").
        fila["pallets_por_cd"] = ", ".join(f"{cd}={n}" for cd, n in sorted(r.pallets_por_cd.items()))
        fila["extras"] = str(r.extras) if r.extras else ""
        filas.append(fila)
    return pd.DataFrame(filas)
