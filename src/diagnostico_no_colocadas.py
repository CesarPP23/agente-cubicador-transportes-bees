"""[PATCH V6.01 sección 5 / V6.02 sección 2] Diagnóstico de motivo de
rechazo para SKUs que quedaron `sin_colocar` al terminar
`armar_pallets_bloques`.

Puramente de LECTURA -no participa del armado real, no cambia ninguna
decisión de `packing_bloques.py`. Se corre una sola vez al final, sobre el
resultado YA congelado, para responder "¿por qué no entró lo que no
entró?" con conteos por motivo.

Reusa las mismas funciones de admisión que el solver real
(`_soporte_viola_nivel`, `_altura_compatible_con_cama`,
`_tiene_soporte_admisible`, etc.) para que el diagnóstico sea fiel a la
regla real, no una reimplementación aproximada que pueda divergir.

[V6.02 / sección 2] `NO_FREE_RECT_FIT` vs `EDGE_OVERHANG` -antes ambos
caían en un único motivo `overflow`, y el caso real de BK31 (Pícaras,
39x30, muy por debajo del envelope 124x104) quedaba mal clasificado como
si fuera un problema de sobresaliente exterior, cuando en realidad es
fragmentación del layout (ningún cuboide libre bastante grande). La
distinción:

- `EDGE_OVERHANG`: la caja, en SU MEJOR orientación, no entra ni siquiera
  en el envelope extendido completo (124x104) -sea cual sea el estado del
  layout, ninguna posición es válida sin exceder el margen de 2cm/lado.
- `NO_FREE_RECT_FIT`: la caja SÍ entraría en el envelope extendido en
  principio, pero el cuboide libre concreto que se está evaluando (lo que
  quedó tras colocar el resto) es más chico que la huella de la caja -
  síntoma de fragmentación, no de un límite físico exterior."""
from dataclasses import dataclass, field

import config
from models import PalletV5
from src.packing_columnar import _reconstruir_en_construccion
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import _tiene_soporte_admisible

TOL = 1e-6

NO_FREE_RECT_FIT = "NO_FREE_RECT_FIT"
EDGE_OVERHANG = "EDGE_OVERHANG"
HEIGHT_LIMIT = "HEIGHT_LIMIT"
OVERLAP = "OVERLAP"
SUPPORT = "SUPPORT"
CATEGORY_LEVEL = "CATEGORY_LEVEL"
LAYER_HEIGHT = "LAYER_HEIGHT"
CAJAS_POR_PH = "CAJAS_POR_PH"
ORIENTATION = "ORIENTATION"

MOTIVOS = (
    ORIENTATION,
    HEIGHT_LIMIT,
    EDGE_OVERHANG,
    NO_FREE_RECT_FIT,
    OVERLAP,
    SUPPORT,
    CATEGORY_LEVEL,
    LAYER_HEIGHT,
    CAJAS_POR_PH,
)


@dataclass
class _DiagnosticoSKU:
    pendientes: int
    candidatos_evaluados: int = 0
    motivos: dict[str, int] = field(default_factory=lambda: {m: 0 for m in MOTIVOS})

    def a_dict(self) -> dict:
        return {
            "pendientes": self.pendientes,
            "candidatos_evaluados": self.candidatos_evaluados,
            **self.motivos,
        }


def cabe_en_envelope_extendido(cand: TorreCandidate) -> bool:
    """True si esta orientación, en su MEJOR caso (sin fragmentación, sin
    otras cajas), entraría en el envelope extendido completo (124x104) -si
    esto es False, ninguna posición es válida sin exceder el margen
    exterior de 2cm/lado, sea cual sea el estado del layout."""
    return (
        cand.largo <= config.PALLET_LARGO_EFECTIVO + TOL
        and cand.ancho <= config.PALLET_ANCHO_EFECTIVO + TOL
    )


