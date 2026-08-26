import pandas as pd
import pytest

ENVIOS_COLS = ["CD", "SKU", "Descripción", "Cajas Teóricas", "Unidades"]
MAESTRO_COLS = ["SKU", "Categoría", "Subcategoría", "Unidades por caja", "Cajas por cama", "Camas por PH", "Cajas por PH"]
UMA_COLS = ["SKU", "Largo de caja", "Ancho de caja", "Alto de caja", "Peso bruto por unidad"]


def _envio(cd="BK31", sku=1, descripcion="Producto", cajas=10, unidades=None):
    return {
        "CD": cd,
        "SKU": sku,
        "Descripción": descripcion,
        "Cajas Teóricas": cajas,
        "Unidades": unidades if unidades is not None else cajas,
    }


def _maestro(
    sku=1, categoria="Licores", subcategoria=None, unidades_por_caja=1,
    cajas_por_cama=10, camas_por_ph=5, cajas_por_ph=50,
):
    return {
        "SKU": sku,
        "Categoría": categoria,
        "Subcategoría": subcategoria,
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
