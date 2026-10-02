"""
Página de Cartones del Día.
Scraping de cartones editoriales de fuentes mexicanas.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
import tempfile
import os

from config import SOURCES_CFG, COPYRIGHT, CONTACTO_EMAILS
from services.cartones import fetch_all_cartones
from utils.pdf_generator import generar_pdf_cartones
from utils.date_helpers import TZ_MX
from utils.styles import get_header_html
from utils.auth import require_auth
from utils.audit_log import registrar

require_auth()
_usuario = st.session_state.get("username")

# =========================================================
# HEADER
# =========================================================
st.markdown(get_header_html("CARTONES DEL DÍA"), unsafe_allow_html=True)

st.divider()

# =========================================================
# SESSION STATE
# =========================================================
if "cartones_df" not in st.session_state:
    st.session_state.cartones_df = pd.DataFrame()
if "cartones_running" not in st.session_state:
    st.session_state.cartones_running = False
if "cartones_status" not in st.session_state:
    st.session_state.cartones_status = {}
if "cartones_all_items" not in st.session_state:
    st.session_state.cartones_all_items = []
if "cartones_seleccion" not in st.session_state:
    st.session_state.cartones_seleccion = set()


def _toggle_seleccion(stable_id: str) -> None:
    if stable_id in st.session_state.cartones_seleccion:
        st.session_state.cartones_seleccion.discard(stable_id)
    else:
        st.session_state.cartones_seleccion.add(stable_id)


# =========================================================
# CONFIGURACIÓN
# =========================================================
with st.expander("⚙️ Configuración", expanded=True):
    target_n = st.number_input("Cantidad:", value=20, min_value=5, max_value=50, step=1)
    lookback_days = st.number_input(
        "Solo hoy (0) / con días atrás:", value=0, min_value=0, max_value=30, step=1,
        help="0 = solo cartones de hoy. Sube el número para incluir días anteriores.",
    )
    verbose = st.checkbox("Mostrar logs en consola", value=False)

# =========================================================
# BARRA DE ACCIONES
# =========================================================
col_actualizar, col_pdf = st.columns(2)

with col_actualizar:
    btn_label = "⏹ Cancelar" if st.session_state.cartones_running else "🔄 Actualizar"
    btn_type = "secondary" if st.session_state.cartones_running else "primary"
    if st.button(btn_label, type=btn_type, use_container_width=True):
        if st.session_state.cartones_running:
            st.session_state.cartones_running = False
            st.toast("Cancelación solicitada", icon="⚠️")
        else:
            st.session_state.cartones_running = True
            st.session_state.cartones_status = {}
            st.session_state.cartones_all_items = []
            st.session_state.cartones_df = pd.DataFrame()
            st.rerun()

with col_pdf:
    if not st.session_state.cartones_df.empty:
        try:
            @st.cache_data
            def _pdf_cartones(df_json: str) -> bytes:
                import pandas as _pd
                import tempfile, os, io
                df = _pd.read_json(io.StringIO(df_json))
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp.close()
                generar_pdf_cartones(df, tmp.name)
                with open(tmp.name, "rb") as f:
                    data = f.read()
                os.unlink(tmp.name)
                return data

            descargado = st.download_button(
                "📄 Exportar PDF",
                data=_pdf_cartones(st.session_state.cartones_df.to_json()),
                file_name=f"cartones_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            if descargado:
                registrar(_usuario, "cartones", "exportar_pdf", detalle={
                    "num_cartones": len(st.session_state.cartones_df),
                })
        except Exception as e:
            registrar(_usuario, "cartones", "exportar_pdf", exito=False, detalle={"error": str(e)})
            st.error(f"Error al generar PDF: {e}")

st.markdown(
    """
    <style>
    div[class*="st-key-btn_eliminar_cartones"] button {
        background-color: #dc3545;
        color: white;
        border: none;
    }
    div[class*="st-key-btn_eliminar_cartones"] button:hover {
        background-color: #bb2d3b;
        color: white;
    }
    div[class*="st-key-btn_eliminar_cartones"] button:active {
        background-color: #a02834;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
col_eliminar, _ = st.columns([1, 3])
with col_eliminar:
    if st.session_state.cartones_seleccion:
        n_sel = len(st.session_state.cartones_seleccion)
        if st.button(f"🗑️ Eliminar {n_sel}", key="btn_eliminar_cartones", use_container_width=True):
            seleccion = st.session_state.cartones_seleccion
            df = st.session_state.cartones_df
            def _mantener(row):
                sid = row.get("url", "") or f"{row.get('titulo','')}_{row.get('fuente','')}_{row.name}"
                return sid not in seleccion
            antes = len(df)
            df_filtrado = df[df.apply(_mantener, axis=1)].reset_index(drop=True)
            st.session_state.cartones_df = df_filtrado
            st.session_state.cartones_seleccion = set()
            registrar(_usuario, "cartones", "eliminar_cartones", detalle={
                "num_eliminados": antes - len(df_filtrado),
            })
            st.toast(f"Eliminados {antes - len(df_filtrado)} cartón(es)", icon="🗑️")
            st.rerun()

# =========================================================
# PROCESAMIENTO
# =========================================================
if st.session_state.cartones_running:
    progress_bar = st.progress(0, text="Iniciando...")

    def progress_callback(pct, msg):
        progress_bar.progress(pct, text=msg)

    try:
        df_final, all_items, source_status = fetch_all_cartones(
            lookback_days=lookback_days,
            target_n=target_n,
            verbose=verbose,
            progress_callback=progress_callback,
        )

        st.session_state.cartones_df = df_final
        st.session_state.cartones_all_items = all_items
        st.session_state.cartones_status = source_status
        st.session_state.cartones_running = False

        progress_bar.progress(1.0, text="Completado")

        registrar(_usuario, "cartones", "actualizar_cartones", exito=not df_final.empty, detalle={
            "cantidad": target_n, "dias_atras": lookback_days, "resultados": len(df_final),
        })

        if not df_final.empty:
            st.toast(f"Se encontraron {len(df_final)} cartones", icon="🖼️")
        else:
            st.warning("No se encontraron cartones con los criterios actuales.")

        st.rerun()

    except Exception as e:
        st.session_state.cartones_running = False
        registrar(_usuario, "cartones", "actualizar_cartones", exito=False, detalle={"error": str(e)})
        st.error(f"Error durante el procesamiento: {e}")
        st.rerun()

# =========================================================
# TABLA DE RESULTADOS
# =========================================================
df_actual = st.session_state.cartones_df

if df_actual is not None and not df_actual.empty:
    st.subheader(f"Resultados: {len(df_actual)} cartones")
    if st.session_state.cartones_seleccion:
        st.info(f"{len(st.session_state.cartones_seleccion)} seleccionado(s) — usa la barra lateral para eliminar")

    # Preparar para visualización
    df_display = df_actual.copy()
    if "fecha" in df_display.columns:
        df_display["fecha_display"] = df_display["fecha"].apply(
            lambda x: x.strftime("%Y-%m-%d %H:%M") if isinstance(x, datetime) else "N/D"
        )
    else:
        df_display["fecha_display"] = "N/D"

    # Mostrar tabla con checkboxes y miniaturas
    for idx, row in df_display.iterrows():
        # Usar URL como identificador estable (o titulo+fuente como fallback)
        stable_id = row.get("url", "") or f"{row.get('titulo','')}_{row.get('fuente','')}_{idx}"
        with st.container():
            col_check, col_img, col_info = st.columns([0.3, 1, 3])

            with col_check:
                checked = stable_id in st.session_state.cartones_seleccion
                st.checkbox(
                    f"Seleccionar: {row.get('titulo', 'cartón sin título')}",
                    value=checked,
                    key=f"sel_{stable_id}",
                    on_change=_toggle_seleccion,
                    args=(stable_id,),
                    label_visibility="collapsed",
                )

            with col_img:
                img_url = row.get("img", "")
                if img_url and isinstance(img_url, str) and img_url.startswith("http"):
                    try:
                        st.image(img_url, width=200, caption=row.get("fuente", ""))
                    except Exception:
                        st.caption("Imagen no disponible")
                else:
                    st.caption("Sin imagen")

            with col_info:
                st.markdown(f"**{row.get('titulo', '(sin título)')}**")
                st.markdown(
                    f"Fuente: {row.get('fuente', 'N/A')} | "
                    f"Fecha: {row.get('fecha_display', 'N/D')}"
                )
                url = row.get("url", "")
                if url and isinstance(url, str) and url.startswith("http"):
                    st.markdown(f"[Abrir enlace]({url})")

            st.divider()

else:
    if not st.session_state.cartones_running:
        st.info("Presiona 'Actualizar' para cargar cartones.")

# =========================================================
# NOTAS
# =========================================================
if df_actual is not None and not df_actual.empty:
    with st.expander("Notas y uso"):
        st.markdown("""
        - **Tip:** Marca cartones con el checkbox y elimínalos con el botón **Eliminar**.
        - **Exportación:** El PDF incluirá únicamente los cartones restantes.
        - **Nota legal/uso justo:** Se muestran cartones con atribución y liga a la fuente. Revisa Términos de cada sitio.
        """)
    with st.expander("📊 Estado de fuentes"):
        if st.session_state.cartones_status:
            for fuente_cfg in SOURCES_CFG:
                f = fuente_cfg["fuente"]
                status_info = st.session_state.cartones_status.get(f, {})
                status = status_info.get("status", "Pendiente")
                count = status_info.get("count", 0)
                icon = {"OK": "✅", "Error": "❌", "Procesando": "⏳"}.get(status, "⏸️")
                st.markdown(f"{icon} **{f}**: {count} items ({status})")
        else:
            st.caption("Sin datos. Actualiza para ver el estado.")

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.markdown(
    f"""
    <div style='text-align: center; font-size: 12px; color: #666;'>
        {COPYRIGHT}<br>
        {CONTACTO_EMAILS}
    </div>
    """,
    unsafe_allow_html=True,
)
