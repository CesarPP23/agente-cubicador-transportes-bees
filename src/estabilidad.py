"""[V5-P11] Estabilidad informativa -KPIs/alertas sobre un PalletV5 ya
armado, NUNCA bloquean el armado (DOCUMENTACION_TECNICA_V5.md sección 10,
DOCUMENTACION_LOGICA_V5.md sección 16). Sin restricciones duras soltadas
(altura, peso) no hay ninguna señal física de estabilidad quedando -este
módulo la recupera como reporte, para que operación pueda auditar por qué
un pallet específico podría necesitar revisión manual, sin que el motor
deje de producir 42-45 pallets por eso.
"""
from dataclasses import dataclass, field

import config
from models import PalletV5

ESTADO_OK = "OK"
ESTADO_WARN_COG = "WARN_COG"
ESTADO_WARN_TORRE_ESBELTA = "WARN_TORRE_ESBELTA"
ESTADO_WARN_PESO_SUPERIOR = "WARN_PESO_SUPERIOR"

# Umbrales informativos (sin validar contra operación real -mismo espíritu
# que config.PESO_PARAMETROS_VALIDADOS=False: son un punto de partida
# razonable, no una norma).
COG_MAX_DESVIACION_CM = 15.0  # cuánto puede desviarse el centro de masa del centro geométrico del pallet
RATIO_ESBELTEZ_MAX = 4.0  # altura de una torre / su lado más corto, antes de considerarla "esbelta"
# Fracción de la altura de producto donde puede estar el centro de masa
# VERTICAL (altura del torre/2, ponderada por peso) antes de considerarlo
# "top-heavy". 0.5 sería el punto de equilibrio exacto de un pallet
# perfectamente parejo -0.6 deja margen para que un solo nivel uniforme
# (centro de masa en altura/2 = ratio 0.5 exacto) no dispare la alerta.
PESO_SUPERIOR_FRACCION_MAX = 0.6


@dataclass
class EstabilidadPallet:
    pallet_id: str
    centro_masa_x: float
    centro_masa_y: float
    desviacion_centro_masa: float
    peso_por_cuadrante: dict[str, float] = field(default_factory=dict)
    torres_esbeltas: list[str] = field(default_factory=list)
    fraccion_peso_superior: float = 0.0
    estados: list[str] = field(default_factory=lambda: [ESTADO_OK])

    @property
    def ok(self) -> bool:
        return self.estados == [ESTADO_OK] or not self.estados


def _cuadrante(x: float, y: float) -> str:
    lado_y = "S" if y < config.PALLET_ANCHO / 2 else "N"
    lado_x = "O" if x < config.PALLET_LARGO / 2 else "E"
    return f"{lado_y}{lado_x}"


def calcular_estabilidad(pallet: PalletV5) -> EstabilidadPallet:
    """Calcula, no bloquea. Devuelve `ESTADO_OK` si no hay ninguna señal
    fuera de umbral -pallets sin torres (ej. un dedicado BAT vacío por algún
    motivo transitorio) se reportan OK por defecto, no hay nada que evaluar."""
    torres = pallet.torres
    if not torres:
        return EstabilidadPallet(
            pallet_id=pallet.id, centro_masa_x=0.0, centro_masa_y=0.0, desviacion_centro_masa=0.0,
        )

    peso_total = sum(t.peso for t in torres) or 1.0
    cx = sum((t.x + t.largo / 2) * t.peso for t in torres) / peso_total
    cy = sum((t.y + t.ancho / 2) * t.peso for t in torres) / peso_total
    centro_geom_x, centro_geom_y = config.PALLET_LARGO / 2, config.PALLET_ANCHO / 2
    desviacion = ((cx - centro_geom_x) ** 2 + (cy - centro_geom_y) ** 2) ** 0.5

    peso_cuadrante: dict[str, float] = {}
    for t in torres:
        q = _cuadrante(t.x + t.largo / 2, t.y + t.ancho / 2)
        peso_cuadrante[q] = peso_cuadrante.get(q, 0.0) + t.peso

    torres_esbeltas = [
        f"{t.sku}@({t.x:.0f},{t.y:.0f})"
        for t in torres
        if t.altura > 0 and min(t.largo, t.ancho) > 0 and (t.altura / min(t.largo, t.ancho)) > RATIO_ESBELTEZ_MAX
    ]

    # [P11, actualizado para packing3d] Centro de masa VERTICAL: cada torre
    # aporta su peso centrado en la mitad de SU propio segmento (masa
    # ~uniforme de piso a tope del segmento) -el centro real de un segmento
    # es `t.z + t.altura/2`, no `t.altura/2` a secas: dos torres del mismo
    # peso y altura, una apilada arriba de la otra, tienen que aportar
    # distinto al centro de masa vertical. Ponderado y normalizado contra
    # la altura de producto del pallet (`max(t.z + t.altura)`, el tope real
    # con torres apiladas, no `max(t.altura)` que ignoraría dónde empieza
    # cada segmento) -no contra "el tercio superior" (eso daba falso
    # positivo en cualquier pallet de una sola capa uniforme: TODA torre
    # corta igual a las demás queda, por definición, en "el tercio de
    # arriba" si es la única capa).
    altura_producto = max((t.z + t.altura for t in torres), default=0.0)
    if altura_producto > 0:
        centro_masa_z = sum(t.peso * (t.z + t.altura / 2) for t in torres) / peso_total
        fraccion_superior = centro_masa_z / altura_producto
    else:
        fraccion_superior = 0.0

    estados = []
    if desviacion > COG_MAX_DESVIACION_CM:
        estados.append(ESTADO_WARN_COG)
    if torres_esbeltas:
        estados.append(ESTADO_WARN_TORRE_ESBELTA)
    if fraccion_superior > PESO_SUPERIOR_FRACCION_MAX:
        estados.append(ESTADO_WARN_PESO_SUPERIOR)
    if not estados:
        estados = [ESTADO_OK]

    return EstabilidadPallet(
        pallet_id=pallet.id,
        centro_masa_x=round(cx, 2), centro_masa_y=round(cy, 2), desviacion_centro_masa=round(desviacion, 2),
        peso_por_cuadrante={k: round(v, 2) for k, v in peso_cuadrante.items()},
        torres_esbeltas=torres_esbeltas, fraccion_peso_superior=round(fraccion_superior, 3), estados=estados,
    )
