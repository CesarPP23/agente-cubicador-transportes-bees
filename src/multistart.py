"""[V5-P7] Multi-start: no confiar en un único orden de entrada.

Por CD, genera múltiples candidatos con órdenes de procesamiento distintos
(7 estrategias base + N semillas para la aleatoria) y elige el mejor por
comparación lexicográfica (DOCUMENTACION_TECNICA_V5.md sección 8).
"""
import random
from dataclasses import dataclass, field

import pandas as pd

import config
from models import PalletV5
from src.packing_columnar import armar_pallets_columnar

ESTRATEGIAS = [
    "VOLUMEN_DESC",
    "FOOTPRINT_DESC",
    "ALTURA_DESC",
    "FLEXIBILIDAD_ASC",
    "CAJAS_CAMA_DESC",
    "PESO_DESC",
    "RANDOM",
]


@dataclass
class SolucionCD:
    cd: str
    estrategia: str
    seed: int | None
    pallets: list[PalletV5] = field(default_factory=list)
    n_pallets: int = 0
    n_pallets_bajo_190: int = 0
    residual_total: float = 0.0
    altura_media: float = 0.0
    geometrias_inferidas: int = 0

    @property
    def score(self) -> tuple:
        """Comparación lexicográfica (sección 8): menos pallets primero,
        después menos pallets bajo el nominal, después menos residual
        (déficit de altura respecto del target sumado en todos los
        pallets), después más cerca del target en promedio, después menos
        geometría inferida/degradada."""
        return (
            self.n_pallets,
            self.n_pallets_bajo_190,
            round(self.residual_total, 2),
            round(abs(self.altura_media - config.ALTURA_TARGET), 2),
            self.geometrias_inferidas,
        )


def _valor(fila: pd.Series, campo: str, default: float = 0.0) -> float:
    v = fila.get(campo)
    return float(v) if pd.notna(v) else default


def _orden_por_estrategia(df_cd: pd.DataFrame, estrategia: str, seed: int | None) -> list[str]:
    """Devuelve el orden de SKUs (por CÓDIGO, no candidatas) según la
    estrategia. `armar_pallets_columnar` filtra/completa lo que le falte."""
    por_sku = df_cd.drop_duplicates(subset="SKU").set_index("SKU", drop=False)
    skus = list(por_sku.index)

    if estrategia == "RANDOM":
        rng = random.Random(seed)
        orden = list(skus)
        rng.shuffle(orden)
        return orden

    def _fila(sku):
        return por_sku.loc[sku]

    claves = {
        "VOLUMEN_DESC": lambda s: -(
            _valor(_fila(s), "Largo_Efectivo") * _valor(_fila(s), "Ancho_Efectivo")
            * _valor(_fila(s), "Alto_Efectivo") * _valor(_fila(s), "Cajas_Remanente")
        ),
        "FOOTPRINT_DESC": lambda s: -(_valor(_fila(s), "Largo_Efectivo") * _valor(_fila(s), "Ancho_Efectivo")),
        "ALTURA_DESC": lambda s: -_valor(_fila(s), "Alto_Efectivo"),
        # [sección 11] "menor flexibilidad primero": una caja que ocupa una
        # fracción grande del pallet tiene MENOS posiciones alternativas
        # posibles -se coloca primero, antes de que el espacio libre se
        # fragmente en huecos donde ya no entraría.
        "FLEXIBILIDAD_ASC": lambda s: (
            (config.PALLET_LARGO - _valor(_fila(s), "Largo_Efectivo"))
            * (config.PALLET_ANCHO - _valor(_fila(s), "Ancho_Efectivo"))
        ),
        "CAJAS_CAMA_DESC": lambda s: -_valor(_fila(s), "Cajas_Cama_Efectivo"),
        "PESO_DESC": lambda s: -(_valor(_fila(s), "Peso_Caja") * _valor(_fila(s), "Cajas_Remanente")),
    }
    clave = claves.get(estrategia)
    if clave is None:
        raise ValueError(f"estrategia desconocida: {estrategia}")
    return sorted(skus, key=clave)


def _evaluar(
    df_cd: pd.DataFrame, cd: str, estrategia: str, seed: int | None, info_sku: dict, concentrar_sku: bool = False
) -> SolucionCD:
    orden = _orden_por_estrategia(df_cd, estrategia, seed)
    pallets = armar_pallets_columnar(df_cd, cd, orden_skus=orden, concentrar_sku=concentrar_sku)

    alturas = [p.altura_final for p in pallets]
    altura_media = sum(alturas) / len(alturas) if alturas else 0.0
    n_bajo_190 = sum(1 for a in alturas if a < config.ALTURA_NOMINAL_MIN)
    # "residual" = cuánta altura le falta a cada pallet para llegar al
    # target -un proxy simple de "qué tan lejos está de la operación real"
    # sin depender de una definición más elaborada de volumen residual.
    residual_total = sum(max(0.0, config.ALTURA_TARGET - a) for a in alturas)
    geometrias_inferidas = sum(
        1
        for p in pallets
        for t in p.torres
        if info_sku.get(t.sku, {}).get("fuente_geometria") in ("INFERIDA_MAESTRO", "MAESTRO_IMPOSIBLE_DEGRADADO")
    )

    return SolucionCD(
        cd=cd, estrategia=estrategia, seed=seed, pallets=pallets,
        n_pallets=len(pallets), n_pallets_bajo_190=n_bajo_190,
        residual_total=round(residual_total, 3), altura_media=round(altura_media, 3),
        geometrias_inferidas=geometrias_inferidas,
    )


def generar_soluciones_cd(
    df_cd: pd.DataFrame,
    cd: str,
    info_sku: dict,
    estrategias: list[str] | None = None,
    seeds: int = config.MULTISTART_SEEDS,
    concentrar_sku: bool = False,
) -> list[SolucionCD]:
    """[sección 8] Genera un candidato por cada estrategia determinística +
    `seeds` candidatos con orden aleatorio (semillas 0..seeds-1,
    reproducibles). Ninguna estrategia determinística se corre más de una
    vez -correrla de nuevo con otra "semilla" daría el mismo resultado, sería
    trabajo perdido; la variación real de RANDOM sí justifica múltiples
    corridas.

    `concentrar_sku` (default False, sin cambio de comportamiento): se pasa
    tal cual a `armar_pallets_columnar` en cada candidato -ver
    packing_columnar.py y PATCH_LOG.md, sección "V-AUTO-CONSOLIDADO-DURO"."""
    estrategias = estrategias or ESTRATEGIAS
    soluciones: list[SolucionCD] = []

    for estrategia in estrategias:
        if estrategia == "RANDOM":
            for seed in range(min(seeds, config.MULTISTART_MAX)):
                soluciones.append(_evaluar(df_cd, cd, estrategia, seed, info_sku, concentrar_sku=concentrar_sku))
        else:
            soluciones.append(_evaluar(df_cd, cd, estrategia, None, info_sku, concentrar_sku=concentrar_sku))

    return soluciones


def mejor_solucion(soluciones: list[SolucionCD]) -> SolucionCD:
    """Selección lexicográfica: `min(score)` -sección 8."""
    return min(soluciones, key=lambda s: s.score)
