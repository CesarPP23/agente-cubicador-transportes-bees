from dataclasses import dataclass, field

import pandas as pd


@dataclass
class LogEntry:
    cd: object
    sku: object
    regla: str
    accion: str


@dataclass
class Placement:
    sku: str
    cantidad: int
    x: float
    y: float
    w: float
    d: float


@dataclass
class Cama:
    categorias: list[str]
    altura_cama: float
    placements: list[Placement] = field(default_factory=list)
    cantidades: dict[str, int] = field(default_factory=dict)
    nivel_categoria: int | None = None


@dataclass
class PalletLinea:
    sku: str
    descripcion: str
    categoria: str
    nivel_categoria: int | None
    cajas_demanda_oficial: int
    cajas_extra_consolidacion: int
    peso_no_validable: bool = False


@dataclass
class Pallet:
    id: str
    cd: str
    tipo: str
    camas: list[Cama] = field(default_factory=list)
    lineas: list[PalletLinea] = field(default_factory=list)
    altura_final: float = 0.0
    peso_estimado: float = 0.0
    estado: str = "OK"


@dataclass
class ResultadoPipeline:
    plan_picking_df: pd.DataFrame
    log_validacion_df: pd.DataFrame
    resumen_cd_df: pd.DataFrame
    pallets: list[Pallet]
    info_sku: dict = field(default_factory=dict)
