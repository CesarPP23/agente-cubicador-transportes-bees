"""Fixture del Golden Case BK31 (PATCH V6.01, sección 4).

Demanda real de BK31 (CD Cañete, `Pallets_Objetivo=1`), extraída de
`Plantilla_Ejemplo_Agente_Cubicador (1) (3).xlsx` (hojas `Envios_Julio`,
`Maestro_SKUs`, `UMA` filtradas a CD=BK31 -ver
`tests/fixtures/bk31_manual.xlsx`, copia recortada de esas mismas filas) y
reconstrucción caja por caja del pallet armado a mano
(`Parches/v5/ejemplo_manual_bk31/armado_manual_bk31.py`, sesión de chat
completa, README de esa carpeta).

No cuenta Pall Mall Boost/Sunrely (SKUs 19238/22938, 0.1 cajas teóricas
cada uno): van a la caja de consolidación de Cigarros aparte (src/bat.py),
nunca entran al cubicaje geométrico -por eso no están en `DEMANDA_BK31`
(12 SKUs, 98 cajas) aunque sí figuran en el Excel recortado.

Sistema de coordenadas del armado manual: el script original
(`armado_manual_bk31.py`) grafica con su eje `x` (0-100, "Frente") a lo
largo del ANCHO físico del pallet (config.PALLET_ANCHO=100) y su eje `y`
(0-120, "Fondo") a lo largo del LARGO físico (config.PALLET_LARGO=120)
-al revés de la convención de `models.Torre` (`x` a lo largo de
PALLET_LARGO, `y` a lo largo de PALLET_ANCHO). `_CAJAS_MANUAL_RAW` reusa
EXACTAMENTE las mismas llamadas `add(...)` del script original;
`torres_manual_bk31()` hace el swap x<->y (y dx<->dy) al convertir a
`Torre`.
"""
from __future__ import annotations

import pandas as pd

import config
from models import PalletV5, Torre

