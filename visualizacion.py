import matplotlib.patches as patches
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

import config
from models import Cama, Pallet, PalletV5
from src.bat import BAT_SKU_MARCADOR

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


# ============================================================================
# [V5-P12] Visualización 3D real de PalletV5 (torres) -DOCUMENTACION_TECNICA_V5.md
# sección 14: "toda posición exportada debe poder verse". Reemplaza la vista
# 2D por cama (dibujar_pallet, arriba) para el modelo columnar -una torre no
# es una franja horizontal uniforme, tiene x/y/altura propios que la vista
# por cama no puede representar.
# ============================================================================

COLOR_BAT = "#7a5c1e"
COLOR_BASE_PALLET = "#c9a876"

VISTAS_3D = {
    "isometrica": (22, -60),
    "frente": (0, -90),
    "lateral": (0, 0),
    "superior": (90, -90),
}


def _cuboide(x: float, y: float, z: float, dx: float, dy: float, dz: float) -> list[list[tuple[float, float, float]]]:
    """Devuelve las 6 caras de una caja [x,x+dx]x[y,y+dy]x[z,z+dz] como listas
    de vértices, listas para `Poly3DCollection`."""
    v = [
        (x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z),
        (x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz),
    ]
    return [
        [v[0], v[1], v[2], v[3]],  # piso
        [v[4], v[5], v[6], v[7]],  # techo
        [v[0], v[1], v[5], v[4]],  # frente
        [v[2], v[3], v[7], v[6]],  # atrás
        [v[1], v[2], v[6], v[5]],  # derecha
        [v[0], v[3], v[7], v[4]],  # izquierda
    ]


def dibujar_pallet_v5_3d(pallet: PalletV5, info_sku: dict, vista: str = "isometrica") -> plt.Figure:
    """[V5-P12] Dibuja un PalletV5 en 3D real: una caja por posición (x, y, z)
    dentro de cada torre, coloreada por categoría del SKU. Las cajas BAT
    (torre con sku `bat.BAT_SKU_MARCADOR`) se marcan con `COLOR_BAT` -no
    tienen categoría propia, son la caja física de consolidación."""
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="3d")

    elev, azim = VISTAS_3D.get(vista, VISTAS_3D["isometrica"])
    ax.view_init(elev=elev, azim=azim)

    altura_max = max(pallet.altura_final, config.ALTURA_TOTAL_MAX) + 10
    ax.set_xlim(0, config.PALLET_LARGO)
    ax.set_ylim(0, config.PALLET_ANCHO)
    ax.set_zlim(0, altura_max)
    ax.set_xlabel("Largo (cm)")
    ax.set_ylabel("Ancho (cm)")
    ax.set_zlabel("Altura (cm)")
    ax.set_title(f"{pallet.id} — {pallet.altura_final:.1f} cm — {pallet.estado}", fontsize=9, color=COLOR_TEXTO)

    base = _cuboide(0, 0, 0, config.PALLET_LARGO, config.PALLET_ANCHO, config.ALTURA_PALLET_VACIO)
    ax.add_collection3d(Poly3DCollection(base, facecolor=COLOR_BASE_PALLET, edgecolor=COLOR_BORDE, linewidths=0.5, alpha=0.9))

    categorias_presentes = set()
    z0 = config.ALTURA_PALLET_VACIO
    for torre in pallet.torres:
        es_bat = torre.sku == "__BAT__"
        categoria = None if es_bat else info_sku.get(torre.sku, {}).get("categoria")
        color = COLOR_BAT if es_bat else COLOR_CATEGORIA.get(categoria, COLOR_DEFECTO)
        categorias_presentes.add("BAT (consolidación)" if es_bat else (categoria or "Sin categoría"))

        if torre.placements:
            for placement in torre.placements:
                caras = _cuboide(placement.x, placement.y, z0 + placement.z, placement.largo, placement.ancho, placement.alto)
                ax.add_collection3d(Poly3DCollection(caras, facecolor=color, edgecolor="white", linewidths=0.4, alpha=0.95))
        else:
            # Sin placements individuales (ej. torres BAT armadas por caja
            # completa): se dibuja la torre entera como un solo bloque.
            caras = _cuboide(torre.x, torre.y, z0 + torre.z, torre.largo, torre.ancho, torre.altura)
            ax.add_collection3d(Poly3DCollection(caras, facecolor=color, edgecolor="white", linewidths=0.4, alpha=0.95))

        etiqueta = "BAT" if es_bat else str(torre.sku)
        ax.text(
            torre.x + torre.largo / 2, torre.y + torre.ancho / 2, z0 + torre.z + torre.altura + 2,
            f"{etiqueta}\nx{torre.cantidad}", ha="center", va="bottom", fontsize=6, color=COLOR_TEXTO,
        )

    handles = [patches.Patch(facecolor=(COLOR_BAT if c.startswith("BAT") else COLOR_CATEGORIA.get(c, COLOR_DEFECTO)), label=c) for c in sorted(categorias_presentes)]
    if handles:
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=min(len(handles), 4), fontsize=7, frameon=False)

    fig.tight_layout()
    return fig
