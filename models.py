from dataclasses import dataclass, field

import pandas as pd

import config


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

    # [PARCHE P5] cm² de la base 120x100 efectivamente cubiertos por las cajas.
    # Lo puebla packing_2d._cama_desde_colocacion a partir de los placements.
    area_ocupada: float = 0.0

    @property
    def categoria(self) -> str:
        """[PARCHE P7] Categoría única de la cama.

        Todas las reglas de estabilidad (_es_flexible, _remate_de,
        _remate_compatible) asumían implícitamente `categorias[0]`, o sea que la
        cama tiene UNA sola categoría. Hoy eso se cumple porque
        packing_2d.generar_camas agrupa por Categoria_Normalizada antes de
        clusterizar. Si algún día se permiten camas multi-categoría, sin este
        guard las reglas de estabilidad empezarían a mentir SIN fallar.
        """
        if len(self.categorias) != 1:
            raise ValueError(
                f"Cama con {len(self.categorias)} categorías ({self.categorias}). "
                "Las reglas de estabilidad del Paso 4 asumen una sola categoría por cama."
            )
        return self.categorias[0]

    @property
    def fill_ratio(self) -> float:
        """[PARCHE P5] Fracción de la base del pallet cubierta por esta cama.

        Las camas sin placements (las que arma pallets_homogeneos.py, que no
        pasan por el packing 2D) se asumen llenas: su densidad viene del Maestro
        y no hay geometría con la cual medirlas.
        """
        if not self.placements:
            return 1.0
        return self.area_ocupada / (config.PALLET_LARGO * config.PALLET_ANCHO)


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
