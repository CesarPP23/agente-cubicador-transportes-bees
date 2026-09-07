import streamlit as st

from src.exportar import exportar_workbook
from src.pipeline import ejecutar_pipeline
from src.template import construir_template
from src.validacion import cargar_hojas, cargar_pallets_objetivo
from visualizacion import VISTAS_3D, dibujar_cama, dibujar_pallet, dibujar_pallet_v5_3d

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
pallets_objetivo_por_cd = None

if modo.startswith("Un solo"):
    archivo = st.file_uploader("Excel combinado", type=["xlsx"])
    if archivo is not None:
        envios, maestro, uma = cargar_hojas(archivo)
        pallets_objetivo_por_cd = cargar_pallets_objetivo(archivo)
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
        pallets_objetivo_por_cd = cargar_pallets_objetivo(archivo_envios)

if pallets_objetivo_por_cd:
    st.info(
        f"Cantidad de pallets fija (Pallets_Objetivo) detectada para {len(pallets_objetivo_por_cd)} CD(s): "
        f"{pallets_objetivo_por_cd}. Estos CDs pueden tardar varios minutos cada uno (el motor exacto "
        "corre backtracking + ruina-y-reconstrucción para aprovechar cada pallet al máximo, ver "
        "Parches/v5/PATCH_LOG.md)."
    )

if envios is not None and st.button("Procesar", type="primary"):
    with st.spinner("Ejecutando el motor de optimización..."):
        st.session_state["resultado"] = ejecutar_pipeline(envios, maestro, uma, pallets_objetivo_por_cd)

resultado = st.session_state.get("resultado")

if resultado is None:
    st.info("Sube los archivos y presiona **Procesar** para generar el plan de picking.")
    st.stop()

pallets = resultado.pallets
df = resultado.plan_picking_df
cajas_no_colocadas_df = resultado.cajas_no_colocadas_df
cajas_no_colocadas_total = (
    int(cajas_no_colocadas_df["Cajas_No_Colocadas"].sum())
    if cajas_no_colocadas_df is not None and not cajas_no_colocadas_df.empty
    else 0
)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Pallets totales", len(pallets))
col2.metric("Homogéneos (base 1 SKU)", sum(1 for p in pallets if p.tipo.startswith("Homogéneo")))
col3.metric("Mixtos", sum(1 for p in pallets if p.tipo == "Mixto"))
col4.metric("Alertas de peso", sum(1 for p in pallets if "ALERTA DE PESO" in p.estado))
col5.metric(
    "Cajas extra por consolidación",
    int(df["Cajas_Extra_Consolidacion"].sum()) if not df.empty else 0,
)
col6.metric("Cajas no colocadas", cajas_no_colocadas_total)

tab_plan, tab_log, tab_resumen, tab_no_colocadas, tab_inspector = st.tabs(
    ["Plan de Picking", "Log de Validación", "Resumen por CD", "⚠ Cajas No Colocadas", "Inspector de Pallets"]
)

with tab_plan:
    st.dataframe(df, use_container_width=True)

with tab_log:
    st.dataframe(resultado.log_validacion_df, use_container_width=True)

with tab_resumen:
    st.dataframe(resultado.resumen_cd_df, use_container_width=True)

with tab_no_colocadas:
    if cajas_no_colocadas_df is None or cajas_no_colocadas_df.empty:
        st.success("Toda la demanda se colocó -no quedaron cajas sin cubicar.")
    else:
        st.warning(
            f"{cajas_no_colocadas_total} cajas no entraron en ningún pallet -detalle por CD y SKU abajo. "
            "Esto pasa cuando un CD tiene `Pallets_Objetivo` fijo y esa cantidad de pallets genuinamente "
            "no alcanza para toda la demanda."
        )
        st.dataframe(cajas_no_colocadas_df, use_container_width=True)

with tab_inspector:
    if not pallets:
        st.warning("No se generaron pallets.")
    else:
        v5_por_id = {p.id: p for p in resultado.pallets_v5} if resultado.pallets_v5 else {}

        cds = sorted({p.cd for p in pallets})
        cd_elegido = st.selectbox("Centro de Distribución", cds)
        pallets_cd = [p for p in pallets if p.cd == cd_elegido]
        ids_pallet = [p.id for p in pallets_cd]
        id_elegido = st.selectbox("Pallet", ids_pallet)
        pallet = next(p for p in pallets_cd if p.id == id_elegido)
        pallet_v5 = v5_por_id.get(id_elegido)

        if pallet_v5 is not None:
            columna_vista, columna_torres = st.columns([1, 1.4])

            with columna_vista:
                vista = st.selectbox("Vista", list(VISTAS_3D.keys()), index=0)
                st.pyplot(dibujar_pallet_v5_3d(pallet_v5, resultado.info_sku, vista=vista))

            with columna_torres:
                st.caption(f"{len(pallet_v5.torres)} torres — ocupación XY {pallet_v5.ocupacion_xy:.0%}")
                filas = [
                    {
                        "SKU": "BAT" if t.sku == "__BAT__" else t.sku,
                        "x": t.x, "y": t.y, "cantidad": t.cantidad,
                        "altura_torre": round(t.altura, 1),
                        "orientación": t.orientacion,
                        "fuente_geometría": t.fuente_geometria,
                    }
                    for t in pallet_v5.torres
                ]
                st.dataframe(filas, use_container_width=True)
                estabilidad = pallet_v5.metadata.get("estabilidad")
                if estabilidad is not None:
                    st.caption(f"Estabilidad: {', '.join(estabilidad.estados)}")
        else:
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