# --- 1. Demanda real (SKU, Descripción, Categoría, Subcategoría, Cantidad,
#     Largo/Ancho/Alto de caja UMA, Cajas por PH del Maestro, Peso bruto) ---
DEMANDA_BK31 = [
    {"SKU": "15506", "Descripcion": "Vino Borgoña Queirolo 750ml 1x1", "Categoria": "Licores", "Subcategoria": "Vino", "Cajas": 57, "Largo": 31.0, "Ancho": 24.0, "Alto": 30.5, "Cajas_por_cama": 15, "Camas_por_PH": 5, "Cajas_por_PH": 75, "Peso_Caja": 15.000},
    {"SKU": "23486", "Descripcion": "Altomayo Cafe Inst Gourmet 14gr 2x6", "Categoria": "Comestibles", "Subcategoria": "Café", "Cajas": 6, "Largo": 25.7, "Ancho": 26.0, "Alto": 17.0, "Cajas_por_cama": 12, "Camas_por_PH": 10, "Cajas_por_PH": 120, "Peso_Caja": 0.000},
    {"SKU": "22713", "Descripcion": "KR Gaseosa Naranja 350ml 15x1", "Categoria": "NABs", "Subcategoria": "Gaseosa", "Cajas": 4, "Largo": 28.5, "Ancho": 17.0, "Alto": 21.5, "Cajas_por_cama": 24, "Camas_por_PH": 8, "Cajas_por_PH": 192, "Peso_Caja": 7.845},
    {"SKU": "20233", "Descripcion": "AM Cafe Inst Gourmet 7gr 2x8", "Categoria": "Comestibles", "Subcategoria": "Café", "Cajas": 3, "Largo": 35.0, "Ancho": 27.0, "Alto": 13.0, "Cajas_por_cama": 11, "Camas_por_PH": 12, "Cajas_por_PH": 132, "Peso_Caja": 1.600},
    {"SKU": "22712", "Descripcion": "KR Gaseosa Limón 350ml 15x1", "Categoria": "NABs", "Subcategoria": "Gaseosa", "Cajas": 2, "Largo": 28.5, "Ancho": 17.0, "Alto": 21.5, "Cajas_por_cama": 24, "Camas_por_PH": 8, "Cajas_por_PH": 192, "Peso_Caja": 7.845},
    {"SKU": "22354", "Descripcion": "Molitalia Sémola 200g 10x1", "Categoria": "Comestibles", "Subcategoria": "Pastas", "Cajas": 4, "Largo": 47.0, "Ancho": 13.0, "Alto": 10.0, "Cajas_por_cama": 14, "Camas_por_PH": 14, "Cajas_por_PH": 196, "Peso_Caja": 4.040},
    {"SKU": "22726", "Descripcion": "Vodka Russkaya Grape 750ml 1x1", "Categoria": "Licores", "Subcategoria": "Vodka", "Cajas": 1, "Largo": 31.1, "Ancho": 23.2, "Alto": 30.2, "Cajas_por_cama": 15, "Camas_por_PH": 5, "Cajas_por_PH": 75, "Peso_Caja": 15.396},
    {"SKU": "22715", "Descripcion": "Gaseosa Oro Cola Amarilla 350ml 15x1", "Categoria": "NABs", "Subcategoria": "Gaseosa", "Cajas": 5, "Largo": 28.5, "Ancho": 17.0, "Alto": 21.5, "Cajas_por_cama": 25, "Camas_por_PH": 6, "Cajas_por_PH": 150, "Peso_Caja": 7.845},
    {"SKU": "22176", "Descripcion": "Pringles Papas Queso 40g 12x1", "Categoria": "Comestibles", "Subcategoria": "Snacks", "Cajas": 5, "Largo": 29.0, "Ancho": 22.5, "Alto": 13.0, "Cajas_por_cama": 0, "Camas_por_PH": 0, "Cajas_por_PH": 168, "Peso_Caja": 6.480},
    {"SKU": "19685", "Descripcion": "Picaras Mini Clasica 46gr 6x1", "Categoria": "Comestibles", "Subcategoria": "Galletas y Wafers", "Cajas": 5, "Largo": 39.0, "Ancho": 30.0, "Alto": 28.5, "Cajas_por_cama": 10, "Camas_por_PH": 6, "Cajas_por_PH": 60, "Peso_Caja": 4.116},
    {"SKU": "21191", "Descripcion": "PO Picaras Extremas 38gr 18x1", "Categoria": "Comestibles", "Subcategoria": "Galletas y Wafers", "Cajas": 4, "Largo": 39.0, "Ancho": 30.0, "Alto": 28.5, "Cajas_por_cama": 9, "Camas_por_PH": 6, "Cajas_por_PH": 54, "Peso_Caja": 7.740},
    {"SKU": "21850", "Descripcion": "PO Picaras Fresa 38gr 18x1", "Categoria": "Comestibles", "Subcategoria": "Galletas y Wafers", "Cajas": 2, "Largo": 39.0, "Ancho": 30.0, "Alto": 28.5, "Cajas_por_cama": 9, "Camas_por_PH": 5, "Cajas_por_PH": 45, "Peso_Caja": 7.200},
]

DEMANDA_TOTAL_CAJAS = sum(fila["Cajas"] for fila in DEMANDA_BK31)  # 98


def demanda_df() -> pd.DataFrame:
    """DataFrame "crudo" de negocio -una fila por SKU, columnas de sección
    4 del patch (SKU/Descripción/Categoría/.../Peso). No apto directo para
    `armar_pallets_bloques` -ver `demanda_solver_df()`."""
    return pd.DataFrame(DEMANDA_BK31)