def _motivo_para_cuboide(
    pallet: PalletV5, c, cand: TorreCandidate, tope_capa: int | None,
    nivel_sku: int, nivel_por_sku: dict[str, int],
) -> str | None:
    """Primer motivo (en orden de chequeo real, ver `_cuboide_admite_
    candidato`/`_fit_directo_o_con_tolerancia` en packing_bloques.py) por
    el que ESTE cuboide libre concreto no admite `cand`. `None` si sí
    entra (no debería pasar -si el candidato realmente cupiera en algún
    cuboide libre, el solver lo habría colocado)."""
    if cand.alto_caja > c.d + TOL:
        return HEIGHT_LIMIT

    if not cabe_en_envelope_extendido(cand):
        return EDGE_OVERHANG  # ni con el envelope completo entra en NINGÚN lado -no es fragmentación

    # [V6.02 sección 2, bug real encontrado escribiendo este diagnóstico]
    # NO se chequea acá la posición absoluta del cuboide (c.x/c.y contra
    # PALLET_LARGO/ANCHO + margen): un cuboide libre real (MaxRects) ya
    # está SIEMPRE contenido en [-margen, pallet+margen] por construcción,
    # así que ese chequeo nunca aporta información nueva -pero SÍ daba
    # falsos positivos de EDGE_OVERHANG para cuboides angostos pegados al
    # borde (ej. w=31 en x=91..122): la caja no entra porque el cuboide es
    # angosto (fragmentación), no porque exceda el borde -eso ya lo detecta
    # el chequeo de `NO_FREE_RECT_FIT` de abajo, con la semántica correcta.
    tolerancia = config.TOLERANCIA_OVERHANG_CM
    directo = cand.largo <= c.w + TOL and cand.ancho <= c.h + TOL
    if not directo and (cand.largo > c.w + tolerancia + TOL or cand.ancho > c.h + tolerancia + TOL):
        # La caja cabría en el envelope, pero ESTE cuboide (lo que quedó
        # libre acá, incluso con la tolerancia de apoyo) es más chico que
        # su huella -fragmentación del layout, no límite exterior.
        return NO_FREE_RECT_FIT
    if c.z > TOL:
        soportes = [t for t in pallet.torres if abs(t.z + t.altura - c.z) <= TOL]
        torre = crear_torre(cand, x=c.x, y=c.y, z=c.z, cantidad=1)
        if not _tiene_soporte_admisible(torre, soportes):
            return SUPPORT
    if tope_capa is not None:
        ya_en_esta_capa = sum(
            t.cantidad for t in pallet.torres if t.sku == cand.sku and abs(t.z - c.z) <= TOL
        )
        if ya_en_esta_capa >= tope_capa:
            return LAYER_HEIGHT
    if c.z > TOL:
        for t in pallet.torres:
            if abs((t.z + t.altura) - c.z) > TOL:
                continue
            if t.x + t.largo <= c.x + TOL or c.x + cand.largo <= t.x + TOL:
                continue
            if t.y + t.ancho <= c.y + TOL or c.y + cand.ancho <= t.y + TOL:
                continue
            if nivel_por_sku.get(t.sku, 0) > nivel_sku:
                return CATEGORY_LEVEL
    if c.z > TOL:
        for t in pallet.torres:
            if abs(t.z - c.z) <= TOL and abs(t.alto_caja - cand.alto_caja) > config.TOLERANCIA_ALTURA_CAMA_CM + TOL:
                return LAYER_HEIGHT
    return None


def diagnosticar(
    pallets: list[PalletV5],
    sin_colocar: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
) -> dict[str, dict]:
    """Para cada SKU en `sin_colocar`, cuenta motivos de rechazo probando
    CADA orientación candidata contra CADA cuboide libre de CADA pallet ya
    armado (estado final, congelado -no reabre ni modifica nada)."""
    if not sin_colocar:
        return {}

    construcciones = [_reconstruir_en_construccion(p) for p in pallets]

    resultado: dict[str, dict] = {}
    for sku, pendientes in sin_colocar.items():
        diag = _DiagnosticoSKU(pendientes=pendientes)
        candidatas = por_sku.get(sku, [])
        if not candidatas:
            diag.motivos[ORIENTATION] += 1
            resultado[sku] = diag.a_dict()
            continue

        tope_capa = capacidad_cama_por_sku.get(sku)
        nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
        tope_pallet = tope_pallet_por_sku.get(sku)

        for pc, pallet in zip(construcciones, pallets):
            ya_en_pallet = sum(t.cantidad for t in pallet.torres if t.sku == sku)
            if tope_pallet is not None and ya_en_pallet >= tope_pallet:
                for cand in candidatas:
                    diag.candidatos_evaluados += 1
                    diag.motivos[CAJAS_POR_PH] += 1
                continue
            for cand in candidatas:
                for c in pc.libres:
                    diag.candidatos_evaluados += 1
                    motivo = _motivo_para_cuboide(pallet, c, cand, tope_capa, nivel_sku, nivel_por_sku)
                    if motivo is not None:
                        diag.motivos[motivo] += 1

        if not pallets:
            diag.motivos[ORIENTATION] += 1

        resultado[sku] = diag.a_dict()

    return resultado


def formatear_reporte(diagnostico: dict[str, dict]) -> str:
    """Formato de ejemplo de la sección 5 del patch V6.01."""
    lineas = []
    for sku, d in diagnostico.items():
        lineas.append(f"SKU: {sku}")
        lineas.append(f"Pendientes: {d['pendientes']}")
        lineas.append("")
        lineas.append(f"Candidatos evaluados: {d['candidatos_evaluados']}")
        lineas.append("")
        for motivo in MOTIVOS:
            lineas.append(f"{motivo:18s}{d[motivo]:>8d}")
        lineas.append("")
    return "\n".join(lineas)
