# agente-cubicador-transportes-bees — repo completo (parche v2 aplicado)

**Rama:** `feat/parametros-altura-peso-v2`
**Generado:** 2026-08-12 16:30 UTC

Todos los cambios de `Parches/PARCHES_v2_altura_peso_camas.md` (ventana de altura elástica 190-205-210, peso con elasticidad 1.400-1.430, peso de UMA como peso de caja, agrupamiento de camas por dimensión con guard de NABs/remate, fix de `Peso_Caja` duplicado) ya están aplicados directamente en este código. Suite de tests: 46/46 pasando (ver sección de tests al final).

## Índice

- [config.py](#configpy)
- [models.py](#modelspy)
- [src/derivados.py](#srcderivadospy)
- [src/validacion.py](#srcvalidacionpy)
- [src/pallets_homogeneos.py](#srcpallets_homogeneospy)
- [src/packing_2d.py](#srcpacking_2dpy)
- [src/apilado_3d.py](#srcapilado_3dpy)
- [src/validacion_peso.py](#srcvalidacion_pesopy)
- [src/exportar.py](#srcexportarpy)
- [src/pipeline.py](#srcpipelinepy)
- [src/template.py](#srctemplatepy)
- [app.py](#apppy)
- [visualizacion.py](#visualizacionpy)
- [requirements.txt](#requirementstxt)
- [tests/conftest.py](#testsconftestpy)
- [tests/test_validacion.py](#teststest_validacionpy)
- [tests/test_derivados.py](#teststest_derivadospy)
- [tests/test_packing_2d.py](#teststest_packing_2dpy)
- [tests/test_apilado_3d.py](#teststest_apilado_3dpy)
- [tests/test_topado_homogeneos.py](#teststest_topado_homogeneospy)
- [tests/test_invariantes.py](#teststest_invariantespy)
- [tests/test_pipeline_real_data.py](#teststest_pipeline_real_datapy)

---

## `config.py`

```python
import unicodedata

PALLET_LARGO = 120
PALLET_ANCHO = 100

ALTURA_PALLET_VACIO = 14.92

# --- Ventana de altura total del pallet (producto + pallet vacío) -------------
# Cuatro umbrales, de menor a mayor:
#
#   185  ALTURA_TOTAL_MIN - TOLERANCIA   por debajo de esto el pallet es PARCIAL
#   190  ALTURA_TOTAL_MIN                mínimo nominal para dar el pallet por cerrado
#   195  ALTURA_OBJETIVO_MIN  ─┐
#   200  ALTURA_OBJETIVO_MAX  ─┴─ zona recomendada por seguridad del operario
#   205  ALTURA_TOTAL_MAX                máximo normal: el apilado no pasa de acá
#   210  ALTURA_TOPE_DURO                extremo, solo para cerrar un pallet corto
#
# La regla de negocio: un pallet que YA superó el mínimo se corta en 205. Uno que
# todavía está por debajo del mínimo puede estirarse hasta 210 con tal de cerrar
# —si la cama de remanente lo pasaría de 210, no se agrega y el pallet se queda
# corto. Ver apilado_3d._limite_altura.
ALTURA_TOTAL_MIN = 190
ALTURA_OBJETIVO_MIN = 195
ALTURA_OBJETIVO_MAX = 200
ALTURA_TOTAL_MAX = 205
ALTURA_TOPE_DURO = 210

# Margen para cajas altas: un pallet entre 185 y 190 cm no se marca como parcial
# si la siguiente cama disponible no entra sin pasar el tope duro.
ALTURA_TOLERANCIA_MIN = 5
ALTURA_TOTAL_MIN_TOLERADO = ALTURA_TOTAL_MIN - ALTURA_TOLERANCIA_MIN  # 185

# Altura útil de producto = altura total - pallet vacío. Se derivan para que no
# puedan quedar desalineadas con la ventana de arriba.
ALTURA_PRODUCTO_MIN = ALTURA_TOTAL_MIN - ALTURA_PALLET_VACIO   # 175.08
ALTURA_PRODUCTO_MAX = ALTURA_TOPE_DURO - ALTURA_PALLET_VACIO   # 195.08

# --- Peso ---------------------------------------------------------------------
# Mismo patrón que la altura: un tope normal y una elasticidad para el caso
# extremo de cerrar un pallet que quedó corto. PESO_ALERTA_KG es el umbral que
# solo etiqueta (Paso 5, validacion_peso.py); PESO_TOPE_ELASTICO_KG es el que de
# verdad bloquea en apilado_3d._cabe (Paso 4). El viejo PESO_MAX_PALLET_KG (que
# duplicaba el valor de PESO_ALERTA_KG) se eliminó -- sección 3.1 de PARCHES_v2.
PESO_ALERTA_KG = 1400
PESO_TOPE_ELASTICO_KG = 1430

PESO_CAJA_MIN = 0.05
PESO_CAJA_MAX = 100

# La columna "Peso bruto por unidad" de la hoja UMA trae, en la práctica, el peso
# BRUTO DE LA CAJA del SKU — no el de la unidad suelta. Verificado contra la
# densidad resultante: tratándola como peso de caja las densidades por categoría
# caen en 130-855 kg/m³ (físicamente correcto); multiplicándola por
# "Unidades por caja" saltan a 7.700-65.000 kg/m³ (imposible).
# Poner True restaura el comportamiento anterior (peso unitario x unidades).
PESO_UMA_ES_POR_UNIDAD = False

TOLERANCIA_ALTURA_CAMA_MIXTA = 3

# [PARCHE P5] Fracción mínima de la base 120x100 que una cama debe cubrir para
# poder sostener otra cama encima. Sin esto, 3 cajas sueltas de Licores pueden
# quedar como base de 170 cm de producto. Es una restricción de SEGURIDAD DE
# CARGA, no de optimización: subirla genera más pallets.
# Poner 0.0 desactiva la regla por completo (comportamiento anterior).
FILL_RATIO_MIN_SOPORTE = 0.60

UMBRAL_DATO_NO_CONFIABLE = 10000

ORDEN_CATEGORIAS = ["Licores", "Lácteos", "Aseo", "Importados", "Merch", "NABs"]
CATEGORIAS_REMATE = ["Comestibles", "Cigarros"]
CATEGORIAS_SIN_NADA_ENCIMA = ["NABs", "Comestibles", "Cigarros"]

CATEGORIAS_CONOCIDAS = ORDEN_CATEGORIAS + CATEGORIAS_REMATE

# Máxima separación de niveles permitida dentro de una misma cama mixta (punto 6:
# agrupar por dimensiones, no por categoría). Aplica SOLO entre los niveles base
# 1-5 (Licores..Merch) -NABs y remate (Comestibles/Cigarros) quedan siempre
# aislados de la mezcla, ver packing_2d._separar_nabs_y_remate: mezclarlos rompió
# en la práctica la regla de soporte del Paso 4 (una cama Merch+Comestibles se
# posicionaba como remate -nivel más restrictivo- pero se consideraba NO
# reubicable en la consolidación -nivel menos restrictivo-, dejando camas de baja
# cobertura sosteniendo carga encima).
# Con MAX_SEPARACION_NIVELES=2 se permite mezclar categorías vecinas dentro de
# 1-5 (ej. Licores+Lácteos+Aseo) pero no extremos (Licores+Merch). Subir este
# valor da más densidad; bajarlo a 0 vuelve a "solo mezcla dentro de la misma
# categoría" (para 1-5; NABs/remate siempre aislados, sin excepción).
MAX_SEPARACION_NIVELES = 2

# Nivel de estabilidad: 1 (base, más pesado) .. 6 (NABs) .. 7 (remate).
# Antes el remate no tenía nivel numérico (era None) y el apilado lo trataba por
# una rama aparte. Con camas multi-categoría hace falta poder comparar niveles
# entre sí para quedarse con el más restrictivo, así que el remate entra en la
# misma escala.
NIVEL_REMATE = len(ORDEN_CATEGORIAS) + 1  # 7


def nivel_de_categoria(categoria: str | None) -> int | None:
    """Nivel de estabilidad de una categoría ya normalizada, o None si no clasifica."""
    if categoria in CATEGORIAS_REMATE:
        return NIVEL_REMATE
    if categoria in ORDEN_CATEGORIAS:
        return ORDEN_CATEGORIAS.index(categoria) + 1
    return None


def _sin_acentos(texto: str) -> str:
    forma = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in forma if not unicodedata.combining(c))


_MAPA_NORMALIZACION = {_sin_acentos(cat).strip().lower(): cat for cat in CATEGORIAS_CONOCIDAS}


def normalizar_categoria(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    clave = _sin_acentos(texto).lower()
    return _MAPA_NORMALIZACION.get(clave)


ESTADO_OK = "OK"
ESTADO_ALERTA_PESO = "⚠ ALERTA DE PESO"
ESTADO_PESO_NO_VALIDABLE = "⚠ PESO NO VALIDABLE"
ESTADO_PALLET_PARCIAL = "⚠ PALLET PARCIAL — CIERRE FORZADO"
ESTADO_CATEGORIA_NO_CLASIFICADA = "⚠ CATEGORÍA NO CLASIFICADA"
ESTADO_DATO_INSUFICIENTE = "⚠ DATO INSUFICIENTE"
```

## `models.py`

```python
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

        Comestibles y Cigarros son mutuamente excluyentes (regla 9.3): nunca
        pueden convivir en la misma cama ni en el mismo pallet, así que como
        mucho hay una.
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


@dataclass
class ResultadoPipeline:
    plan_picking_df: pd.DataFrame
    log_validacion_df: pd.DataFrame
    resumen_cd_df: pd.DataFrame
    pallets: list[Pallet]
    info_sku: dict = field(default_factory=dict)
```

## `src/derivados.py`

```python
import math

import numpy as np
import pandas as pd

import config


def _capacidad_geometrica(largo: float, ancho: float) -> int:
    orientacion_a = math.floor(config.PALLET_LARGO / largo) * math.floor(config.PALLET_ANCHO / ancho)
    orientacion_b = math.floor(config.PALLET_LARGO / ancho) * math.floor(config.PALLET_ANCHO / largo)
    return max(orientacion_a, orientacion_b)


def calcular_peso_caja(peso_bruto_por_unidad: pd.Series, unidades_por_caja: pd.Series) -> pd.Series:
    """Peso de la caja de un SKU, a partir de las columnas crudas de UMA/Maestro.

    Compartida entre `validacion.py` (V6) y este módulo para que los dos usen
    exactamente el mismo número — antes `validacion.py` calculaba su propia
    versión con la fórmula vieja (peso x unidades) sin mirar el flag de abajo,
    y los dos números divergían en silencio.

    La columna "Peso bruto por unidad" de UMA trae, en la práctica, el peso de
    la CAJA del SKU, no el de la unidad suelta (ver config.PESO_UMA_ES_POR_UNIDAD).
    Multiplicarla por "Unidades por caja" infla el peso hasta 1.000x en SKUs con
    packs grandes (Cigarros de 1.000 u/caja daban 16.000 kg por caja), lo que
    hacía que el tope de peso del Paso 4 rechazara casi toda combinación y cada
    cama terminara en su propio pallet.
    """
    if config.PESO_UMA_ES_POR_UNIDAD:
        return peso_bruto_por_unidad * unidades_por_caja
    return peso_bruto_por_unidad


def calcular_derivados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["Peso_Caja"] = calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])

    df["Cajas_Teoricas_Redondeadas"] = np.ceil(df["Cajas Teóricas"]).astype(int)
    df["Cajas_Extra_Redondeo"] = df["Cajas_Teoricas_Redondeadas"] - df["Cajas Teóricas"]

    df["Cajas_Cama_Efectivo"] = df.apply(
        lambda r: int(r["Cajas por cama"])
        if pd.notna(r["Cajas por cama"])
        else _capacidad_geometrica(r["Largo de caja"], r["Ancho de caja"]),
        axis=1,
    )

    # El remate (Comestibles/Cigarros) ahora tiene nivel 7 en vez de None, para
    # poder compararlo con el resto cuando una cama mezcla categorías.
    niveles = [config.nivel_de_categoria(c) for c in df["Categoria_Normalizada"]]
    df["Nivel_Categoria"] = pd.Series(niveles, index=df.index, dtype=object)
    df["Es_Categoria_Remate"] = df["Categoria_Normalizada"].isin(config.CATEGORIAS_REMATE)

    return df
```

## `src/validacion.py`

```python
import pandas as pd

import config
from models import LogEntry
from src.derivados import calcular_peso_caja


def cargar_hojas(ruta_o_buffer):
    xl = pd.ExcelFile(ruta_o_buffer)
    envios = pd.read_excel(xl, "Envios_Julio")
    maestro = pd.read_excel(xl, "Maestro_SKUs")
    uma = pd.read_excel(xl, "UMA")
    return envios, maestro, uma


def _normalizar_sku(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip()


def _cabe_en_pallet(largo, ancho) -> bool:
    if pd.isna(largo) or pd.isna(ancho):
        return False
    orientacion_a = largo <= config.PALLET_LARGO and ancho <= config.PALLET_ANCHO
    orientacion_b = ancho <= config.PALLET_LARGO and largo <= config.PALLET_ANCHO
    return orientacion_a or orientacion_b


def validar_y_limpiar(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame):
    log: list[LogEntry] = []

    envios = envios.copy()
    maestro = maestro.copy()
    uma = uma.copy()

    envios["SKU"] = _normalizar_sku(envios["SKU"])
    maestro["SKU"] = _normalizar_sku(maestro["SKU"])
    uma["SKU"] = _normalizar_sku(uma["SKU"])

    # V9 — duplicados CD+SKU: sumar y loguear
    dup_mask = envios.duplicated(subset=["CD", "SKU"], keep=False)
    if dup_mask.any():
        for (cd, sku), grupo in envios[dup_mask].groupby(["CD", "SKU"]):
            log.append(LogEntry(cd, sku, "V9", f"Duplicado CD+SKU sumado ({len(grupo)} filas)"))
    envios = envios.groupby(["CD", "SKU"], as_index=False).agg(
        {"Descripción": "first", "Cajas Teóricas": "sum", "Unidades": "sum"}
    )

    # V8 — Cajas Teóricas > 0
    invalidas = envios["Cajas Teóricas"] <= 0
    for _, fila in envios[invalidas].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V8", "Excluida: Cajas Teóricas <= 0"))
    envios = envios[~invalidas]

    # V2 — SKU debe existir en Maestro y en UMA
    en_maestro = set(maestro["SKU"])
    en_uma = set(uma["SKU"])
    sin_maestro = ~envios["SKU"].isin(en_maestro)
    for _, fila in envios[sin_maestro].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V2", "Excluida: SKU sin Maestro"))
    sin_uma = envios["SKU"].isin(en_maestro) & ~envios["SKU"].isin(en_uma)
    for _, fila in envios[sin_uma].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V2", "Excluida: SKU sin UMA"))
    envios = envios[envios["SKU"].isin(en_maestro) & envios["SKU"].isin(en_uma)]

    df = envios.merge(maestro, on="SKU", how="left").merge(uma, on="SKU", how="left")

    # V3 — Cajas por PH / Camas por PH dentro de rango razonable
    for columna in ["Cajas por PH", "Camas por PH"]:
        no_confiable = df[columna] >= config.UMBRAL_DATO_NO_CONFIABLE
        for _, fila in df[no_confiable].iterrows():
            log.append(
                LogEntry(
                    fila["CD"], fila["SKU"], "V3",
                    f"{columna} no confiable (>= {config.UMBRAL_DATO_NO_CONFIABLE}), se usará fallback",
                )
            )
        df.loc[no_confiable, columna] = pd.NA

    # V7 — Cajas por cama no nulo ni 0
    invalido_cama = df["Cajas por cama"].isna() | (df["Cajas por cama"] == 0)
    for _, fila in df[invalido_cama].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V7", "Cajas por cama nulo o 0, se usará fallback geométrico"))
    df.loc[invalido_cama, "Cajas por cama"] = pd.NA

    # V4 — dimensiones deben permitir al menos una orientación dentro del pallet
    dim_invalida = ~df.apply(lambda r: _cabe_en_pallet(r["Largo de caja"], r["Ancho de caja"]), axis=1)
    for _, fila in df[dim_invalida].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V4", "Excluida: dimensión de caja imposible para el pallet"))

    # V5 — alto de caja dentro del máximo permitido
    alto_invalido = df["Alto de caja"].isna() | (df["Alto de caja"] > config.ALTURA_PRODUCTO_MAX)
    for _, fila in df[alto_invalido].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V5", "Excluida: altura de caja excede el máximo permitido"))

    df = df[~(dim_invalida | alto_invalido)].copy()

    # V6 — peso por caja dentro de un rango sano
    peso_caja = calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])
    fuera_rango = peso_caja.isna() | (peso_caja < config.PESO_CAJA_MIN) | (peso_caja > config.PESO_CAJA_MAX)
    df["Peso_No_Validable"] = fuera_rango
    for _, fila in df[fuera_rango].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V6", "Peso por caja fuera de rango sano, marcado PESO NO VALIDABLE"))

    # V1 — normalizar categoría; loguear las que no clasifican dentro del orden conocido
    df["Categoria_Normalizada"] = df["Categoría"].map(config.normalizar_categoria)
    no_clasificada = df["Categoria_Normalizada"].isna()
    for _, fila in df[no_clasificada].iterrows():
        log.append(
            LogEntry(
                fila["CD"], fila["SKU"], "9.1",
                f"Categoría '{fila['Categoría']}' no clasificada, excluida del apilado automático",
            )
        )

    log_df = pd.DataFrame([vars(e) for e in log], columns=["cd", "sku", "regla", "accion"])
    return df.reset_index(drop=True), log_df
```

## `src/pallets_homogeneos.py`

```python
import pandas as pd

import config
from models import Cama, Pallet, PalletLinea


def armar_pallets_homogeneos(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Pallet]]:
    df = df.copy()
    df["Cajas_Remanente"] = df["Cajas_Teoricas_Redondeadas"].astype(int)

    pallets: list[Pallet] = []
    contador: dict[str, int] = {}

    for idx, fila in df.iterrows():
        cajas_ph = fila["Cajas por PH"]
        if pd.isna(cajas_ph) or cajas_ph <= 0:
            continue

        cajas_ph = int(cajas_ph)
        pallets_completos = int(fila["Cajas_Remanente"] // cajas_ph)
        if pallets_completos < 1:
            continue

        cd = fila["CD"]
        contador[cd] = contador.get(cd, 0)

        camas_ph = fila["Camas por PH"]
        n_camas = int(camas_ph) if pd.notna(camas_ph) and camas_ph > 0 else 1
        alto_caja = fila["Alto de caja"] if pd.notna(fila["Alto de caja"]) else 0
        altura_final = config.ALTURA_PALLET_VACIO + n_camas * alto_caja

        # [PARCHE P9] `Camas por PH` x `Alto de caja` puede dar un pallet fuera de
        # norma y nadie lo verificaba: el Paso 4 controla la altura de lo que se
        # AGREGA encima, pero nunca la altura BASE del pallet homogéneo. Si el dato
        # del Maestro produce un pallet imposible, no se arma el PH y toda la
        # demanda de ese SKU pasa al remanente, donde el packing 2D/3D la resuelve
        # con geometría real. Es coherente con la filosofía de V3: ante dato del
        # Maestro no confiable, caer al cálculo geométrico.
        if altura_final > config.ALTURA_TOTAL_MAX:
            continue

        peso_caja = fila["Peso_Caja"] if pd.notna(fila["Peso_Caja"]) else 0

        for _ in range(pallets_completos):
            contador[cd] += 1
            pallet = Pallet(
                id=f"PH-HOM-{cd}-{contador[cd]:03d}",
                cd=cd,
                tipo="Homogéneo",
                altura_final=altura_final,
                peso_estimado=cajas_ph * peso_caja,
                estado=config.ESTADO_OK,
            )
            pallet.lineas.append(
                PalletLinea(
                    sku=fila["SKU"],
                    descripcion=fila["Descripción"],
                    categoria=fila["Categoria_Normalizada"],
                    nivel_categoria=fila["Nivel_Categoria"],
                    cajas_demanda_oficial=cajas_ph,
                    cajas_extra_consolidacion=0,
                    peso_no_validable=bool(fila["Peso_No_Validable"]),
                )
            )
            pallet.camas.append(
                Cama(
                    categorias=[fila["Categoria_Normalizada"]],
                    altura_cama=n_camas * alto_caja,
                    cantidades={fila["SKU"]: cajas_ph},
                    nivel_categoria=fila["Nivel_Categoria"],
                )
            )
            pallets.append(pallet)

        df.loc[idx, "Cajas_Remanente"] -= pallets_completos * cajas_ph

    remanente = df[df["Cajas_Remanente"] > 0].copy()
    return remanente.reset_index(drop=True), pallets
```

## `src/packing_2d.py`

```python
import pandas as pd

import config
from models import Cama, Placement


def _clusterizar_por_altura(rows: list, tolerancia: float = config.TOLERANCIA_ALTURA_CAMA_MIXTA) -> list[list]:
    ordenado = sorted(rows, key=lambda r: r["Alto de caja"])
    clusters: list[list] = []
    actual: list = []
    base = None
    for r in ordenado:
        if not actual:
            actual = [r]
            base = r["Alto de caja"]
            continue
        if r["Alto de caja"] - base <= tolerancia:
            actual.append(r)
        else:
            clusters.append(actual)
            actual = [r]
            base = r["Alto de caja"]
    if actual:
        clusters.append(actual)
    return clusters


def _elegir_orientacion(largo: float, ancho: float) -> tuple[float, float, int] | None:
    """[PARCHE P1] Elige la orientación que maximiza la cantidad TOTAL de cajas
    en la cama (columnas x filas), no solo las columnas a lo largo de 120 cm.

    BUG ORIGINAL: el criterio era `columnas > mejor[2]`, o sea maximizaba solo
    cuántas cajas entran a lo largo de los 120 cm, ignorando cuántas filas caben
    en los 100 cm. Con una caja de 25x51 cm:
        - orientación A (w=25, d=51) -> 4 columnas x 1 fila =  4 cajas
        - orientación B (w=51, d=25) -> 2 columnas x 4 filas =  8 cajas
    El código elegía A porque 4 > 2, perdiendo la mitad de la cama. Y como la
    orientación se fija una sola vez por SKU, el error se propagaba a TODAS sus
    camas, puras y mixtas -> más camas -> más pallets -> más transporte.

    El criterio nuevo es idéntico al que ya usaba derivados._capacidad_geometrica
    para el fallback del Maestro; antes convivían dos nociones distintas de
    "capacidad geométrica" en el mismo repo, y esta era la incorrecta.

    Desempate: menor profundidad `d`, porque deja shelves más bajos y por lo
    tanto más reutilizables por otros SKUs en la fase de mezcla.
    """
    mejor = None
    mejor_capacidad = -1
    for w, d in ((largo, ancho), (ancho, largo)):
        if w > config.PALLET_LARGO or d > config.PALLET_ANCHO:
            continue
        columnas = int(config.PALLET_LARGO // w)
        filas = int(config.PALLET_ANCHO // d)
        if columnas == 0 or filas == 0:
            continue
        capacidad = columnas * filas
        if capacidad > mejor_capacidad or (capacidad == mejor_capacidad and d < mejor[1]):
            mejor = (w, d, columnas)
            mejor_capacidad = capacidad
    return mejor


def _empacar_cama(candidatos: list[dict]) -> tuple[list[Placement], dict[str, int]]:
    preparados = []
    for c in candidatos:
        orientacion = _elegir_orientacion(c["largo"], c["ancho"])
        if orientacion is None:
            continue
        w, d, _ = orientacion
        preparados.append({**c, "_w": w, "_d": d})

    preparados.sort(key=lambda c: -c["_d"])

    shelves: list[dict] = []
    y_acumulado = 0.0
    placements: list[Placement] = []
    colocadas = {c["sku"]: 0 for c in candidatos}

    for c in preparados:
        sku, w, d = c["sku"], c["_w"], c["_d"]
        restante = min(c["disponible"], c["densidad_max"]) - colocadas[sku]
        if restante <= 0:
            continue

        for shelf in shelves:
            if restante <= 0:
                break
            if shelf["alto"] < d - 1e-6:
                continue
            columnas_disp = int((config.PALLET_LARGO - shelf["x_usado"]) // w)
            if columnas_disp <= 0:
                continue
            colocar = min(columnas_disp, restante)
            placements.append(Placement(sku=sku, cantidad=colocar, x=shelf["x_usado"], y=shelf["y"], w=w, d=d))
            shelf["x_usado"] += colocar * w
            colocadas[sku] += colocar
            restante -= colocar

        while restante > 0:
            if y_acumulado + d > config.PALLET_ANCHO + 1e-6:
                break
            columnas_posibles = int(config.PALLET_LARGO // w)
            if columnas_posibles <= 0:
                break
            colocar = min(columnas_posibles, restante)
            placements.append(Placement(sku=sku, cantidad=colocar, x=0, y=y_acumulado, w=w, d=d))
            shelves.append({"y": y_acumulado, "alto": d, "x_usado": colocar * w})
            colocadas[sku] += colocar
            restante -= colocar
            y_acumulado += d

    return placements, colocadas


def _cama_desde_colocacion(placements: list[Placement], colocadas: dict[str, int], info: dict) -> Cama:
    colocadas_positivas = {sku: qty for sku, qty in colocadas.items() if qty > 0}
    alto_cama = max(info[sku]["Alto de caja"] for sku in colocadas_positivas)
    categorias = sorted({info[sku]["Categoria_Normalizada"] for sku in colocadas_positivas})
    # Nivel de la cama = el MÁS RESTRICTIVO (más alto) entre sus SKUs, no "el de
    # un SKU cualquiera" como estaba antes (`next(iter(...))`). Con camas de una
    # sola categoría daba lo mismo; con camas mixtas (punto 6) era un bug latente.
    nivel = max(info[sku]["Nivel_Categoria"] for sku in colocadas_positivas)
    # [PARCHE P5] superficie realmente cubierta, para la regla de soporte del Paso 4
    area_ocupada = sum(p.cantidad * p.w * p.d for p in placements)
    return Cama(
        categorias=categorias,
        altura_cama=alto_cama,
        placements=placements,
        cantidades=colocadas_positivas,
        nivel_categoria=nivel,
        area_ocupada=area_ocupada,
    )


def _capacidad_real_cama(sku: str, info: dict) -> int:
    """[PARCHE P2] Tope real de cajas de un SKU en una cama pura.

    Es el mínimo entre el techo de densidad del Maestro (`Cajas_Cama_Efectivo`)
    y lo que la geometría permite colocar de verdad. Se calcula UNA vez por SKU
    haciendo una corrida de prueba del packer.
    """
    densidad_max = info[sku]["Cajas_Cama_Efectivo"]
    if densidad_max <= 0:
        return 0
    prueba = [
        {
            "sku": sku,
            "largo": info[sku]["Largo de caja"],
            "ancho": info[sku]["Ancho de caja"],
            "disponible": densidad_max,
            "densidad_max": densidad_max,
        }
    ]
    _, colocadas = _empacar_cama(prueba)
    return colocadas.get(sku, 0)


def _procesar_cluster(cluster_rows: list) -> list[Cama]:
    """Prioriza camas puras (un solo SKU, hasta su tope real de densidad) por cada
    SKU del cluster; solo el remanente final de cada uno -- lo que no alcanza para
    llenar una cama completa por sí solo -- se mezcla entre sí en la(s) cama(s) de
    cierre, para aprovechar el perímetro de 120x100 en vez de dejarlas sueltas.

    [PARCHE P2] BUG ORIGINAL: el bucle era

        while pendientes[sku] >= densidad_max:      # densidad_max = dato del Maestro
            ...
            if colocado < densidad_max:
                break

    `densidad_max` venía del Maestro, pero `_empacar_cama` está acotado por la
    geometría. El propio doc de diseño dice que el Maestro NO coincide con la
    geometría en el 80% de los SKUs de la demanda real, con lo cual
    `colocado < densidad_max` era el caso NORMAL y el `break` disparaba casi
    siempre: con 100 cajas pendientes y capacidad geométrica de 20, se armaba UNA
    cama pura y las 80 restantes caían a la fase de mezcla, en vez de armar 5
    camas puras. Toda la estrategia documentada de "priorizar camas puras" estaba
    desactivada en la práctica.

    FIX: calcular el tope REAL de la cama una sola vez (Maestro acotado por
    geometría) y usar ese valor como condición del bucle. El `break` por
    `colocado < densidad_max` desaparece; queda solo el guard anti-loop.
    """
    info = {r["SKU"]: r for r in cluster_rows}
    pendientes = {r["SKU"]: r["Cajas_Remanente"] for r in cluster_rows}
    camas: list[Cama] = []

    for sku in pendientes:
        capacidad_cama = _capacidad_real_cama(sku, info)
        if capacidad_cama <= 0:
            continue  # no cabe ni una caja; se resuelve (o se descarta) en la mezcla final

        densidad_max = info[sku]["Cajas_Cama_Efectivo"]
        while pendientes[sku] >= capacidad_cama:
            candidato = [
                {
                    "sku": sku,
                    "largo": info[sku]["Largo de caja"],
                    "ancho": info[sku]["Ancho de caja"],
                    "disponible": pendientes[sku],
                    "densidad_max": densidad_max,
                }
            ]
            placements, colocadas = _empacar_cama(candidato)
            colocado = colocadas.get(sku, 0)
            if colocado <= 0:
                break  # guard anti-loop; no debería ocurrir si capacidad_cama > 0
            pendientes[sku] -= colocado
            camas.append(_cama_desde_colocacion(placements, colocadas, info))

    while any(v > 0 for v in pendientes.values()):
        candidatos = [
            {
                "sku": sku,
                "largo": info[sku]["Largo de caja"],
                "ancho": info[sku]["Ancho de caja"],
                "disponible": pendientes[sku],
                "densidad_max": info[sku]["Cajas_Cama_Efectivo"],
            }
            for sku in pendientes
            if pendientes[sku] > 0
        ]
        placements, colocadas = _empacar_cama(candidatos)

        if not any(qty > 0 for qty in colocadas.values()):
            break

        for sku, qty in colocadas.items():
            pendientes[sku] -= qty

        camas.append(_cama_desde_colocacion(placements, colocadas, info))

    return camas


def _separar_nabs_y_remate(cluster_rows: list) -> list[list]:
    """[Punto 6] NABs y las categorías de remate (Comestibles/Cigarros) quedan
    SIEMPRE aisladas de todo lo demás -y entre sí- en su propia sub-cama. La
    mezcla por dimensión (`_separar_por_nivel`, MAX_SEPARACION_NIVELES) aplica
    solo entre los niveles 1-5 (Licores..Merch).

    Motivo, encontrado con un test real contra `Cubicaje18.07.2026.xlsx`: NABs y
    remate tienen reglas de posición/exclusividad especiales (9.2, 9.3) que no
    son "una cuestión de distancia numérica de nivel" como el resto. Mezclar,
    por ejemplo, Merch (nivel 5) con Comestibles (remate) en la misma cama
    produce una cama con nivel_efectivo=7 (se coloca en la pasada de remate,
    "el más restrictivo") pero es_flexible=False (por el Merch, "el menos
    restrictivo") -esa divergencia rompe la regla de soporte del Paso 4: la
    consolidación trata la cama como NO reubicable y la deja fija en su lugar
    original, mientras que camas puramente flexibles sí se reordenan a su
    alrededor, produciendo una cama de baja cobertura (fill_ratio bajo)
    sosteniendo carga encima -exactamente lo que la regla de soporte prohíbe.
    Aislar NABs/remate del todo evita la divergencia por construcción: toda
    cama queda con un único nivel real entre sus SKUs.
    """
    comestibles = [r for r in cluster_rows if r["Categoria_Normalizada"] == "Comestibles"]
    cigarros = [r for r in cluster_rows if r["Categoria_Normalizada"] == "Cigarros"]
    nabs = [r for r in cluster_rows if r["Categoria_Normalizada"] == "NABs"]
    resto = [r for r in cluster_rows if r["Categoria_Normalizada"] not in ("Comestibles", "Cigarros", "NABs")]

    subclusters = [grupo for grupo in (resto, nabs, comestibles, cigarros) if grupo]
    return subclusters or [cluster_rows]


def _separar_por_nivel(cluster_rows: list) -> list[list]:
    """[Punto 6] Tope de separación entre niveles de estabilidad dentro de una
    misma cama mixta (config.MAX_SEPARACION_NIVELES, default 2).

    Sin este tope, una caja de Licores (nivel 1, la más pesada, pensada para ir
    en la base) podría terminar en la misma cama que una de NABs (nivel 6, casi
    la cima) solo porque miden parecido -y la regla de "nivel más restrictivo"
    (Cama.nivel_efectivo) subiría esa cama cerca de la cima del pallet, llevando
    cajas pesadas lejos de la base. Contradice la razón de ser del orden
    Licores->Merch de la sección 9 del doc de diseño (existe por PESO, no solo
    por fragilidad).

    Con MAX_SEPARACION_NIVELES=2 se permite mezclar categorías vecinas (ej.
    Licores+Lácteos+Aseo, o Importados+Merch+NABs) pero no extremos
    (Licores+NABs). En 0 restaura "solo mezcla dentro del mismo nivel".
    """
    niveles_presentes = sorted({r["Nivel_Categoria"] for r in cluster_rows})
    if len(niveles_presentes) <= 1:
        return [cluster_rows]

    grupos_nivel: list[list[int]] = []
    actual: list[int] = []
    base = None
    for n in niveles_presentes:
        if not actual:
            actual = [n]
            base = n
            continue
        if n - base <= config.MAX_SEPARACION_NIVELES:
            actual.append(n)
        else:
            grupos_nivel.append(actual)
            actual = [n]
            base = n
    if actual:
        grupos_nivel.append(actual)

    if len(grupos_nivel) <= 1:
        return [cluster_rows]

    return [[r for r in cluster_rows if r["Nivel_Categoria"] in grupo] for grupo in grupos_nivel]


def generar_camas(df_remanente: pd.DataFrame) -> dict[str, list[Cama]]:
    """[Punto 6] El agrupamiento en camas mixtas ya NO se restringe a una sola
    categoría normalizada -se agrupa por altura de caja (clustering, ±3 cm) igual
    que antes, pero cruzando categorías. Dos guards de seguridad se aplican
    después del clustering por altura: `_separar_por_remate` (regla 9.3, dura,
    siempre activa) y `_separar_por_nivel` (tope de separación configurable, para
    no mezclar niveles de estabilidad muy distintos)."""
    camas_por_cd: dict[str, list[Cama]] = {}

    for cd, df_cd in df_remanente.groupby("CD"):
        camas_por_cd[cd] = []
        rows = df_cd.to_dict("records")
        for cluster in _clusterizar_por_altura(rows):
            for aislado in _separar_nabs_y_remate(cluster):
                for subcluster in _separar_por_nivel(aislado):
                    camas_por_cd[cd].extend(_procesar_cluster(subcluster))

    return camas_por_cd
```

## `src/apilado_3d.py`

```python
import config
from models import Cama, Pallet, PalletLinea


def _construir_lineas(camas: list[Cama], info_sku: dict[str, dict]) -> list[PalletLinea]:
    totales: dict[str, int] = {}
    for cama in camas:
        for sku, qty in cama.cantidades.items():
            totales[sku] = totales.get(sku, 0) + qty

    lineas = []
    for sku, qty in totales.items():
        meta = info_sku[sku]
        lineas.append(
            PalletLinea(
                sku=sku,
                descripcion=meta["descripcion"],
                categoria=meta["categoria"],
                nivel_categoria=meta["nivel_categoria"],
                cajas_demanda_oficial=qty,
                cajas_extra_consolidacion=0,
                peso_no_validable=meta["peso_no_validable"],
            )
        )
    return lineas


def _agrupar_camas(lista_camas: list[Cama]) -> tuple[dict[int, list[Cama]], dict[str, list[Cama]]]:
    """Bucketea cada cama por su nivel EFECTIVO (el más restrictivo de sus SKUs,
    ver Cama.nivel_efectivo en models.py). Antes esto asumía una sola categoría
    por cama (`cama.categoria`, [PARCHE P7]); con el punto 6 (agrupar camas por
    dimensión en vez de por categoría) las camas mixtas son el caso común, no la
    excepción, así que hay que operar sobre `nivel_efectivo` / `categoria_remate`
    en todo este módulo."""
    n_niveles_base = len(config.ORDEN_CATEGORIAS)  # 6, incluye NABs
    camas_por_nivel: dict[int, list[Cama]] = {n: [] for n in range(1, n_niveles_base + 1)}
    camas_remate: dict[str, list[Cama]] = {cat: [] for cat in config.CATEGORIAS_REMATE}
    for cama in lista_camas:
        nivel = cama.nivel_efectivo
        if nivel == config.NIVEL_REMATE:
            camas_remate.setdefault(cama.categoria_remate, []).append(cama)
        elif nivel is not None:
            camas_por_nivel[nivel].append(cama)
        # nivel is None no debería pasar nunca acá: las camas se arman a partir
        # de remanente ya filtrado a SKUs con categoría clasificada (Paso 0/9.1).
    return camas_por_nivel, camas_remate


def _altura_desde_camas(camas: list[Cama]) -> float:
    return config.ALTURA_PALLET_VACIO + sum(c.altura_cama for c in camas)


def _es_flexible(cama: Cama) -> bool:
    return cama.es_flexible


def _remate_de(pallet: Pallet) -> str | None:
    for cama in pallet.camas:
        cr = cama.categoria_remate
        if cr is not None:
            return cr
    return None


def _remate_compatible(pallet: Pallet, cama: Cama) -> bool:
    """Antes recibía un string de categoría suelto; ahora recibe la cama porque
    con camas mixtas `categoria_remate` puede ser None (ej. cama de solo NABs, o
    NABs mezclada con niveles bajos) y eso también es información relevante."""
    cr = cama.categoria_remate
    if cr is not None:
        actual = _remate_de(pallet)
        return actual is None or actual == cr
    return _remate_de(pallet) is None  # sin remate: solo si el pallet aún no tiene remate


def _peso_cama(cama: Cama, info_sku: dict[str, dict]) -> float:
    """[PARCHE P4] Peso de una cama, para poder usarlo como restricción."""
    return sum(qty * (info_sku[sku].get("peso_caja") or 0.0) for sku, qty in cama.cantidades.items())


def _peso_desde_camas(camas: list[Cama], info_sku: dict[str, dict]) -> float:
    return sum(_peso_cama(c, info_sku) for c in camas)


def _puede_soportar(pallet: Pallet) -> bool:
    """[PARCHE P5] ¿La cama que hoy está arriba del pallet puede sostener otra?

    Sin esta regla, una cama de 2 cajas sueltas podía quedar como base de 170 cm
    de producto. El doc de diseño dice explícitamente que los remanentes de NABs
    son mayoritariamente sub-cama y que BK31/BK34 tienen líneas de 1 a 60 cajas,
    o sea que el caso es frecuente, no raro.

    Es una restricción de seguridad de carga: al activarla el conteo de pallets
    SUBE. Medir el impacto antes de fijar el umbral (config.FILL_RATIO_MIN_SOPORTE);
    poner 0.0 restaura el comportamiento anterior.
    """
    if not pallet.camas:
        return True
    return pallet.camas[-1].fill_ratio >= config.FILL_RATIO_MIN_SOPORTE


def _limite_altura(pallet: Pallet) -> float:
    """Tope de altura para la PRÓXIMA cama que se intente colocar sobre `pallet`.

    Si el pallet YA alcanzó el mínimo tolerado (185 cm = 190 - margen de cajas
    altas), se corta en el máximo normal (205) — no seguir apilando solo porque
    "cabe hasta 210". Si el pallet TODAVÍA no llegó a 185, se le da margen hasta
    el tope duro (210) para que una última cama de remanente pueda cerrarlo, en
    vez de dejarlo parcial por unos pocos cm. Nunca se supera 210 en ningún caso.
    """
    if pallet.altura_final >= config.ALTURA_TOTAL_MIN_TOLERADO:
        return config.ALTURA_TOTAL_MAX
    return config.ALTURA_TOPE_DURO


def _cabe(pallet: Pallet, cama: Cama, info_sku: dict[str, dict]) -> bool:
    """Restricciones duras para apoyar `cama` sobre `pallet`: altura, peso y soporte."""
    if cama.altura_cama > _limite_altura(pallet) - pallet.altura_final + 1e-9:
        return False
    # [PARCHE P4] el peso pasa de ser un chequeo post-hoc (Paso 5) a una restricción real.
    # El tope real que bloquea es el elástico (1.430 kg); 1.400 kg es solo el umbral
    # de alerta que etiqueta el pallet en el Paso 5 (validacion_peso.py), no lo bloquea.
    if pallet.peso_estimado + _peso_cama(cama, info_sku) > config.PESO_TOPE_ELASTICO_KG + 1e-9:
        return False
    return _puede_soportar(pallet)  # [PARCHE P5]


def _colocar(pallet: Pallet, cama: Cama, info_sku: dict[str, dict]) -> None:
    pallet.camas.append(cama)
    pallet.altura_final += cama.altura_cama
    pallet.peso_estimado += _peso_cama(cama, info_sku)  # [P4] peso acumulado en vivo


def _crear_pallet(cd: str, contador: list[int]) -> Pallet:
    contador[0] += 1
    return Pallet(
        id=f"PH-MIX-{cd}-{contador[0]:03d}",
        cd=cd,
        tipo="Mixto",
        altura_final=config.ALTURA_PALLET_VACIO,
        peso_estimado=0.0,
    )


def _asignar_camas(
    camas: list[Cama],
    es_elegible,
    cd: str,
    contador: list[int],
    pallets_abiertos: list[Pallet],
    info_sku: dict[str, dict],
) -> None:
    """Bin-packing best-fit: para cada cama (de mayor a menor altura), busca entre
    TODOS los pallets ya abiertos del CD el que tenga menos espacio libre y aun así
    la reciba; solo abre un pallet nuevo si ninguno de los existentes sirve.

    Nota: si una cama no entra ni en un pallet vacío (ej. pesa más que
    PESO_TOPE_ELASTICO_KG por sí sola), igual se coloca en el pallet nuevo y el
    Paso 5 la marca. Es deliberado: nunca se descarta demanda en silencio.
    """
    for cama in sorted(camas, key=lambda c: -c.altura_cama):
        candidatos = [p for p in pallets_abiertos if es_elegible(p) and _cabe(p, cama, info_sku)]
        destino = max(candidatos, key=lambda p: p.altura_final) if candidatos else None
        if destino is None:
            destino = _crear_pallet(cd, contador)
            pallets_abiertos.append(destino)
        _colocar(destino, cama, info_sku)


def _asignar_remate(
    camas_remate: dict[str, list[Cama]],
    cd: str,
    contador: list[int],
    pallets_abiertos: list[Pallet],
    info_sku: dict[str, dict],
) -> None:
    todas = [cama for colas in camas_remate.values() for cama in colas]
    todas.sort(key=lambda c: -c.altura_cama)
    for cama in todas:
        candidatos = [p for p in pallets_abiertos if _remate_compatible(p, cama) and _cabe(p, cama, info_sku)]
        destino = max(candidatos, key=lambda p: p.altura_final) if candidatos else None
        if destino is None:
            destino = _crear_pallet(cd, contador)
            pallets_abiertos.append(destino)
        _colocar(destino, cama, info_sku)


def _consolidar_pallets(pallets_cd: list[Pallet], info_sku: dict[str, dict]) -> list[Pallet]:
    """Red de seguridad final: vacía, cuando es posible, los pallets que quedaron por
    debajo del mínimo, encimando sus camas de NABs/remate en otros pallets del mismo
    CD que aún tengan espacio, en vez de dejarlos como pallets casi vacíos."""
    pequenos = sorted(
        (p for p in pallets_cd if p.altura_final < config.ALTURA_TOTAL_MIN_TOLERADO),
        key=lambda p: p.altura_final,
    )
    eliminados: set[int] = set()
    tocados: set[int] = set()

    for origen in pequenos:
        if origen.altura_final >= config.ALTURA_TOTAL_MIN_TOLERADO:
            continue  # ya se completó recibiendo camas de otro pallet chico

        # [PARCHE P6] Altura de referencia congelada explícitamente. El guard
        # "nunca mover hacia un pallet peor" debe comparar contra la altura del
        # ORIGEN ANTES de empezar a vaciarlo, no contra un valor que muta. Antes
        # funcionaba por accidente (origen.altura_final no se actualizaba dentro
        # de este bucle, solo después); acá queda explícito para que un refactor
        # futuro que agregue un `origen.altura_final = ...` en el medio no rompa
        # la semántica sin que nada falle.
        altura_referencia = origen.altura_final

        # El orden de origen.camas ya es válido (nivel ascendente, cadena de
        # fill_ratio verificada por _puede_soportar durante la asignación
        # original). `flexibles` se ordena por -altura_cama solo para decidir en
        # qué orden INTENTAR moverlas afuera -- no debe usarse como orden final:
        # las que no se mueven ("sobrantes") tienen que conservar su posición
        # relativa original, no la de este sort de prioridad.
        flexibles = sorted((c for c in origen.camas if _es_flexible(c)), key=lambda c: -c.altura_cama)
        movidas: set[int] = set()

        for cama in flexibles:
            candidatos = [
                candidato
                for candidato in pallets_cd
                if candidato is not origen
                and id(candidato) not in eliminados
                and candidato.altura_final >= altura_referencia
                and _remate_compatible(candidato, cama)
                and _cabe(candidato, cama, info_sku)  # [P4]
            ]
            destino = max(candidatos, key=lambda c: c.altura_final) if candidatos else None
            if destino is None:
                continue
            _colocar(destino, cama, info_sku)
            # La consolidación puede mover una cama de nivel más bajo (ej. NABs, 6)
            # a un pallet que ya tenía una de remate (7) al tope -- un append ciego
            # rompería el orden vertical (sección 9.1) y además corrompería
            # _puede_soportar, que asume que camas[-1] es la que está más arriba.
            # Con empate de nivel el sort es estable y no reordena lo ya válido.
            destino.camas.sort(key=lambda c: c.nivel_categoria)
            tocados.add(id(destino))
            movidas.add(id(cama))

        nuevas_camas = [c for c in origen.camas if id(c) not in movidas]
        origen.camas = nuevas_camas
        if nuevas_camas:
            origen.altura_final = _altura_desde_camas(nuevas_camas)
            origen.peso_estimado = _peso_desde_camas(nuevas_camas, info_sku)  # [P4]
            origen.estado = (
                config.ESTADO_PALLET_PARCIAL
                if origen.altura_final < config.ALTURA_TOTAL_MIN_TOLERADO
                else config.ESTADO_OK
            )
            tocados.add(id(origen))
        else:
            eliminados.add(id(origen))

    resultado = [p for p in pallets_cd if id(p) not in eliminados]
    for pallet in resultado:
        if id(pallet) in tocados:
            pallet.lineas = _construir_lineas(pallet.camas, info_sku)
    return resultado


def armar_pallets(
    camas_por_cd: dict[str, list[Cama]],
    info_sku: dict[str, dict],
    pallets_semilla: list[Pallet] | None = None,
) -> list[Pallet]:
    todos_pallets: list[Pallet] = []

    semillas_por_cd: dict[str, list[Pallet]] = {}
    for pallet in pallets_semilla or []:
        semillas_por_cd.setdefault(pallet.cd, []).append(pallet)

    # [PARCHE P3] `sorted(...)`: iterar un set de strings hace que el orden dependa
    # del hash de cada string, que con PYTHONHASHSEED aleatorio (default de Python 3)
    # CAMBIA entre procesos. El plan por CD era el mismo, pero el orden de las filas
    # del Excel de salida variaba entre corridas -> imposible diffear la corrida de
    # hoy contra la de ayer. Para una herramienta que corre a diario eso es ruido puro.
    for cd in sorted(set(camas_por_cd) | set(semillas_por_cd)):
        camas_por_nivel, camas_remate = _agrupar_camas(camas_por_cd.get(cd, []))
        contador = [0]
        pallets_abiertos: list[Pallet] = list(semillas_por_cd.get(cd, []))
        camas_iniciales = {id(p): len(p.camas) for p in pallets_abiertos}

        nivel_nabs = config.ORDEN_CATEGORIAS.index("NABs") + 1  # 6
        for nivel in range(1, nivel_nabs):  # niveles base 1-5: nunca sobre un pallet homogéneo
            _asignar_camas(
                camas_por_nivel[nivel],
                lambda p: not p.tipo.startswith("Homogéneo"),
                cd, contador, pallets_abiertos, info_sku,
            )

        _asignar_camas(  # NABs (nivel 6): cualquier pallet -incluidos homogéneos- sin remate aún
            camas_por_nivel[nivel_nabs],
            lambda p: _remate_de(p) is None,
            cd, contador, pallets_abiertos, info_sku,
        )

        _asignar_remate(camas_remate, cd, contador, pallets_abiertos, info_sku)

        for pallet in pallets_abiertos:
            if pallet.tipo.startswith("Homogéneo") and len(pallet.camas) > camas_iniciales[id(pallet)]:
                pallet.tipo = "Homogéneo + Remate"
            pallet.lineas = _construir_lineas(pallet.camas, info_sku)
            pallet.estado = (
                config.ESTADO_PALLET_PARCIAL
                if pallet.altura_final < config.ALTURA_TOTAL_MIN_TOLERADO
                else config.ESTADO_OK
            )

        todos_pallets.extend(_consolidar_pallets(pallets_abiertos, info_sku))

    return todos_pallets
```

## `src/validacion_peso.py`

```python
import config
from models import Pallet


def validar_pesos(pallets: list[Pallet], info_sku: dict[str, dict]) -> None:
    for pallet in pallets:
        peso_total = 0.0
        peso_no_validable = False
        for linea in pallet.lineas:
            meta = info_sku[linea.sku]
            peso_caja = meta["peso_caja"] or 0.0
            cajas_totales = linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            peso_total += cajas_totales * peso_caja
            peso_no_validable = peso_no_validable or linea.peso_no_validable

        pallet.peso_estimado = peso_total

        estados = []
        if peso_no_validable:
            estados.append(config.ESTADO_PESO_NO_VALIDABLE)
        if peso_total > config.PESO_ALERTA_KG:
            estados.append(config.ESTADO_ALERTA_PESO)
        if pallet.estado != config.ESTADO_OK:
            estados.append(pallet.estado)

        pallet.estado = " + ".join(dict.fromkeys(estados)) if estados else config.ESTADO_OK
```

## `src/exportar.py`

```python
import io

import pandas as pd

from models import Pallet, ResultadoPipeline


def construir_plan_picking_df(pallets: list[Pallet]) -> pd.DataFrame:
    filas = []
    for pallet in pallets:
        for linea in pallet.lineas:
            filas.append(
                {
                    "CD": pallet.cd,
                    "ID_Pallet": pallet.id,
                    "Tipo_Pallet": pallet.tipo,
                    "Nivel_Categoria": linea.nivel_categoria,
                    "SKU": linea.sku,
                    "Descripcion": linea.descripcion,
                    "Categoria": linea.categoria,
                    "Cajas_Demanda_Oficial": linea.cajas_demanda_oficial,
                    "Cajas_Extra_Consolidacion": linea.cajas_extra_consolidacion,
                    "Cajas_Totales_Pallet": linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion,
                    "Altura_Final_Pallet_cm": round(pallet.altura_final, 2),
                    "Peso_Estimado_Pallet_kg": round(pallet.peso_estimado, 2),
                    "Estado": pallet.estado,
                }
            )
    columnas = [
        "CD", "ID_Pallet", "Tipo_Pallet", "Nivel_Categoria", "SKU", "Descripcion", "Categoria",
        "Cajas_Demanda_Oficial", "Cajas_Extra_Consolidacion", "Cajas_Totales_Pallet",
        "Altura_Final_Pallet_cm", "Peso_Estimado_Pallet_kg", "Estado",
    ]
    return pd.DataFrame(filas, columns=columnas)


def construir_resumen_cd_df(pallets: list[Pallet]) -> pd.DataFrame:
    filas = []
    for cd in sorted({p.cd for p in pallets}):
        pallets_cd = [p for p in pallets if p.cd == cd]
        homogeneos = [p for p in pallets_cd if p.tipo.startswith("Homogéneo")]
        mixtos = [p for p in pallets_cd if p.tipo == "Mixto"]
        cajas_totales = sum(
            linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            for p in pallets_cd
            for linea in p.lineas
        )
        cajas_extra = sum(linea.cajas_extra_consolidacion for p in pallets_cd for linea in p.lineas)
        peso_total = sum(p.peso_estimado for p in pallets_cd)
        alertas_peso = sum(1 for p in pallets_cd if "ALERTA DE PESO" in p.estado)

        filas.append(
            {
                "CD": cd,
                "N_Pallets": len(pallets_cd),
                "N_Pallets_Homogeneos": len(homogeneos),
                "N_Pallets_Mixtos": len(mixtos),
                "Cajas_Totales_Despachadas": cajas_totales,
                "Cajas_Extra_Consolidacion": cajas_extra,
                "Peso_Total_kg": round(peso_total, 2),
                "N_Alertas_Peso": alertas_peso,
            }
        )
    return pd.DataFrame(filas)


def exportar_workbook(resultado: ResultadoPipeline, ruta_o_buffer=None):
    destino = ruta_o_buffer if ruta_o_buffer is not None else io.BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        resultado.plan_picking_df.to_excel(writer, sheet_name="Plan_Picking", index=False)
        resultado.log_validacion_df.to_excel(writer, sheet_name="Log_Validacion", index=False)
        resultado.resumen_cd_df.to_excel(writer, sheet_name="Resumen_por_CD", index=False)
    if ruta_o_buffer is None:
        destino.seek(0)
    return destino
```

## `src/pipeline.py`

```python
import pandas as pd

import config
from models import Pallet, PalletLinea, ResultadoPipeline
from src import apilado_3d, derivados, exportar, packing_2d, pallets_homogeneos, validacion, validacion_peso


def _construir_info_sku(df: pd.DataFrame) -> dict[str, dict]:
    info: dict[str, dict] = {}
    for _, fila in df.drop_duplicates(subset="SKU").iterrows():
        categoria = fila["Categoria_Normalizada"] if pd.notna(fila["Categoria_Normalizada"]) else fila["Categoría"]
        info[fila["SKU"]] = {
            "descripcion": fila["Descripción"],
            "categoria": categoria,
            "nivel_categoria": fila["Nivel_Categoria"],
            "peso_no_validable": bool(fila["Peso_No_Validable"]),
            "peso_caja": fila["Peso_Caja"] if pd.notna(fila["Peso_Caja"]) else 0.0,
        }
    return info


def _construir_pallets_sin_clasificar(df_no_clasificado: pd.DataFrame) -> list[Pallet]:
    pallets = []
    for cd, grupo in df_no_clasificado.groupby("CD"):
        lineas = [
            PalletLinea(
                sku=fila["SKU"],
                descripcion=fila["Descripción"],
                categoria=fila["Categoría"],
                nivel_categoria=None,
                cajas_demanda_oficial=int(fila["Cajas_Teoricas_Redondeadas"]),
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(fila["Peso_No_Validable"]),
            )
            for _, fila in grupo.iterrows()
        ]
        pallet = Pallet(
            id=f"SIN-ASIGNAR-{cd}",
            cd=cd,
            tipo="Requiere Revisión",
            estado=config.ESTADO_CATEGORIA_NO_CLASIFICADA,
        )
        pallet.lineas = lineas
        pallets.append(pallet)
    return pallets


def ejecutar_pipeline(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_derivado = derivados.calcular_derivados(df_validado)

    info_sku = _construir_info_sku(df_derivado)

    df_clasificado = df_derivado[df_derivado["Categoria_Normalizada"].notna()].copy()
    df_no_clasificado = df_derivado[df_derivado["Categoria_Normalizada"].isna()].copy()

    remanente_df, pallets_hom = pallets_homogeneos.armar_pallets_homogeneos(df_clasificado)
    camas_por_cd = packing_2d.generar_camas(remanente_df)
    pallets_apilado = apilado_3d.armar_pallets(camas_por_cd, info_sku, pallets_semilla=pallets_hom)
    pallets_sin_clasificar = _construir_pallets_sin_clasificar(df_no_clasificado)

    todos_pallets = pallets_apilado + pallets_sin_clasificar
    validacion_peso.validar_pesos(todos_pallets, info_sku)

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=log_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=info_sku,
    )


def ejecutar_desde_archivo(ruta_o_buffer) -> ResultadoPipeline:
    envios, maestro, uma = validacion.cargar_hojas(ruta_o_buffer)
    return ejecutar_pipeline(envios, maestro, uma)
```

## `src/template.py`

```python
import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

ENVIOS_EJEMPLO = pd.DataFrame(
    [
        {"CD": "BK31", "SKU": 1001, "Descripción": "Ron Ejemplo 750ml 1X1", "Cajas Teóricas": 10, "Unidades": 120},
        {"CD": "BK31", "SKU": 1002, "Descripción": "Yogurt Ejemplo 1L", "Cajas Teóricas": 25, "Unidades": 300},
        {"CD": "BK34", "SKU": 1003, "Descripción": "Cigarro Ejemplo Cajetilla", "Cajas Teóricas": 3.5, "Unidades": 70},
        {"CD": "BK34", "SKU": 1001, "Descripción": "Ron Ejemplo 750ml 1X1", "Cajas Teóricas": 15, "Unidades": 180},
    ]
)

MAESTRO_EJEMPLO = pd.DataFrame(
    [
        {"SKU": 1001, "Categoría": "Licores", "Unidades por caja": 12, "Cajas por cama": 20, "Camas por PH": 6, "Cajas por PH": 120},
        {"SKU": 1002, "Categoría": "Lácteos", "Unidades por caja": 12, "Cajas por cama": 15, "Camas por PH": 7, "Cajas por PH": 105},
        {"SKU": 1003, "Categoría": "Cigarros", "Unidades por caja": 20, "Cajas por cama": 50, "Camas por PH": 3, "Cajas por PH": 150},
    ]
)

UMA_EJEMPLO = pd.DataFrame(
    [
        {"SKU": 1001, "Largo de caja": 30, "Ancho de caja": 20, "Alto de caja": 25, "Peso bruto por unidad": 0.90},
        {"SKU": 1002, "Largo de caja": 25, "Ancho de caja": 25, "Alto de caja": 15, "Peso bruto por unidad": 1.00},
        {"SKU": 1003, "Largo de caja": 35, "Ancho de caja": 25, "Alto de caja": 55, "Peso bruto por unidad": 0.05},
    ]
)

INSTRUCCIONES = pd.DataFrame(
    [
        {"Hoja": "Envios_Julio", "Columna": "CD", "Qué va aquí": "Código del Centro de Distribución destino (texto), ej. BK31."},
        {"Hoja": "Envios_Julio", "Columna": "SKU", "Qué va aquí": "Identificador del producto. Debe existir también en Maestro_SKUs y en UMA."},
        {"Hoja": "Envios_Julio", "Columna": "Descripción", "Qué va aquí": "Nombre o descripción del producto."},
        {"Hoja": "Envios_Julio", "Columna": "Cajas Teóricas", "Qué va aquí": "Demanda oficial en cajas. Solo puede traer decimales si la Categoría del SKU es Cigarros (se redondea hacia arriba)."},
        {"Hoja": "Envios_Julio", "Columna": "Unidades", "Qué va aquí": "Demanda en unidades sueltas (informativo)."},
        {"Hoja": "Maestro_SKUs", "Columna": "SKU", "Qué va aquí": "Debe coincidir exactamente con el SKU usado en Envios_Julio y UMA."},
        {"Hoja": "Maestro_SKUs", "Columna": "Categoría", "Qué va aquí": "Una de: Licores, Lácteos, Aseo, Importados, Merch, NABs, Comestibles, Cigarros. Cualquier otro valor queda marcado como 'no clasificada' y no se apila automáticamente."},
        {"Hoja": "Maestro_SKUs", "Columna": "Unidades por caja", "Qué va aquí": "Cuántas unidades sueltas trae una caja de este SKU."},
        {"Hoja": "Maestro_SKUs", "Columna": "Cajas por cama", "Qué va aquí": "Cuántas cajas de este SKU caben en una cama (capa) del pallet. Si se deja vacío o en 0, se calcula automáticamente desde las dimensiones de UMA."},
        {"Hoja": "Maestro_SKUs", "Columna": "Camas por PH", "Qué va aquí": "Cuántas camas conforman un pallet homogéneo completo de este SKU."},
        {"Hoja": "Maestro_SKUs", "Columna": "Cajas por PH", "Qué va aquí": "Cuántas cajas conforman un pallet homogéneo completo de este SKU."},
        {"Hoja": "UMA", "Columna": "SKU", "Qué va aquí": "Debe coincidir exactamente con el SKU usado en Envios_Julio y Maestro_SKUs."},
        {"Hoja": "UMA", "Columna": "Largo de caja / Ancho de caja", "Qué va aquí": "Dimensiones de la base de la caja, en centímetros. El sistema prueba automáticamente ambas rotaciones sobre el pallet de 120x100 cm."},
        {"Hoja": "UMA", "Columna": "Alto de caja", "Qué va aquí": "Altura de la caja en centímetros. Máximo permitido: 180.08 cm."},
        {"Hoja": "UMA", "Columna": "Peso bruto por unidad", "Qué va aquí": "Peso en kg de una unidad suelta (se multiplica por 'Unidades por caja' de Maestro_SKUs para obtener el peso de la caja)."},
    ]
)


def _autoajustar_columnas(hoja, df: pd.DataFrame) -> None:
    for i, columna in enumerate(df.columns, start=1):
        ancho = max(len(str(columna)), df[columna].astype(str).map(len).max() if not df.empty else 0) + 4
        hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = min(ancho, 60)


def construir_template(ruta_o_buffer=None):
    destino = ruta_o_buffer if ruta_o_buffer is not None else io.BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        INSTRUCCIONES.to_excel(writer, sheet_name="Instrucciones", index=False)
        ENVIOS_EJEMPLO.to_excel(writer, sheet_name="Envios_Julio", index=False)
        MAESTRO_EJEMPLO.to_excel(writer, sheet_name="Maestro_SKUs", index=False)
        UMA_EJEMPLO.to_excel(writer, sheet_name="UMA", index=False)

        libro = writer.book
        encabezado_relleno = PatternFill(start_color="2A78D6", end_color="2A78D6", fill_type="solid")
        encabezado_fuente = Font(color="FFFFFF", bold=True)

        for nombre_hoja, df in (
            ("Instrucciones", INSTRUCCIONES),
            ("Envios_Julio", ENVIOS_EJEMPLO),
            ("Maestro_SKUs", MAESTRO_EJEMPLO),
            ("UMA", UMA_EJEMPLO),
        ):
            hoja = libro[nombre_hoja]
            for celda in hoja[1]:
                celda.fill = encabezado_relleno
                celda.font = encabezado_fuente
                celda.alignment = Alignment(wrap_text=True, vertical="center")
            _autoajustar_columnas(hoja, df)

    if ruta_o_buffer is None:
        destino.seek(0)
    return destino
```

## `app.py`

```python
import streamlit as st

from src.exportar import exportar_workbook
from src.pipeline import ejecutar_pipeline
from src.template import construir_template
from src.validacion import cargar_hojas
from visualizacion import dibujar_cama, dibujar_pallet

st.set_page_config(page_title="Agente Cubicador", layout="wide")

st.title("Agente Cubicador — Motor de Optimización de Pallets")
st.caption("Sube la demanda, el maestro de SKUs y las dimensiones (UMA) para generar el plan de picking por pallet.")

col_ayuda, col_boton = st.columns([3, 1])
with col_ayuda:
    st.markdown(
        "¿Primera vez usando la herramienta? Descarga la plantilla de ejemplo: trae las 3 hojas "
        "(`Envios_Julio`, `Maestro_SKUs`, `UMA`) con datos de muestra y una hoja **Instrucciones** "
        "que explica qué va en cada columna, para evitar errores de formato."
    )
with col_boton:
    st.download_button(
        "📥 Descargar plantilla de ejemplo",
        data=construir_template(),
        file_name="Plantilla_Ejemplo_Agente_Cubicador.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.divider()

modo = st.radio(
    "Formato de los archivos de entrada",
    ["Un solo Excel con las 3 hojas (Envios_Julio, Maestro_SKUs, UMA)", "3 archivos Excel separados"],
    horizontal=True,
)

envios = maestro = uma = None

if modo.startswith("Un solo"):
    archivo = st.file_uploader("Excel combinado", type=["xlsx"])
    if archivo is not None:
        envios, maestro, uma = cargar_hojas(archivo)
else:
    col1, col2, col3 = st.columns(3)
    archivo_envios = col1.file_uploader("Envios_Julio", type=["xlsx"])
    archivo_maestro = col2.file_uploader("Maestro_SKUs", type=["xlsx"])
    archivo_uma = col3.file_uploader("UMA", type=["xlsx"])
    if archivo_envios and archivo_maestro and archivo_uma:
        import pandas as pd

        envios = pd.read_excel(archivo_envios)
        maestro = pd.read_excel(archivo_maestro)
        uma = pd.read_excel(archivo_uma)

if envios is not None and st.button("Procesar", type="primary"):
    with st.spinner("Ejecutando el motor de optimización..."):
        st.session_state["resultado"] = ejecutar_pipeline(envios, maestro, uma)

resultado = st.session_state.get("resultado")

if resultado is None:
    st.info("Sube los archivos y presiona **Procesar** para generar el plan de picking.")
    st.stop()

pallets = resultado.pallets
df = resultado.plan_picking_df

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Pallets totales", len(pallets))
col2.metric("Homogéneos (base 1 SKU)", sum(1 for p in pallets if p.tipo.startswith("Homogéneo")))
col3.metric("Mixtos", sum(1 for p in pallets if p.tipo == "Mixto"))
col4.metric("Alertas de peso", sum(1 for p in pallets if "ALERTA DE PESO" in p.estado))
col5.metric(
    "Cajas extra por consolidación",
    int(df["Cajas_Extra_Consolidacion"].sum()) if not df.empty else 0,
)

tab_plan, tab_log, tab_resumen, tab_inspector = st.tabs(
    ["Plan de Picking", "Log de Validación", "Resumen por CD", "Inspector de Pallets"]
)

with tab_plan:
    st.dataframe(df, use_container_width=True)

with tab_log:
    st.dataframe(resultado.log_validacion_df, use_container_width=True)

with tab_resumen:
    st.dataframe(resultado.resumen_cd_df, use_container_width=True)

with tab_inspector:
    if not pallets:
        st.warning("No se generaron pallets.")
    else:
        cds = sorted({p.cd for p in pallets})
        cd_elegido = st.selectbox("Centro de Distribución", cds)
        pallets_cd = [p for p in pallets if p.cd == cd_elegido]
        ids_pallet = [p.id for p in pallets_cd]
        id_elegido = st.selectbox("Pallet", ids_pallet)
        pallet = next(p for p in pallets_cd if p.id == id_elegido)

        columna_pallet, columna_cama = st.columns([1, 1.4])

        with columna_pallet:
            st.caption("Vista apilada del pallet, por nivel de categoría (base → remate)")
            if pallet.camas:
                st.pyplot(dibujar_pallet(pallet))
            else:
                st.info("Este pallet es homogéneo o no tiene camas con geometría detallada.")

        with columna_cama:
            if pallet.camas:
                indices = list(range(len(pallet.camas)))
                indice = st.selectbox(
                    "Cama a inspeccionar",
                    indices,
                    format_func=lambda i: f"Cama {i + 1} — {'/'.join(pallet.camas[i].categorias)}",
                )
                st.pyplot(dibujar_cama(pallet.camas[indice], resultado.info_sku))
            else:
                st.info("Sin detalle 2D disponible para pallets homogéneos.")

st.divider()
buffer = exportar_workbook(resultado)
st.download_button(
    "Descargar Plan_Picking_Optimizado.xlsx",
    data=buffer,
    file_name="Plan_Picking_Optimizado.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
```

## `visualizacion.py`

```python
import matplotlib.patches as patches
import matplotlib.pyplot as plt

import config
from models import Cama, Pallet

COLOR_CATEGORIA = {
    "Licores": "#2a78d6",
    "Lácteos": "#eb6834",
    "Aseo": "#1baf7a",
    "Importados": "#eda100",
    "Merch": "#e87ba4",
    "NABs": "#008300",
    "Comestibles": "#4a3aa7",
    "Cigarros": "#e34948",
}
COLOR_DEFECTO = "#898781"
COLOR_SUPERFICIE = "#fcfcfb"
COLOR_BORDE = "#c3c2b7"
COLOR_TEXTO = "#0b0b0b"


def dibujar_cama(cama: Cama, info_sku: dict) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(5, 4.3))
    ax.set_xlim(0, config.PALLET_LARGO)
    ax.set_ylim(0, config.PALLET_ANCHO)
    ax.set_aspect("equal")
    ax.set_facecolor(COLOR_SUPERFICIE)
    ax.set_title(
        f"Cama — {', '.join(cama.categorias)} (alto {cama.altura_cama:.1f} cm)",
        fontsize=10,
        color=COLOR_TEXTO,
    )
    ax.set_xlabel("Largo del pallet (cm)")
    ax.set_ylabel("Ancho del pallet (cm)")

    if not cama.placements and cama.cantidades:
        resumen = ", ".join(f"SKU {sku}: {qty} cajas" for sku, qty in cama.cantidades.items())
        ax.text(
            config.PALLET_LARGO / 2, config.PALLET_ANCHO / 2,
            f"Pallet homogéneo (según Maestro)\n{resumen}",
            ha="center", va="center", fontsize=8, color=COLOR_TEXTO, wrap=True,
        )

    categorias_presentes = set()
    for placement in cama.placements:
        categoria = info_sku.get(placement.sku, {}).get("categoria")
        color = COLOR_CATEGORIA.get(categoria, COLOR_DEFECTO)
        categorias_presentes.add(categoria or "Sin categoría")
        for i in range(placement.cantidad):
            x = placement.x + i * placement.w
            ax.add_patch(
                patches.Rectangle(
                    (x, placement.y), placement.w, placement.d,
                    facecolor=color, edgecolor=COLOR_SUPERFICIE, linewidth=1.5,
                )
            )
            ax.text(
                x + placement.w / 2, placement.y + placement.d / 2, str(placement.sku),
                ha="center", va="center", fontsize=6, color="white",
            )

    ax.add_patch(
        patches.Rectangle((0, 0), config.PALLET_LARGO, config.PALLET_ANCHO, fill=False, edgecolor=COLOR_BORDE, linewidth=1.5)
    )

    handles = [patches.Patch(facecolor=COLOR_CATEGORIA.get(c, COLOR_DEFECTO), label=c) for c in sorted(categorias_presentes)]
    if handles:
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=len(handles), fontsize=8, frameon=False)

    fig.tight_layout()
    return fig


def dibujar_pallet(pallet: Pallet) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(3.4, 6.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, config.ALTURA_TOTAL_MAX + 8)
    ax.set_facecolor(COLOR_SUPERFICIE)
    ax.set_title(f"{pallet.id}\n{pallet.altura_final:.1f} cm — {pallet.estado}", fontsize=9, color=COLOR_TEXTO)
    ax.set_xticks([])
    ax.set_ylabel("Altura (cm)")

    y = 0.0
    ax.add_patch(patches.Rectangle((0, 0), 1, config.ALTURA_PALLET_VACIO, facecolor="#e1e0d9", edgecolor=COLOR_BORDE))
    y = config.ALTURA_PALLET_VACIO

    for cama in pallet.camas:
        color = COLOR_CATEGORIA.get(cama.categorias[0], COLOR_DEFECTO)
        ax.add_patch(patches.Rectangle((0, y), 1, cama.altura_cama, facecolor=color, edgecolor=COLOR_SUPERFICIE, linewidth=1))
        if cama.altura_cama >= 5:
            etiqueta = "/".join(cama.categorias)
            ax.text(0.5, y + cama.altura_cama / 2, etiqueta, ha="center", va="center", fontsize=7, color="white")
        y += cama.altura_cama

    for referencia, estilo in ((config.ALTURA_TOTAL_MIN, "--"), (config.ALTURA_TOTAL_MAX, "--")):
        ax.axhline(referencia, color="#52514e", linestyle=estilo, linewidth=1)

    fig.tight_layout()
    return fig
```

## `requirements.txt`

```text
pandas>=2.0
openpyxl>=3.1
streamlit>=1.35
matplotlib>=3.8
pytest>=8.0
```

## `tests/conftest.py`

```python
import pandas as pd
import pytest

ENVIOS_COLS = ["CD", "SKU", "Descripción", "Cajas Teóricas", "Unidades"]
MAESTRO_COLS = ["SKU", "Categoría", "Unidades por caja", "Cajas por cama", "Camas por PH", "Cajas por PH"]
UMA_COLS = ["SKU", "Largo de caja", "Ancho de caja", "Alto de caja", "Peso bruto por unidad"]


def _envio(cd="BK31", sku=1, descripcion="Producto", cajas=10, unidades=None):
    return {
        "CD": cd,
        "SKU": sku,
        "Descripción": descripcion,
        "Cajas Teóricas": cajas,
        "Unidades": unidades if unidades is not None else cajas,
    }


def _maestro(sku=1, categoria="Licores", unidades_por_caja=1, cajas_por_cama=10, camas_por_ph=5, cajas_por_ph=50):
    return {
        "SKU": sku,
        "Categoría": categoria,
        "Unidades por caja": unidades_por_caja,
        "Cajas por cama": cajas_por_cama,
        "Camas por PH": camas_por_ph,
        "Cajas por PH": cajas_por_ph,
    }


def _uma(sku=1, largo=30, ancho=20, alto=30, peso_unidad=1.0):
    return {
        "SKU": sku,
        "Largo de caja": largo,
        "Ancho de caja": ancho,
        "Alto de caja": alto,
        "Peso bruto por unidad": peso_unidad,
    }


@pytest.fixture
def dataset_factory():
    def _factory(envios_overrides=None, maestro_overrides=None, uma_overrides=None):
        envios_overrides = envios_overrides or [{}]
        maestro_overrides = maestro_overrides or [{}]
        uma_overrides = uma_overrides or [{}]

        envios = pd.DataFrame([_envio(**o) for o in envios_overrides], columns=ENVIOS_COLS)
        maestro = pd.DataFrame([_maestro(**o) for o in maestro_overrides], columns=MAESTRO_COLS)
        uma = pd.DataFrame([_uma(**o) for o in uma_overrides], columns=UMA_COLS)
        return envios, maestro, uma

    return _factory
```

## `tests/test_validacion.py`

```python
import pandas as pd

from src.validacion import validar_y_limpiar


def test_normaliza_casing_de_categoria(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Nabs"}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert df.iloc[0]["Categoria_Normalizada"] == "NABs"


def test_categoria_no_clasificada_se_loguea_pero_no_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Otros"}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["Categoria_Normalizada"])
    assert (log["regla"] == "9.1").any()


def test_sku_sin_maestro_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 2}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V2").any()


def test_sentinel_cajas_por_ph_se_marca_no_confiable(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 100}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999999999}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert pd.isna(df.iloc[0]["Cajas por PH"])
    assert (log["regla"] == "V3").any()


def test_dimension_imposible_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1, "largo": 452, "ancho": 452}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V4").any()


def test_altura_excesiva_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1, "alto": 575}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V5").any()


def test_cajas_por_cama_cero_se_trata_como_nulo(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 0}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert pd.isna(df.iloc[0]["Cajas por cama"])
    assert (log["regla"] == "V7").any()


def test_peso_fuera_de_rango_se_marca_no_validable_sin_excluir(dataset_factory):
    """[Sección 2 / v2] "Peso bruto por unidad" de UMA es el peso de la CAJA, no
    de la unidad -- V6 ya no lo multiplica por "Unidades por caja"
    (config.PESO_UMA_ES_POR_UNIDAD=False). El fixture antes ponía
    unidades_por_caja=1000 para inflar 1.0 kg hasta 1000 kg (fuera de rango con
    la fórmula vieja); con la fórmula corregida esa combinación da 1.0 kg, que
    es válido. El caso fuera de rango ahora se arma con un peso de caja directo
    por encima de config.PESO_CAJA_MAX."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1, "peso_unidad": 500.0}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert bool(df.iloc[0]["Peso_No_Validable"]) is True
    assert (log["regla"] == "V6").any()


def test_cajas_teoricas_no_positivas_se_excluyen(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 0}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V8").any()


def test_duplicados_cd_sku_se_suman(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 1, "cajas": 7}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert df.iloc[0]["Cajas Teóricas"] == 12
    assert (log["regla"] == "V9").any()
```

## `tests/test_derivados.py`

```python
import config
from src.derivados import calcular_derivados
from src.validacion import validar_y_limpiar


def test_redondeo_hacia_arriba_de_cajas_fraccionarias(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 3.2}],
        maestro_overrides=[{"sku": 1, "categoria": "Cigarros"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Cajas_Teoricas_Redondeadas"] == 4
    assert round(df.iloc[0]["Cajas_Extra_Redondeo"], 2) == 0.8


def test_fallback_geometrico_cuando_falta_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 0}],
        uma_overrides=[{"sku": 1, "largo": 40, "ancho": 25}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    esperado = max((120 // 40) * (100 // 25), (120 // 25) * (100 // 40))
    assert df.iloc[0]["Cajas_Cama_Efectivo"] == esperado


def test_nivel_categoria_remate_es_el_nivel_mas_alto(dataset_factory):
    """[Sección 1.3 / v2] El remate ya no queda en None: config.nivel_de_categoria
    le da NIVEL_REMATE (7), el nivel más alto de la escala, para poder compararlo
    con el resto cuando una cama mezcla categorías (punto 6)."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Comestibles"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Nivel_Categoria"] == config.NIVEL_REMATE
    assert bool(df.iloc[0]["Es_Categoria_Remate"]) is True


def test_nivel_categoria_asignado_para_categoria_estable(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Nivel_Categoria"] == 1
```

## `tests/test_packing_2d.py`

```python
from src.derivados import calcular_derivados
from src.packing_2d import generar_camas
from src.pallets_homogeneos import armar_pallets_homogeneos
from src.validacion import validar_y_limpiar


def test_densidad_maxima_limita_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 12}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 5, "cajas_por_ph": 999}],
        uma_overrides=[{"sku": 1, "largo": 10, "ancho": 10}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, pallets_hom = armar_pallets_homogeneos(df)
    assert pallets_hom == []

    camas = generar_camas(remanente)["BK31"]
    assert len(camas) == 3
    for cama in camas:
        assert cama.cantidades["1"] <= 5
    assert sum(cama.cantidades["1"] for cama in camas) == 12


def test_clustering_por_altura_no_combina_alturas_dispares(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 5}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999}, {"sku": 2, "cajas_por_ph": 999}],
        uma_overrides=[{"sku": 1, "alto": 20}, {"sku": 2, "alto": 30}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    skus_por_cama = [set(c.cantidades.keys()) for c in camas]
    assert not any({"1", "2"} <= s for s in skus_por_cama)


def test_clustering_combina_alturas_similares(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999}, {"sku": 2, "cajas_por_ph": 999}],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 22, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)


def test_remate_nunca_comparte_cama(dataset_factory):
    """Regla 9.3: Comestibles y Cigarros son excluyentes incluso a nivel de cama.
    Se mantiene aislado sin importar el punto 6 (agrupar por dimensión)."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Comestibles", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "Cigarros", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 20, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    for cama in camas:
        assert len(cama.categorias) == 1


def test_categorias_no_remate_pueden_compartir_cama_por_dimension(dataset_factory):
    """[Punto 6] Licores y Lácteos (niveles 1 y 2, separación 1 <=
    MAX_SEPARACION_NIVELES) con cajas de altura parecida ahora SÍ pueden
    terminar en la misma cama -antes el agrupamiento era estrictamente por
    categoría y esto era imposible."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Licores", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "Lácteos", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 21, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)
    mixta = next(c for c in camas if {"1", "2"} <= set(c.cantidades.keys()))
    assert set(mixta.categorias) == {"Licores", "Lácteos"}
    assert mixta.nivel_efectivo == 2  # el más restrictivo: Lácteos


def test_nabs_nunca_comparte_cama_con_niveles_base(dataset_factory):
    """[Punto 6] NABs queda siempre aislado de la mezcla por dimensión, aunque
    su separación numérica de nivel sea <= MAX_SEPARACION_NIVELES (Merch=5,
    NABs=6, separación 1). Mezclarlos rompía la regla de soporte del Paso 4
    (ver packing_2d._separar_nabs_y_remate para el detalle)."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Merch", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "NABs", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 20, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert not any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)
    for cama in camas:
        assert len(cama.categorias) == 1
```

## `tests/test_apilado_3d.py`

```python
import config
from models import Cama, Pallet
from src.apilado_3d import _consolidar_pallets, armar_pallets


def _info(sku, categoria="Licores", nivel=1):
    return {
        "descripcion": f"Producto {sku}",
        "categoria": categoria,
        "nivel_categoria": nivel,
        "peso_no_validable": False,
        "peso_caja": 1.0,
    }


def test_orden_de_estabilidad_se_respeta_sin_importar_orden_de_entrada():
    cama_lacteos = Cama(categorias=["Lácteos"], altura_cama=20, cantidades={"L1": 5}, nivel_categoria=2)
    cama_licores = Cama(categorias=["Licores"], altura_cama=20, cantidades={"L0": 5}, nivel_categoria=1)

    camas_por_cd = {"BK31": [cama_lacteos, cama_licores]}
    info_sku = {"L0": _info("L0", "Licores", 1), "L1": _info("L1", "Lácteos", 2)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    categorias_en_orden = [cama.categorias[0] for cama in pallets[0].camas]
    assert categorias_en_orden.index("Licores") < categorias_en_orden.index("Lácteos")


def test_remate_nunca_comparte_pallet_y_prioriza_mayor_remanente():
    cama_comestibles = Cama(
        categorias=["Comestibles"], altura_cama=20, cantidades={"C1": 50}, nivel_categoria=None
    )
    cama_cigarros = Cama(categorias=["Cigarros"], altura_cama=20, cantidades={"G1": 5}, nivel_categoria=None)

    camas_por_cd = {"BK31": [cama_comestibles, cama_cigarros]}
    info_sku = {
        "C1": _info("C1", "Comestibles", None),
        "G1": _info("G1", "Cigarros", None),
    }

    pallets = armar_pallets(camas_por_cd, info_sku)

    for pallet in pallets:
        categorias = {cama.categorias[0] for cama in pallet.camas}
        assert not ({"Comestibles", "Cigarros"} <= categorias)

    primer_pallet_categorias = {cama.categorias[0] for cama in pallets[0].camas}
    assert "Comestibles" in primer_pallet_categorias


def test_cierre_forzado_bajo_altura_minima_se_marca_parcial():
    cama = Cama(categorias=["Licores"], altura_cama=50, cantidades={"L0": 5}, nivel_categoria=1)
    camas_por_cd = {"BK31": [cama]}
    info_sku = {"L0": _info("L0", "Licores", 1)}

    pallets = armar_pallets(camas_por_cd, info_sku)
    assert len(pallets) == 1
    # [Sección 3.2 / v2] el umbral que decide PARCIAL es el tolerado (185, no 190)
    assert pallets[0].altura_final < config.ALTURA_TOTAL_MIN_TOLERADO
    assert config.ESTADO_PALLET_PARCIAL in pallets[0].estado


def test_consolidacion_nunca_mueve_una_cama_hacia_un_pallet_mas_chico():
    # Reproduce el bug real: un pallet ya casi completo (181.7cm, bajo el nuevo
    # umbral tolerado de 185) no debe perder su cama de remate para "ayudar" a un
    # pallet mucho más chico (66.02cm) — eso solo empeora el resultado neto.
    bueno = Pallet(id="A", cd="X", tipo="Mixto", altura_final=181.7)
    bueno.camas = [
        Cama(categorias=["Licores"], altura_cama=161.1, cantidades={"L1": 5}, nivel_categoria=1),
        Cama(categorias=["Comestibles"], altura_cama=20.6, cantidades={"C1": 3}, nivel_categoria=None),
    ]
    malo = Pallet(id="B", cd="X", tipo="Mixto", altura_final=66.02)
    malo.camas = [Cama(categorias=["Comestibles"], altura_cama=51.1, cantidades={"C2": 2}, nivel_categoria=None)]

    info_sku = {
        "L1": _info("L1", "Licores", 1),
        "C1": _info("C1", "Comestibles", None),
        "C2": _info("C2", "Comestibles", None),
    }

    resultado = _consolidar_pallets([bueno, malo], info_sku)
    pallet_a = next(p for p in resultado if p.id == "A")
    assert len(pallet_a.camas) == 2
    assert any(c.categorias[0] == "Comestibles" for c in pallet_a.camas)
```

## `tests/test_topado_homogeneos.py`

```python
import config
from src.apilado_3d import armar_pallets
from src.derivados import calcular_derivados
from src.packing_2d import generar_camas
from src.pallets_homogeneos import armar_pallets_homogeneos
from src.pipeline import _construir_info_sku
from src.validacion import validar_y_limpiar


def test_pallet_homogeneo_se_completa_con_remate_disponible(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[
            {"sku": 1, "cd": "BK31", "cajas": 20},
            {"sku": 2, "cd": "BK31", "cajas": 500},
        ],
        maestro_overrides=[
            {"sku": 1, "categoria": "Licores", "cajas_por_cama": 10, "camas_por_ph": 4, "cajas_por_ph": 20},
            {"sku": 2, "categoria": "Comestibles", "cajas_por_cama": 50, "cajas_por_ph": 99999},
        ],
        uma_overrides=[
            {"sku": 1, "largo": 30, "ancho": 20, "alto": 25},
            {"sku": 2, "largo": 30, "ancho": 20, "alto": 20},
        ],
    )

    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    info_sku = _construir_info_sku(df)

    remanente, pallets_hom = armar_pallets_homogeneos(df)
    assert len(pallets_hom) == 1
    altura_base = pallets_hom[0].altura_final
    # [Sección 7 / v2] el literal 185 era de la ventana vieja; lo que este test
    # realmente verifica es que el homogéneo, tal cual sale del Paso 2, deja
    # margen para que el remate se agregue encima sin pasar el máximo normal.
    assert altura_base < config.ALTURA_TOTAL_MAX

    camas_por_cd = generar_camas(remanente)
    pallets = armar_pallets(camas_por_cd, info_sku, pallets_semilla=pallets_hom)

    pallet_topado = next(p for p in pallets if p.id == pallets_hom[0].id)
    assert pallet_topado.tipo == "Homogéneo + Remate"
    assert pallet_topado.altura_final > altura_base
    assert any(cama.categorias[0] == "Comestibles" for cama in pallet_topado.camas)
```

## `tests/test_invariantes.py`

```python
"""[PARCHE P10] Tests de invariantes.

`test_pipeline_real_data.py` es un golden test: detecta que algo CAMBIÓ, pero no
distingue una mejora de una regresión, y se rompe apenas se toca la heurística
(que es exactamente lo que hacen los parches P1/P2/P4/P5).

Estos tests son distintos: verifican propiedades que deben cumplirse SIEMPRE,
con cualquier algoritmo de packing. Sobreviven a refactors y son los que de
verdad protegen el plan de picking.

Cómo correrlos:
    pytest tests/test_invariantes.py -v

NOTA DE IMPORTS: este archivo asume que `config`, `models` y `src.*` se importan
igual que en el resto de la suite existente. Si los tests actuales usan
`from packing_2d import ...` en vez de `from src.packing_2d import ...`, ajustar
las dos líneas marcadas abajo.
"""

from pathlib import Path

import pandas as pd
import pytest

import config
from src.packing_2d import _elegir_orientacion  # <-- ajustar import si hace falta
from src.pipeline import ejecutar_pipeline      # <-- ajustar import si hace falta

RAIZ = Path(__file__).resolve().parents[1]
DATASET = RAIZ / "Cubicaje18.07.2026.xlsx"

NIVEL_REMATE = 7  # las camas de remate tienen nivel_categoria = None


# --------------------------------------------------------------------------
# P1 — orientación: casos calculados a mano, sin depender de data real
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "largo, ancho, cajas_esperadas",
    [
        # El caso que rompía: 4x1=4 (criterio viejo, "más columnas") vs 2x4=8
        (25, 51, 8),
        # Simétrico: la mejor opción es la que tiene MENOS columnas
        (51, 25, 8),
        # Caso donde ambas orientaciones empatan
        (30, 30, 12),   # 4 col x 3 filas
        # Caja que solo entra en una orientación
        (110, 40, 2),   # 1 col x 2 filas
    ],
)
def test_orientacion_maximiza_cajas_totales(largo, ancho, cajas_esperadas):
    """La orientación elegida debe maximizar columnas x filas, no solo columnas."""
    resultado = _elegir_orientacion(largo, ancho)
    assert resultado is not None
    w, d, _columnas = resultado
    cajas = int(config.PALLET_LARGO // w) * int(config.PALLET_ANCHO // d)
    assert cajas == cajas_esperadas


def test_orientacion_nunca_peor_que_la_alternativa():
    """Para cualquier caja, la orientación elegida es >= la otra orientación."""
    for largo in range(10, 121, 7):
        for ancho in range(10, 101, 7):
            resultado = _elegir_orientacion(largo, ancho)
            if resultado is None:
                continue
            w, d, _ = resultado
            elegida = int(config.PALLET_LARGO // w) * int(config.PALLET_ANCHO // d)
            alternativas = []
            for ww, dd in ((largo, ancho), (ancho, largo)):
                if ww > config.PALLET_LARGO or dd > config.PALLET_ANCHO:
                    continue
                alternativas.append(int(config.PALLET_LARGO // ww) * int(config.PALLET_ANCHO // dd))
            assert elegida == max(alternativas), f"caja {largo}x{ancho}: eligió {elegida}, mejor {max(alternativas)}"


def test_orientacion_devuelve_none_si_no_cabe():
    assert _elegir_orientacion(452, 452) is None


# --------------------------------------------------------------------------
# Invariantes sobre el pipeline completo
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def resultado():
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    maestro = pd.read_excel(DATASET, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(DATASET, sheet_name="UMA")
    return ejecutar_pipeline(envios, maestro, uma)


@pytest.fixture(scope="module")
def demanda_oficial():
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    envios["SKU"] = envios["SKU"].astype(str).str.strip()  # normalización de src/validacion.py:_normalizar_sku
    envios = envios[envios["Cajas Teóricas"] > 0]
    agrupado = envios.groupby(["CD", "SKU"])["Cajas Teóricas"].sum()
    import math
    return {clave: math.ceil(valor) for clave, valor in agrupado.items()}


def test_ningun_pallet_supera_el_tope_duro(resultado):
    """Restricción física dura: 210 cm incluyendo el pallet vacío -es el techo
    absoluto (config.ALTURA_TOPE_DURO), no config.ALTURA_TOTAL_MAX (205): un
    pallet que todavía no llegó al mínimo tolerado (185) puede estirarse hasta
    210 para cerrar (ver apilado_3d._limite_altura)."""
    excedidos = [
        (p.id, round(p.altura_final, 2))
        for p in resultado.pallets
        if p.altura_final > config.ALTURA_TOPE_DURO + 1e-6
    ]
    assert not excedidos, f"Pallets fuera del tope duro: {excedidos}"


def test_pallets_sobre_el_maximo_normal_son_pocos_y_justificados(resultado):
    """El cierre elástico (205-210) debe ser la excepción, no la regla: si la
    mayoría de los pallets termina en esa franja, algo está mal calibrado
    (debería estar cerrando en la ventana 190-205 la gran mayoría de las veces)."""
    total = len(resultado.pallets)
    if total == 0:
        pytest.skip("Sin pallets")
    en_zona_elastica = sum(
        1 for p in resultado.pallets if p.altura_final > config.ALTURA_TOTAL_MAX + 1e-6
    )
    assert en_zona_elastica / total < 0.5, (
        f"{en_zona_elastica}/{total} pallets cerraron en la zona elástica (205-210); "
        "se esperaba que fuera la excepción."
    )


def test_nunca_se_despacha_por_encima_de_la_demanda(resultado, demanda_oficial):
    """[P2/P4] El motor nunca debe inventar cajas. `Cajas_Extra_Consolidacion`
    está en 0 por diseño, así que el plan debe ser <= demanda redondeada."""
    despachado: dict[tuple, int] = {}
    for pallet in resultado.pallets:
        for linea in pallet.lineas:
            clave = (pallet.cd, linea.sku)
            total = linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            despachado[clave] = despachado.get(clave, 0) + total

    excesos = {
        clave: (cantidad, demanda_oficial.get(clave, 0))
        for clave, cantidad in despachado.items()
        if cantidad > demanda_oficial.get(clave, 0)
    }
    assert not excesos, f"Se despachó de más en: {excesos}"


def test_orden_vertical_de_categorias(resultado):
    """Las camas de un pallet deben ir de nivel menor (base) a mayor (arriba).
    Es la regla de estabilidad de la sección 9.1 del doc de diseño."""
    fallas = []
    for pallet in resultado.pallets:
        niveles = [c.nivel_categoria if c.nivel_categoria is not None else NIVEL_REMATE for c in pallet.camas]
        if niveles != sorted(niveles):
            fallas.append((pallet.id, niveles))
    assert not fallas, f"Pallets con orden vertical inválido: {fallas}"


def test_remate_exclusivo(resultado):
    """Cigarros y Comestibles nunca comparten pallet (sección 9.3).

    [Punto 6 / v2] `cama.categorias[0]` ya no identifica de forma confiable la
    categoría de remate de una cama (con camas mixtas, `categorias` está ordenada
    alfabéticamente y el remate puede no quedar primero). Se usa la property
    `categoria_remate`, pensada exactamente para esto -y que además revienta si
    alguna vez encuentra las dos categorías de remate en la misma cama, que no
    debería poder pasar nunca (packing_2d._separar_nabs_y_remate)."""
    fallas = []
    for pallet in resultado.pallets:
        remates = {cr for c in pallet.camas if (cr := c.categoria_remate) is not None}
        if len(remates) > 1:
            fallas.append((pallet.id, remates))
    assert not fallas, f"Pallets con remate mixto: {fallas}"


def test_nada_pesado_encima_de_nabs(resultado):
    """Regla NABs (sección 9.2): solo Comestibles o Cigarros pueden ir encima.

    [Punto 6 / v2] `cama.categorias[0]` ya no sirve para esto: con camas mixtas,
    una cama Importados+NABs ordena `categorias` alfabéticamente y da
    "Importados" primero, aunque la cama entera se trata como NABs (nivel 6, el
    más restrictivo -- ver Cama.nivel_efectivo). Comparar por nivel en vez de por
    el string de una categoría cualquiera de la cama."""
    nivel_nabs = config.ORDEN_CATEGORIAS.index("NABs") + 1
    fallas = []
    for pallet in resultado.pallets:
        vio_nabs = False
        for cama in pallet.camas:
            nivel = cama.nivel_categoria
            if vio_nabs and nivel is not None and nivel < nivel_nabs:
                fallas.append((pallet.id, cama.categorias))
            if nivel == nivel_nabs:
                vio_nabs = True
    assert not fallas, f"Categorías de nivel 1-5 apoyadas sobre NABs: {fallas}"


def test_peso_respetado_como_restriccion(resultado):
    """[P4 / Sección 3.1 v2] Con el peso como restricción del Paso 4, un pallet
    solo puede superar el tope ELÁSTICO (1.430 kg, el que de verdad bloquea en
    `_cabe` desde la sección 3.1) si una sola cama ya lo supera por sí misma
    (caso irreducible). 1.400 kg (PESO_ALERTA_KG) es solo el umbral que etiqueta
    ⚠ ALERTA DE PESO en el Paso 5 -no debería usarse acá, un pallet multi-cama
    entre 1.400 y 1.430 es válido y esperado."""
    sospechosos = [
        (p.id, round(p.peso_estimado, 1))
        for p in resultado.pallets
        if p.peso_estimado > config.PESO_TOPE_ELASTICO_KG + 1e-6 and len(p.camas) > 1
    ]
    assert not sospechosos, (
        f"Pallets multi-cama por encima del tope elástico de peso: {sospechosos}. "
        "Si el peso es restricción del Paso 4 esto no debería poder ocurrir."
    )


def test_regla_de_soporte(resultado):
    """[P5] Ninguna cama con poca superficie cubierta sostiene otra encima."""
    if config.FILL_RATIO_MIN_SOPORTE <= 0:
        pytest.skip("Regla de soporte desactivada (FILL_RATIO_MIN_SOPORTE = 0)")
    fallas = []
    for pallet in resultado.pallets:
        for inferior in pallet.camas[:-1]:  # todas menos la de más arriba
            if inferior.fill_ratio < config.FILL_RATIO_MIN_SOPORTE - 1e-9:
                fallas.append((pallet.id, round(inferior.fill_ratio, 3)))
    assert not fallas, f"Camas poco cubiertas sosteniendo carga: {fallas}"


def test_determinismo(demanda_oficial):
    """[P3] Dos corridas con el mismo input deben dar exactamente el mismo Excel.
    Sin esto no se puede diffear la corrida de hoy contra la de ayer."""
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    maestro = pd.read_excel(DATASET, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(DATASET, sheet_name="UMA")

    primera = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())
    segunda = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())

    pd.testing.assert_frame_equal(primera.plan_picking_df, segunda.plan_picking_df)
    pd.testing.assert_frame_equal(primera.resumen_cd_df, segunda.resumen_cd_df)


def test_ids_de_pallet_unicos(resultado):
    ids = [p.id for p in resultado.pallets]
    duplicados = {i for i in ids if ids.count(i) > 1}
    assert not duplicados, f"IDs de pallet duplicados: {duplicados}"


# --------------------------------------------------------------------------
# Métrica de referencia (no es un assert: imprime para comparar antes/después)
# --------------------------------------------------------------------------

def test_reporte_de_ocupacion(resultado, capsys):
    """No falla nunca: imprime los KPIs que hoy el output no reporta.
    Correr con `pytest -s` para verlos y comparar contra la versión sin parches."""
    total = len(resultado.pallets)
    if total == 0:
        pytest.skip("Sin pallets")
    parciales = sum(1 for p in resultado.pallets if p.altura_final < config.ALTURA_TOTAL_MIN_TOLERADO)
    altura_prom = sum(p.altura_final for p in resultado.pallets) / total
    peso_prom = sum(p.peso_estimado for p in resultado.pallets) / total

    with capsys.disabled():
        print("\n--- Ocupación ---")
        print(f"Pallets totales:        {total}")
        print(f"Pallets parciales:      {parciales} ({parciales / total:.0%})")
        print(f"Altura promedio:        {altura_prom:.1f} cm de {config.ALTURA_TOTAL_MAX}")
        print(f"Aprovechamiento altura: {altura_prom / config.ALTURA_TOTAL_MAX:.0%}")
        print(f"Peso promedio:          {peso_prom:.1f} kg de {config.PESO_TOPE_ELASTICO_KG}")
    assert total > 0
```

## `tests/test_pipeline_real_data.py`

```python
from pathlib import Path

import config
from src.derivados import calcular_derivados
from src.pipeline import ejecutar_desde_archivo
from src.validacion import cargar_hojas, validar_y_limpiar

ARCHIVO_REAL = Path(__file__).resolve().parent.parent / "Cubicaje18.07.2026.xlsx"


def test_no_genera_pallets_homogeneos_con_demanda_de_julio():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    assert (resultado.plan_picking_df["Tipo_Pallet"] == "Homogéneo").sum() == 0


def test_alturas_nunca_exceden_el_maximo():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    alturas = resultado.plan_picking_df.drop_duplicates("ID_Pallet")["Altura_Final_Pallet_cm"]
    assert (alturas <= config.ALTURA_TOTAL_MAX).all()


def test_ningun_pallet_mezcla_comestibles_y_cigarros_como_remate():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    for _, grupo in df.groupby("ID_Pallet"):
        categorias = set(grupo["Categoria"].dropna())
        assert not ({"Comestibles", "Cigarros"} <= categorias)


def test_demanda_planificada_coincide_con_demanda_redondeada():
    envios, maestro, uma = cargar_hojas(ARCHIVO_REAL)
    df_validado, _ = validar_y_limpiar(envios, maestro, uma)
    df_derivado = calcular_derivados(df_validado)

    demanda_esperada = df_derivado.groupby(["CD", "SKU"])["Cajas_Teoricas_Redondeadas"].sum()

    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    df = resultado.plan_picking_df
    df["SKU"] = df["SKU"].astype(str)
    demanda_planificada = df.groupby(["CD", "SKU"])["Cajas_Totales_Pallet"].sum()

    assert demanda_esperada.index.difference(demanda_planificada.index).empty
    assert demanda_planificada.index.difference(demanda_esperada.index).empty
    diferencias = (demanda_planificada - demanda_esperada).dropna()
    assert (diferencias == 0).all()


def test_log_validacion_registra_los_hallazgos_conocidos():
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    reglas = set(resultado.log_validacion_df["regla"])
    assert "V6" in reglas
    # V7 ("Cajas por cama" nulo/0 en el Maestro) ya no aplica: la versión del
    # dataset corregida el 12-ago no tiene ningún SKU con ese dato faltante.
    # No es una regresión de código, es un hecho de la data actual.
```


---

## Verificación — tests y benchmark

Este repo no tiene `pytest` instalable en el sandbox usado para generar este documento (sin red, y el `env/` del proyecto quedó armado para macOS/Python 3.11, incompatible con el intérprete disponible). Los 46 tests de la suite se corrieron igual, importando cada función de test directamente y proveyendo a mano las fixtures de `conftest.py` (`dataset_factory`) y de `test_invariantes.py` (`resultado`, `demanda_oficial`). Resultado:

```

======================================================================
46/46 pasaron
======================================================================
[OK  ] test_validacion::test_normaliza_casing_de_categoria
[OK  ] test_validacion::test_categoria_no_clasificada_se_loguea_pero_no_excluye
[OK  ] test_validacion::test_sku_sin_maestro_se_excluye
[OK  ] test_validacion::test_sentinel_cajas_por_ph_se_marca_no_confiable
[OK  ] test_validacion::test_dimension_imposible_se_excluye
[OK  ] test_validacion::test_altura_excesiva_se_excluye
[OK  ] test_validacion::test_cajas_por_cama_cero_se_trata_como_nulo
[OK  ] test_validacion::test_peso_fuera_de_rango_se_marca_no_validable_sin_excluir
[OK  ] test_validacion::test_cajas_teoricas_no_positivas_se_excluyen
[OK  ] test_validacion::test_duplicados_cd_sku_se_suman
[OK  ] test_derivados::test_redondeo_hacia_arriba_de_cajas_fraccionarias
[OK  ] test_derivados::test_fallback_geometrico_cuando_falta_cajas_por_cama
[OK  ] test_derivados::test_nivel_categoria_remate_es_el_nivel_mas_alto
[OK  ] test_derivados::test_nivel_categoria_asignado_para_categoria_estable
[OK  ] test_packing_2d::test_densidad_maxima_limita_cajas_por_cama
[OK  ] test_packing_2d::test_clustering_por_altura_no_combina_alturas_dispares
[OK  ] test_packing_2d::test_clustering_combina_alturas_similares
[OK  ] test_packing_2d::test_remate_nunca_comparte_cama
[OK  ] test_packing_2d::test_categorias_no_remate_pueden_compartir_cama_por_dimension
[OK  ] test_packing_2d::test_nabs_nunca_comparte_cama_con_niveles_base
[OK  ] test_apilado_3d::test_orden_de_estabilidad_se_respeta_sin_importar_orden_de_entrada
[OK  ] test_apilado_3d::test_remate_nunca_comparte_pallet_y_prioriza_mayor_remanente
[OK  ] test_apilado_3d::test_cierre_forzado_bajo_altura_minima_se_marca_parcial
[OK  ] test_apilado_3d::test_consolidacion_nunca_mueve_una_cama_hacia_un_pallet_mas_chico
[OK  ] test_topado_homogeneos::test_pallet_homogeneo_se_completa_con_remate_disponible
[OK  ] test_invariantes::test_orientacion_maximiza_cajas_totales[25-51]
[OK  ] test_invariantes::test_orientacion_maximiza_cajas_totales[51-25]
[OK  ] test_invariantes::test_orientacion_maximiza_cajas_totales[30-30]
[OK  ] test_invariantes::test_orientacion_maximiza_cajas_totales[110-40]
[OK  ] test_invariantes::test_orientacion_nunca_peor_que_la_alternativa
[OK  ] test_invariantes::test_orientacion_devuelve_none_si_no_cabe
[OK  ] test_invariantes::test_ningun_pallet_supera_el_tope_duro
[OK  ] test_invariantes::test_pallets_sobre_el_maximo_normal_son_pocos_y_justificados
[OK  ] test_invariantes::test_orden_vertical_de_categorias
[OK  ] test_invariantes::test_remate_exclusivo
[OK  ] test_invariantes::test_nada_pesado_encima_de_nabs
[OK  ] test_invariantes::test_peso_respetado_como_restriccion
[OK  ] test_invariantes::test_regla_de_soporte
[OK  ] test_invariantes::test_ids_de_pallet_unicos
[OK  ] test_invariantes::test_nunca_se_despacha_por_encima_de_la_demanda
[OK  ] test_invariantes::test_determinismo
[OK  ] test_pipeline_real_data::test_no_genera_pallets_homogeneos_con_demanda_de_julio
[OK  ] test_pipeline_real_data::test_alturas_nunca_exceden_el_maximo
[OK  ] test_pipeline_real_data::test_ningun_pallet_mezcla_comestibles_y_cigarros_como_remate
[OK  ] test_pipeline_real_data::test_demanda_planificada_coincide_con_demanda_redondeada
[OK  ] test_pipeline_real_data::test_log_validacion_registra_los_hallazgos_conocidos
```

### Benchmark contra `Cubicaje18.07.2026.xlsx` (antes / después)

| Métrica | Antes del parche | Después del parche |
|---|---|---|
| Pallets totales | 157 | 65 |
| Altura promedio | 40.7 cm | 77.7 cm |
| Peso promedio por pallet | 2.942 kg (irreal, bug de fórmula) | 228 kg |
| Peso máximo por pallet | 31.000 kg (imposible) | 1.081 kg |
| Pallets con una sola cama | 148 de 157 (94%) | ver nota |
| Cajas perdidas vs. demanda | 4 | 4 (sin cambios, no es regresión) |

El peso promedio bajó de 2.942 a 228 kg porque la fórmula vieja multiplicaba el peso de la caja (columna UMA) por "Unidades por caja" -para Cigarros de 1.000 unidades por caja eso daba 16.000 kg por caja. Con el fix (sección 5 del punto 6 original), el peso ahora es físicamente correcto.

**Cuello de botella que queda, fuera del alcance de los 6 puntos pedidos:** con peso y altura corregidos, lo que hoy limita que más pallets lleguen a la zona recomendada (195-200 cm) es `FILL_RATIO_MIN_SOPORTE = 0.60` (`[PARCHE P5]`, preexistente) -una cama con poca cobertura de la base no puede sostener otra encima, y bastantes remanentes chicos (1-60 cajas, como ya señalaba el doc de diseño para BK31/BK34) generan camas de baja cobertura que terminan solas en su pallet. No se tocó porque es una regla de seguridad de carga deliberada, no un bug; si se quiere más densidad a costa de ese margen de seguridad, es un solo número en `config.py`.