def demanda_solver_df() -> pd.DataFrame:
    """Misma demanda, con las columnas que consume
    `src.packing_bloques.armar_pallets_bloques` (Cajas_Remanente,
    *_Efectivo, Cajas_Cama_Efectivo, Nivel_Categoria, Categoria_Normalizada,
    "Cajas por PH") -geometría ya "reconciliada" (acá, trivialmente: UMA
    tal cual, sin necesidad de inferencia porque el Maestro ya la valida
    -mismo criterio que `reconciliacion_geometrica.reconciliar_sku` con
    fuente UMA_VALIDADA)."""
    filas = []
    for fila in DEMANDA_BK31:
        categoria_norm = config.normalizar_categoria(fila["Categoria"])
        filas.append({
            "SKU": fila["SKU"],
            "CD": "BK31",
            "Cajas_Remanente": fila["Cajas"],
            "Largo_Efectivo": fila["Largo"],
            "Ancho_Efectivo": fila["Ancho"],
            "Alto_Efectivo": fila["Alto"],
            "Peso_Caja": fila["Peso_Caja"],
            "Fuente_Geometria": "UMA_VALIDADA",
            "Cajas_Cama_Efectivo": fila["Cajas_por_cama"] or None,
            "Categoria_Normalizada": categoria_norm,
            "Nivel_Categoria": config.nivel_de_categoria(categoria_norm),
            "Cajas por PH": fila["Cajas_por_PH"],
        })
    return pd.DataFrame(filas)


def cajas_por_ph_bk31() -> dict[str, int]:
    return {fila["SKU"]: fila["Cajas_por_PH"] for fila in DEMANDA_BK31}


# --- 2. Reconstrucción manual, caja por caja (Parches/v5/ejemplo_manual_bk31/
#     armado_manual_bk31.py, mismas llamadas `add(...)` exactas) ---
_CAJAS_MANUAL_RAW: list[dict] = []


def _add(sku, x, y, z, largo, ancho, alto, cantidad):
    for i in range(cantidad):
        _CAJAS_MANUAL_RAW.append(
            {"sku": sku, "x": x, "y": y, "z": z + i * alto, "dx": largo, "dy": ancho, "dz": alto}
        )


