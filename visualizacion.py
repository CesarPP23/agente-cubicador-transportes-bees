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
