from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

import config


@dataclass
class LogEntry:
    cd: object
    sku: object
    regla: str
    accion: str


@dataclass
class GeometriaSKU:
    """[V3 / sección 4.1, 5] Resultado de reconciliar Maestro ("Cajas por
    cama", capacidad operacional declarada) contra UMA (Largo/Ancho/Alto
    medidos) para un SKU. Ver src/reconciliacion_geometrica.py."""

    sku: str
    largo_uma: float | None
    ancho_uma: float | None
    alto_uma: float
    largo_efectivo: float
    ancho_efectivo: float
    alto_efectivo: float
    cajas_cama_maestro: int | None
    capacidad_uma: int | None
    # UMA_VALIDADA | UMA_SOBRECAPACIDAD | UMA_VALIDADA_CON_SOBRESALIENTE |
    # INFERIDA_MAESTRO | MAESTRO_IMPOSIBLE_DEGRADADO | DATO_INSUFICIENTE
    fuente_geometria: str
    delta_largo: float | None
    delta_ancho: float | None
    requiere_revision: bool
    # [V4c] True si la mejor orientación es acostada (una cara lateral como
    # huella, no la base) -solo posible en config.CATEGORIAS_ROTACION_LIBRE.
    acostada: bool = False


@dataclass
class CajaBAT:
    """[V3 / sección 4.2, 9, 11] Caja física de consolidación de Cigarros/
    vapes: junta varios SKUs del mismo CD, tamaño fijo, se coloca como remate
    encima de un pallet host ya armado. Ver src/bat.py."""

    cd: str
    id_bat: str
    unidades: int
    cantidades_cajas: dict[str, float] = field(default_factory=dict)
    largo: float = config.CAJA_BAT_LARGO
    ancho: float = config.CAJA_BAT_ANCHO
    alto: float = config.CAJA_BAT_ALTO
    pallet_host_id: str | None = None


@dataclass
class Placement:
    sku: str
    cantidad: int
    x: float
    y: float
    w: float
    d: float
    # Altura vertical que esta caja aporta a la cama en la orientación
    # elegida (siempre "Alto de caja" en V3 -solo rotación XY, ver config.py).
    h: float = 0.0