def _construir_cajas_manual_raw() -> None:
    _CAJAS_MANUAL_RAW.clear()
    # Cama1 (Z=0)
    for j in range(3):
        for i in range(4):
            _add('15506', i * 24, j * 31, 0, 24, 31, 30.5, 1)
    for i in range(3):
        _add('15506', i * 31 + 7, 93, 0, 31, 24, 30.5, 1)
    # Cama2 (Z=30.5)
    xs2 = [4, 28, 52, 76]
    for y in [27, 58, 89]:
        for x in xs2:
            _add('15506', x, y, 30.5, 24, 31, 30.5, 1)
    for x in [7, 38, 69]:
        _add('15506', x, 3, 30.5, 31, 24, 30.5, 1)
    # Cama3 (Z=61.0)
    for j in range(3):
        for i in range(4):
            _add('15506', i * 24, j * 31, 61.0, 24, 31, 30.5, 1)
    for i in range(3):
        _add('15506', i * 31 + 7, 93, 61.0, 31, 24, 30.5, 1)
    # Cama4 (Z=91.5)
    for y in [27, 58]:
        for x in xs2:
            _add('15506', x, y, 91.5, 24, 31, 30.5, 1)
    for x in [7, 38, 69]:
        _add('15506', x, 3, 91.5, 31, 24, 30.5, 1)
    _add('15506', 76, 89, 91.5, 24, 31, 30.5, 1)
    _add('22726', 1.8, 89, 91.5, 23.2, 31.1, 30.2, 1)
    _add('22713', 25.0, 89, 91.5, 17.0, 28.5, 21.5, 2)
    _add('22713', 42.0, 89, 91.5, 17.0, 28.5, 21.5, 2)
    _add('22712', 59.0, 89, 91.5, 17.0, 28.5, 21.5, 2)
    # Gaseosa Oro
    for i in range(5):
        _add('22715', 32.5, 3 + i * 17.0, 122.0, 28.5, 17.0, 21.5, 1)
    # Picaras (3 confirmadas + 2 Mini adicionales)
    _add('19685', 61, 0, 122.0, 39.0, 30.0, 28.5, 1)
    _add('21191', 61, 30, 122.0, 39.0, 30.0, 28.5, 1)
    _add('21850', 61, 60, 122.0, 39.0, 30.0, 28.5, 1)
    _add('19685', 1.8, 3, 122.0, 30.0, 39.0, 28.5, 1)
    _add('19685', 1.8, 42, 122.0, 30.0, 39.0, 28.5, 1)
    # Cama 6: mismas 5 posiciones de la cama 5, apiladas encima (z=150.5)
    _add('19685', 1.8, 3, 150.5, 30.0, 39.0, 28.5, 1)
    _add('19685', 1.8, 42, 150.5, 30.0, 39.0, 28.5, 1)
    _add('21191', 61, 0, 150.5, 39.0, 30.0, 28.5, 1)
    _add('21191', 61, 30, 150.5, 39.0, 30.0, 28.5, 1)
    _add('21191', 61, 60, 150.5, 39.0, 30.0, 28.5, 1)
    # AM Cafe sobre la repisa de las 3 KR
    _add('20233', 25.0, 89, 134.5, 35.0, 27.0, 13.0, 3)
    # Altomayo: 4 apiladas sobre el Vino + 2 giradas sobre el resto de la repisa KR
    _add('23486', 76.0, 89, 122.0, 25.7, 26.0, 17.0, 4)
    _add('23486', 60.0, 89, 134.5, 17.0, 26.0, 25.7, 2)
    # Ultima Fresa (Picaras), acostada
    _add('21850', 32.5, 49, 143.5, 28.5, 39.0, 30.0, 1)
    # Pringles (5)
    _add('22176', 32.5, 3.0, 143.5, 13.0, 22.5, 29.0, 1)
    _add('22176', 32.5, 25.5, 143.5, 13.0, 22.5, 29.0, 1)
    _add('22176', 45.5, 3.0, 143.5, 13.0, 22.5, 29.0, 1)
    _add('22176', 45.5, 25.5, 143.5, 13.0, 22.5, 29.0, 2)
    # Molitalia (4)
    _add('22354', 1.8, 89.0, 121.7, 10.0, 13.0, 47.0, 1)
    _add('22354', 1.8, 102.0, 121.7, 10.0, 13.0, 47.0, 1)
    _add('22354', 11.8, 89.0, 121.7, 10.0, 13.0, 47.0, 1)
    _add('22354', 11.8, 102.0, 121.7, 10.0, 13.0, 47.0, 1)


_construir_cajas_manual_raw()


def torres_manual_bk31() -> list[Torre]:
    """Convierte `_CAJAS_MANUAL_RAW` (sistema de coordenadas del script de
    referencia) al sistema de `models.Torre` (`x` a lo largo de
    PALLET_LARGO=120, `y` a lo largo de PALLET_ANCHO=100): swap x<->y,
    dx<->dy -ver docstring del módulo."""
    torres = []
    for c in _CAJAS_MANUAL_RAW:
        torres.append(Torre(
            sku=c["sku"], cd="BK31", orientacion="manual",
            x=c["y"], y=c["x"], z=c["z"],
            largo=c["dy"], ancho=c["dx"], alto_caja=c["dz"],
            cantidad=1, peso=0.0, fuente_geometria="UMA_VALIDADA",
        ))
    return torres


def cargar_pallet_manual_bk31() -> PalletV5:
    torres = torres_manual_bk31()
    altura_final = config.ALTURA_PALLET_VACIO + max(t.z + t.altura for t in torres)
    return PalletV5(id="BK31-MANUAL", cd="BK31", torres=torres, altura_final=altura_final)