@dataclass
class Cama:
    categorias: list[str]
    altura_cama: float
    placements: list[Placement] = field(default_factory=list)
    cantidades: dict[str, int] = field(default_factory=dict)
    nivel_categoria: int | None = None

    # [PARCHE P5] cm² de la base 120x100 efectivamente cubiertos por las cajas.
    area_ocupada: float = 0.0

    # [V3 / sección 4.3, 14.2] PORTANTE si va a recibir otra cama encima
    # (necesita quedar razonablemente nivelada); TERMINAL si es la última del
    # pallet (nada se apoya encima, tolera más diferencia de altura). Lo fija
    # apilado_3d al momento de decidir qué va arriba de qué -antes de eso
    # queda en PORTANTE por default (la asunción más conservadora).
    tipo_soporte: Literal["PORTANTE", "TERMINAL"] = "PORTANTE"

    # [V3 / sección 4.3] Rango de alturas de caja presentes en la cama, y su
    # diferencia -ver packing_2d._cama_desde_colocacion.
    altura_min_cajas: float = 0.0
    altura_max_cajas: float = 0.0

    # [V3 / sección 4.3, 15.2] Menor support_ratio entre las cajas que esta
    # cama sostiene encima (None si todavía no tiene nada apoyado, o si es la
    # cama superior de un par sin calcular). Lo puebla soporte.py.
    support_ratio_min: float | None = None

    # [V3 / sección 4.1] True si Largo/Ancho de algún SKU de esta cama vienen
    # de reconciliacion_geometrica (INFERIDA_MAESTRO), no de UMA tal cual.
    geometria_inferida: bool = False

    @property
    def desnivel(self) -> float:
        """[V3 / sección 14.3] Diferencia entre la caja más alta y más baja
        de la cama. 0 en camas sin placements (PH, BAT: una sola "unidad"
        física, no hay desnivel que medir)."""
        return self.altura_max_cajas - self.altura_min_cajas

    @property
    def categoria(self) -> str:
        """Categoría única de la cama. Solo válida en camas puras.

        [PARCHE P7] dejaba esto como guard duro porque el packing agrupaba por
        categoría. Ahora las camas pueden mezclar categorías (agrupan por medidas
        de caja), así que las reglas de estabilidad del Paso 4 dejaron de usar
        esta property: usan `nivel_efectivo`, `categoria_remate` y `es_flexible`,
        que sí están definidas para camas mixtas. Se conserva para las camas
        puras (pallets homogéneos, tests) y sigue fallando fuerte si se la llama
        sobre una cama mixta, que es exactamente lo que queremos.
        """
        if len(self.categorias) != 1:
            raise ValueError(
                f"Cama con {len(self.categorias)} categorías ({self.categorias}). "
                "Usá nivel_efectivo / categoria_remate / es_flexible para camas mixtas."
            )
        return self.categorias[0]

    @property
    def _niveles(self) -> list[int]:
        return [n for n in (config.nivel_de_categoria(c) for c in self.categorias) if n is not None]

    @property
    def nivel_efectivo(self) -> int | None:
        """Nivel de estabilidad de la cama = el MÁS RESTRICTIVO de sus SKUs.

        Una cama que mezcla Licores (1) y Merch (5) se trata como Merch: se
        coloca en la pasada del nivel 5 y por lo tanto no recibe nada pesado
        encima. Es la interpretación conservadora: si un solo SKU de la cama no
        aguanta compresión, la cama entera no aguanta.
        """
        niveles = self._niveles
        return max(niveles) if niveles else None

    @property
    def nivel_minimo(self) -> int | None:
        niveles = self._niveles
        return min(niveles) if niveles else None

    @property
    def categoria_remate(self) -> str | None:
        """La categoría de remate presente en la cama, si hay alguna.

        Comestibles y Cigarros son mutuamente excluyentes dentro de la MISMA
        cama (una sola capa no puede ser dos cosas a la vez -revienta más
        abajo si pasa). [V4b] A nivel PALLET ya no son excluyentes: pueden
        convivir en camas distintas del mismo pallet cuando es la única forma
        de que una caja BAT entre en un pallet ya armado (ver
        bat.asignar_hosts_bat) -la mezcla libre por categoría (packing_2d,
        apilado_3d) tampoco distingue remate de no-remate para decidir qué va
        con qué.
        """
        remates = [c for c in self.categorias if c in config.CATEGORIAS_REMATE]
        if len(remates) > 1:
            raise ValueError(
                f"Cama con dos categorías de remate ({remates}); son excluyentes (regla 9.3)."
            )
        return remates[0] if remates else None

    @property
    def es_flexible(self) -> bool:
        """¿Esta cama puede ir encima de otras? Solo si TODOS sus SKUs son NABs
        o remate — o sea si ninguno necesita apoyarse en la base del pallet."""
        minimo = self.nivel_minimo
        return minimo is not None and minimo >= config.ORDEN_CATEGORIAS.index("NABs") + 1

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

    # [V3 / sección 4.4, 9] Altura antes de recibir una caja BAT como remate
    # (None si nunca fue evaluado como host, o si es un pallet BAT-host ya
    # resuelto). Se guarda para trazabilidad del host: cuánto subió por BAT.
    altura_pre_bat: float | None = None
    cajas_bat: list["CajaBAT"] = field(default_factory=list)
    es_host_bat: bool = False

    # Qué tan lejos quedó la altura final del objetivo (config.ALTURA_TARGET);
    # negativo = por debajo, positivo = por encima. Lo puebla bat.py al elegir
    # host, y apilado_3d al cerrar el pallet.
    altura_target_delta: float | None = None

    support_ratio_min: float | None = None
    benchmark_match_id: str | None = None


# ============================================================================
# [V5-P4] Modelos columnares -DOCUMENTACION_TECNICA_V5.md sección 3.
#
# El pallet deja de modelarse como una secuencia de camas horizontales
# uniformes y pasa a modelarse como una base 120x100 sobre la que se ubican
# TORRES verticales de altura independiente: Caja -> Torre -> Pallet (antes
# Caja -> Cama -> Pallet). Cama/Pallet (arriba) siguen siendo el modelo del
# core V4 -no se tocan- y pueden seguir existiendo como vista derivada para
# visualización/picking una vez que V5 esté en producción.
# ============================================================================


@dataclass(frozen=True)
class OrientacionCaja:
    """Una orientación físicamente válida de una caja: qué dimensión queda
    en cada eje. `acostada=True` solo es válida para SKUs de
    config.CATEGORIAS_ROTACION_LIBRE (ver reconciliacion_geometrica.py)."""

    largo: float
    ancho: float
    alto: float
    codigo: str  # "L×A" | "A×L" | "ACOSTADA_L" | "ACOSTADA_A"
    acostada: bool = False


@dataclass
class PlacementCaja:
    """Una caja física concreta dentro de una torre."""

    sku: str
    x: float
    y: float
    z: float
    largo: float
    ancho: float
    alto: float
    orientacion: str
    indice: int = 0


@dataclass
class Torre:
    """Cajas del mismo SKU apiladas verticalmente en una posición XY fija
    del pallet. Un SKU puede ocupar varias torres en el mismo pallet -no se
    exige que todas tengan la misma altura (DOCUMENTACION_LOGICA_V5.md 4.3).

    [V5-packing3d] `z` es la base de ESTE segmento dentro de la pila de
    producto (0 = piso del pallet, sin contar ALTURA_PALLET_VACIO -mismo
    origen que usa `visualizacion.py`). Antes del packing 3D, `z` siempre
    era 0 -una torre ocupaba su XY de piso a techo y nada más podía usar el
    aire por encima. Con `z` explícito, otra SKU puede tener su propia
    Torre en el MISMO (x, y) pero con z >= la anterior + su altura -lego
    real en vez de columnas aisladas."""

    sku: str
    cd: str
    x: float
    y: float
    largo: float
    ancho: float
    alto_caja: float
    cantidad: int
    peso: float
    orientacion: str
    fuente_geometria: str
    placements: list[PlacementCaja] = field(default_factory=list)
    z: float = 0.0

    @property
    def altura(self) -> float:
        """altura_torre = cantidad_cajas x alto_caja -SIEMPRE derivada, nunca
        un campo aparte que se pueda desincronizar de `cantidad`. Es la
        altura de ESTE segmento, no la altura acumulada desde el piso -para
        eso ver `z + altura` (el "techo" del segmento)."""
        return self.cantidad * self.alto_caja

    @property
    def area_base(self) -> float:
        return self.largo * self.ancho


@dataclass
class PalletV5:
    id: str
    cd: str
    torres: list[Torre] = field(default_factory=list)
    cajas_bat: list["CajaBAT"] = field(default_factory=list)
    altura_final: float = 0.0
    peso_estimado: float = 0.0
    ocupacion_xy: float = 0.0
    volumen_utilizado: float = 0.0
    estado: str = "OK"
    metadata: dict = field(default_factory=dict)


@dataclass
class ResultadoPipeline:
    plan_picking_df: pd.DataFrame
    log_validacion_df: pd.DataFrame
    resumen_cd_df: pd.DataFrame
    pallets: list[Pallet]
    info_sku: dict = field(default_factory=dict)
    auditoria_geometrica_df: pd.DataFrame | None = None
    benchmark_df: pd.DataFrame | None = None
    pallets_v5: list[PalletV5] | None = None
    cajas_no_colocadas_df: pd.DataFrame | None = None
