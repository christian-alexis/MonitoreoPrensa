"""
Página de Síntesis de Noticias.
Scraping de Google News RSS con fuentes confiables mexicanas.
"""
import io
import os
import threading
import time

import streamlit as st
import pandas as pd
from datetime import datetime

from config import CATEGORIAS_KEYWORDS, FUENTES_CONFIABLES, COPYRIGHT, CONTACTO_EMAILS
from services.sintesis_noticias import buscar_por_categorias, es_fuente_confiable
from services.sintesis_ia import CADENA_IA, ejecutar_cascada
from utils.pdf_generator import generar_pdf_sintesis
from utils.date_helpers import TZ_MX
from utils.styles import get_header_html
from utils.auth import require_auth
from utils.audit_log import registrar

require_auth()
_usuario = st.session_state.get("username")

# =========================================================
# HEADER
# =========================================================
st.markdown(get_header_html("SÍNTESIS DE PRENSA"), unsafe_allow_html=True)
st.divider()

# =========================================================
# SESSION STATE
# =========================================================
if "noticias_df" not in st.session_state:
    st.session_state.noticias_df = pd.DataFrame()
if "editando_idx" not in st.session_state:
    st.session_state.editando_idx = None
if "generando_resumen_idx" not in st.session_state:
    st.session_state.generando_resumen_idx = None
if "analizando_relevancia" not in st.session_state:
    st.session_state.analizando_relevancia = False
if "relevancia_ctx" not in st.session_state:
    st.session_state.relevancia_ctx = None
if "relevancia_thread" not in st.session_state:
    st.session_state.relevancia_thread = None
if "ai_news_provider" not in st.session_state:
    st.session_state.ai_news_provider = "Gemini (gratis)"
if "noticias_uso" not in st.session_state:
    st.session_state.noticias_uso = []
if "ultimo_exito_noticias" not in st.session_state:
    st.session_state.ultimo_exito_noticias = None
if "mostrar_uso_noticias" not in st.session_state:
    st.session_state.mostrar_uso_noticias = False

# Keys de IA (compartidas con las demás páginas)
if "api_key_anthropic" not in st.session_state:
    st.session_state.api_key_anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
if "api_key_groq" not in st.session_state:
    st.session_state.api_key_groq = os.environ.get("GROQ_API_KEY", "")
if "api_key_openrouter" not in st.session_state:
    st.session_state.api_key_openrouter = os.environ.get("OPENROUTER_API_KEY", "")
if "api_key_cerebras" not in st.session_state:
    st.session_state.api_key_cerebras = os.environ.get("CEREBRAS_API_KEY", "")


def _claves_ia() -> dict:
    return {
        "gemini": st.session_state.get("api_key_gemini", ""),
        "anthropic": st.session_state.get("api_key_anthropic", ""),
        "groq": st.session_state.get("api_key_groq", ""),
        "openrouter": st.session_state.get("api_key_openrouter", ""),
        "cerebras": st.session_state.get("api_key_cerebras", ""),
    }


def _registrar_uso(operacion: str, proveedor: str, ok: bool, detalle: str = ""):
    uso = st.session_state.noticias_uso
    uso.append({
        "operacion": operacion,
        "proveedor": proveedor,
        "ok": bool(ok),
        "detalle": detalle or "",
    })
    st.session_state.noticias_uso = uso[-200:]
    if ok:
        st.session_state.ultimo_exito_noticias = {
            "operacion": operacion,
            "proveedor": proveedor,
        }
        # Abrir la ventana emergente al generar análisis/resúmenes (no en el chat)
        if operacion in ("generar_resumen_noticia", "analizar_relevancia", "generar_resumen_ejecutivo"):
            st.session_state.mostrar_uso_noticias = True


_ETIQUETAS_OP = {
    "generar_resumen_noticia": "📰 Resumen de una noticia",
    "analizar_relevancia": "🔍 Análisis de relevancia",
    "generar_resumen_ejecutivo": "📝 Resumen ejecutivo",
}

# Análisis de relevancia en segundo plano: el hilo SOLO toca este dict (no usa
# st.session_state), así el re-run normal de Streamlit (por clics/mouse) no
# bloquea ni reinicia el proceso.
_RELEV_LOCK = threading.Lock()


def _procesar_relevancia(registros, proveedor, claves, ctx):
    """Trabajador en segundo plano del análisis de relevancia."""
    import pandas as _pd
    from services.sintesis_ia import ejecutar_cascada as _ejecutar

    df = _pd.DataFrame(registros)
    total = len(df)
    try:
        for idx in range(total):
            if ctx.get("cancel"):
                break
            fila = df.iloc[idx]
            titulo = str(fila.get("Título", ""))
            url = str(fila.get("Enlace_URL", ""))
            fuente = str(fila.get("Fuente", ""))

            def on_uso(op, prov, ok, detalle=""):
                with _RELEV_LOCK:
                    ctx["uso"].append((op, prov, ok, detalle))

            resultado, proveedor_u = _ejecutar(
                "analizar_relevancia", proveedor, claves, on_uso, titulo, url, fuente
            )
            if resultado is None:
                resultado = {"relevancia": 0, "razonamiento": "Sin IA disponible"}
            df.iat[idx, df.columns.get_loc("Relevancia_SHCP")] = resultado["relevancia"]
            df.iat[idx, df.columns.get_loc("Razón_Relevancia")] = resultado["razonamiento"]
            with _RELEV_LOCK:
                ctx["status"] = {"actual": idx + 1, "total": total, "titulo": titulo}

        df = df.sort_values("Relevancia_SHCP", ascending=False).reset_index(drop=True)
        df["ID"] = range(1, len(df) + 1)
        if "Fecha_Ordenable" in df.columns:
            df["Fecha_Ordenable"] = df["Fecha_Ordenable"].astype(str)
        with _RELEV_LOCK:
            ctx["df_json"] = df.to_json()
            ctx["status"] = {"actual": total, "total": total, "titulo": ""}
    except Exception as e:
        with _RELEV_LOCK:
            ctx["error"] = str(e)
    finally:
        with _RELEV_LOCK:
            ctx["done"] = True


@st.dialog("🤖 IAs utilizadas en Síntesis de Noticias", width="medium")
def dialog_uso_noticias():
    uso = st.session_state.get("noticias_uso", [])
    if not uso:
        st.info("Aún no hay operaciones con IA.")
        return

    ultimo = st.session_state.get("ultimo_exito_noticias")
    if ultimo and ultimo["operacion"] in _ETIQUETAS_OP:
        st.success(
            f"{_ETIQUETAS_OP[ultimo['operacion']]} generado con **{ultimo['proveedor']}**"
        )

    st.markdown("**Resumen de uso**")
    por_operacion = {}
    for ev in uso:
        por_operacion.setdefault(ev["operacion"], []).append(ev)

    for op, evs in por_operacion.items():
        st.markdown(f"**{_ETIQUETAS_OP.get(op, op)}**")
        exito: dict = {}
        fallos = []
        for ev in evs:
            if ev["ok"]:
                exito[ev["proveedor"]] = exito.get(ev["proveedor"], 0) + 1
            else:
                fallos.append(ev)
        if exito:
            st.markdown("- ✅ " + ", ".join(f"**{p}** ({n})" for p, n in exito.items()))
        for ev in fallos[-5:]:
            det = "sin key" if ev["detalle"] == "sin key" else (ev["detalle"][:50] if ev["detalle"] else "")
            st.markdown(f"- ⏭️ {ev['proveedor']} — {det}")
        st.divider()


# Abre automáticamente la ventana emergente tras generar un análisis o resumen
if st.session_state.get("mostrar_uso_noticias"):
    st.session_state.mostrar_uso_noticias = False
    dialog_uso_noticias()

# Filtros dinámicos
categorias_iniciales = list(CATEGORIAS_KEYWORDS.keys())
if "filtros_disponibles" not in st.session_state:
    st.session_state.filtros_disponibles = []
if "filtros_activos" not in st.session_state:
    st.session_state.filtros_activos = list(categorias_iniciales)


def crear_df_noticias(df_raw):
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    n = len(df_raw)
    df = pd.DataFrame({
        "ID": range(1, n + 1),
        "Seleccionado": [False] * n,
        "Orden": range(1, n + 1),
        "Título": df_raw["title"].values if "title" in df_raw.columns else "",
        "Resumen Ejecutivo": ["Resumen no disponible"] * n,
        "Fuente": df_raw["source_name"].values if "source_name" in df_raw.columns else "",
        "Categoría": df_raw["categoria"].values if "categoria" in df_raw.columns else "",
        "Verificación": ["Verificada" if c else "No verificada" for c in df_raw["confiable"].values],
        "Enfoque": ["Neutral"] * n,
        "Fecha": df_raw["fecha_display"].values if "fecha_display" in df_raw.columns else "",
        "Enlace_URL": df_raw["url"].values if "url" in df_raw.columns else "",
        "Relevancia_SHCP": [0] * n,
        "Razón_Relevancia": ["Pendiente de analizar"] * n,
        "Sentimiento": ["Sin clasificar"] * n,
        "Fecha_Ordenable": df_raw["fecha_procesada"].values if "fecha_procesada" in df_raw.columns else "",
    })
    return df


# =========================================================
# FILTROS Y BÚSQUEDA
# =========================================================
with st.expander("🏷️ Filtros activos", expanded=True):
    filtro_cols = st.columns(4)
    idx_col = 0
    for cat in list(st.session_state.filtros_activos):
        with filtro_cols[idx_col % 4]:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{cat}**")
            if c2.button("✕", key=f"rm_{cat}", help="Quitar"):
                st.session_state.filtros_activos.remove(cat)
                st.session_state.filtros_disponibles.append(cat)
                st.rerun()
        idx_col += 1

    if st.session_state.filtros_disponibles:
        with st.popover("+ Agregar filtro"):
            for cat in list(st.session_state.filtros_disponibles):
                if st.button(cat, key=f"add_{cat}"):
                    st.session_state.filtros_disponibles.remove(cat)
                    st.session_state.filtros_activos.append(cat)
                    st.rerun()

    nuevo_filtro = st.text_input(
        "Agregar palabra clave:", placeholder="Nuevo filtro...",
        label_visibility="collapsed",
    )
    if nuevo_filtro and nuevo_filtro not in st.session_state.filtros_activos and nuevo_filtro not in st.session_state.filtros_disponibles:
        st.session_state.filtros_disponibles.append(nuevo_filtro)
        st.rerun()

    categorias_sel = list(st.session_state.filtros_activos)

with st.expander("🔍 Opciones de búsqueda", expanded=True):
    solo_confiables = st.checkbox("Solo fuentes confiables", value=True)
    rango_fecha = st.selectbox(
        "Periodo de búsqueda:",
        ["Solo de hoy", "Hoy y ayer", "Hoy, ayer y antier"],
        help="Filtra por la fecha de publicación de las noticias.",
    )
    dias = {"Solo de hoy": 0, "Hoy y ayer": 1, "Hoy, ayer y antier": 2}[rango_fecha]
    num_noticias = st.number_input(
        "Número de noticias:", value=10, min_value=1, max_value=100
    )

with st.expander("🤖 IA y API keys", expanded=True):
    ia_actual = st.session_state.get("ai_news_provider", "Gemini (gratis)")
    if ia_actual not in CADENA_IA:
        ia_actual = "Gemini (gratis)"
    ia_primaria = st.selectbox(
        "IA principal:",
        CADENA_IA,
        index=CADENA_IA.index(ia_actual),
        help="Si la IA principal falla o no tiene key, se usa en cascada: "
        "Gemini → Anthropic → OpenRouter → Cerebras → Groq → Ollama.",
    )
    st.session_state.ai_news_provider = ia_primaria

    st.divider()
    st.markdown("**🔑 API keys de IA**")
    st.caption(
        "Se comparten con la página de la Mañanera. Keys gratuitas en "
        "aistudio.google.com, console.anthropic.com, console.groq.com, "
        "openrouter.ai y cerebras.ai/cloud."
    )
    _col_k1, _col_k2, _col_k3 = st.columns(3)
    with _col_k1:
        _gem = st.text_input(
            "Gemini (maestro):", type="password",
            value=st.session_state.get("api_key_gemini", ""),
            placeholder="AIza...",
        )
        if _gem != st.session_state.get("api_key_gemini", ""):
            st.session_state.api_key_gemini = _gem
        _anth = st.text_input(
            "Anthropic:", type="password",
            value=st.session_state.get("api_key_anthropic", ""),
            placeholder="sk-ant-...",
        )
        if _anth != st.session_state.get("api_key_anthropic", ""):
            st.session_state.api_key_anthropic = _anth
    with _col_k2:
        _groq = st.text_input(
            "Groq:", type="password",
            value=st.session_state.get("api_key_groq", ""),
            placeholder="gsk_...",
        )
        if _groq != st.session_state.get("api_key_groq", ""):
            st.session_state.api_key_groq = _groq
        _or = st.text_input(
            "OpenRouter:", type="password",
            value=st.session_state.get("api_key_openrouter", ""),
            placeholder="sk-or-...",
        )
        if _or != st.session_state.get("api_key_openrouter", ""):
            st.session_state.api_key_openrouter = _or
    with _col_k3:
        _cb = st.text_input(
            "Cerebras:", type="password",
            value=st.session_state.get("api_key_cerebras", ""),
            placeholder="csk-...",
        )
        if _cb != st.session_state.get("api_key_cerebras", ""):
            st.session_state.api_key_cerebras = _cb

# =========================================================
# BARRA DE ACCIONES PRINCIPAL
# =========================================================
col_buscar, col_analizar, col_pdf = st.columns(3)

with col_buscar:
    if st.button("🔍 Buscar noticias", type="primary", use_container_width=True):
        if not categorias_sel:
            st.warning("Selecciona al menos una categoría")
        else:
            with st.spinner("Buscando noticias..."):
                df = buscar_por_categorias(
                    categorias=categorias_sel,
                    solo_confiables=solo_confiables,
                    num_noticias=num_noticias,
                    dias=dias,
                )
                if df is not None and not df.empty:
                    st.session_state.noticias_df = crear_df_noticias(df)
                    registrar(_usuario, "sintesis_noticias", "buscar_noticias", detalle={
                        "categorias": categorias_sel, "num_noticias": num_noticias,
                        "solo_confiables": solo_confiables, "dias": dias,
                        "resultados": len(df),
                    })
                    st.toast(f"Se encontraron {len(df)} noticias", icon="📰")
                    st.rerun()
                else:
                    registrar(_usuario, "sintesis_noticias", "buscar_noticias", exito=False, detalle={
                        "categorias": categorias_sel, "num_noticias": num_noticias,
                    })
                    st.warning("No se encontraron noticias. Ajusta los filtros.")

df_actual = st.session_state.noticias_df
tiene_noticias = df_actual is not None and not df_actual.empty

with col_analizar:
    if tiene_noticias:
        if st.session_state.get("analizando_relevancia"):
            st.button("⏳ Analizando…", disabled=True, use_container_width=True)
        elif st.button("🔍 Analizar relevancia", use_container_width=True, key="btn_analizar_relevancia"):
            ctx = {
                "status": {}, "done": False, "cancel": False,
                "error": None, "uso": [], "df_json": "",
            }
            st.session_state.relevancia_ctx = ctx
            prov = st.session_state.get("ai_news_provider", "Gemini (gratis)")
            claves = _claves_ia()
            registros = df_actual.to_dict("records")
            thread = threading.Thread(
                target=_procesar_relevancia,
                args=(registros, prov, claves, ctx),
                daemon=True,
            )
            st.session_state.relevancia_thread = thread
            st.session_state.analizando_relevancia = True
            thread.start()
            st.rerun()

with col_pdf:
    if tiene_noticias:
        seleccionadas = [
            i for i in range(len(df_actual))
            if st.session_state.get(f"sel_{i}", False)
        ]
        if not seleccionadas:
            st.button("📄 Exportar PDF (selecciona noticias)", disabled=True, use_container_width=True)
        else:
            try:
                @st.cache_data
                def _pdf_sintesis(df_json: str, indices: tuple) -> bytes:
                    import pandas as _pd, tempfile, os, io
                    df = _pd.read_json(io.StringIO(df_json))
                    df_exp = df.iloc[list(indices)][[
                        "Título", "Resumen Ejecutivo", "Fuente",
                        "Categoría", "Enfoque", "Fecha", "Enlace_URL"
                    ]].copy()
                    df_exp["Enlace"] = df_exp["Enlace_URL"].apply(
                        lambda u: f'<a href="{u}" target="_blank">Ver</a>' if u else ""
                    )
                    df_exp = df_exp.drop(columns=["Enlace_URL"])
                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    tmp.close()
                    generar_pdf_sintesis(df_exp, tmp.name)
                    with open(tmp.name, "rb") as f:
                        data = f.read()
                    os.unlink(tmp.name)
                    return data

                descargado = st.download_button(
                    "📄 Exportar PDF",
                    data=_pdf_sintesis(
                        df_actual[[
                            "Título", "Resumen Ejecutivo", "Fuente", "Categoría",
                            "Enfoque", "Fecha", "Enlace_URL",
                        ]].astype(str).to_json(),
                        tuple(seleccionadas),
                    ),
                    file_name=f"sintesis_prensa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
                if descargado:
                    registrar(_usuario, "sintesis_noticias", "exportar_pdf", detalle={
                        "num_noticias": len(seleccionadas),
                    })
            except Exception as e:
                    registrar(_usuario, "sintesis_noticias", "exportar_pdf", exito=False, detalle={"error": str(e)})
                    st.error(f"Error al generar PDF: {e}")

# =========================================================
# AGREGAR REGISTRO MANUAL
# =========================================================
with st.expander("➕ Agregar registro manual"):
    with st.form("nuevo_registro", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nuevo_orden = st.number_input("Orden:", value=1, min_value=1)
            nuevo_titulo = st.text_input("Título:")
            nuevo_fuente = st.text_input("Fuente:")
            nuevo_categoria = st.selectbox("Categoría:", options=list(CATEGORIAS_KEYWORDS.keys()) + ["Otra"])
        with col2:
            nuevo_resumen = st.text_area("Resumen Ejecutivo:", height=100)
            nuevo_verificacion = st.selectbox("Verificación:", ["Verificada", "No verificada"])
            nuevo_enfoque = st.selectbox("Enfoque:", ["Positivo", "Neutral", "Negativo"])
            nuevo_fecha = st.date_input("Fecha:", value=datetime.now(TZ_MX).date())
            nuevo_enlace = st.text_input("Enlace:", placeholder="https://...")

        if st.form_submit_button("Guardar registro") and nuevo_titulo:
            nueva_fila = pd.DataFrame([{
                "ID": 0, "Seleccionado": False, "Orden": nuevo_orden,
                "Título": nuevo_titulo, "Resumen Ejecutivo": nuevo_resumen or "",
                "Fuente": nuevo_fuente or "", "Categoría": nuevo_categoria,
                "Verificación": nuevo_verificacion, "Enfoque": nuevo_enfoque,
                "Fecha": nuevo_fecha.strftime("%d/%m/%Y") if nuevo_fecha else "",
                "Enlace_URL": nuevo_enlace or "", "Relevancia_SHCP": 0,
                "Razón_Relevancia": "Pendiente de analizar", "Sentimiento": "Sin clasificar",
                "Fecha_Ordenable": nuevo_fecha,
            }])
            if st.session_state.noticias_df.empty:
                st.session_state.noticias_df = nueva_fila
            else:
                st.session_state.noticias_df = pd.concat(
                    [st.session_state.noticias_df, nueva_fila], ignore_index=True
                )
            df = st.session_state.noticias_df
            df["ID"] = range(1, len(df) + 1)
            df = df.sort_values("Orden").reset_index(drop=True)
            df["ID"] = range(1, len(df) + 1)
            st.session_state.noticias_df = df
            registrar(_usuario, "sintesis_noticias", "agregar_registro_manual", detalle={"titulo": nuevo_titulo})
            st.toast("Registro agregado", icon="✅")
            st.rerun()

# =========================================================
# ELIMINAR SELECCIONADAS
# =========================================================
st.markdown(
    """
    <style>
    div[class*="st-key-btn_eliminar_seleccionadas"] button {
        background-color: #dc3545;
        color: white;
        border: none;
    }
    div[class*="st-key-btn_eliminar_seleccionadas"] button:hover {
        background-color: #bb2d3b;
        color: white;
    }
    div[class*="st-key-btn_eliminar_seleccionadas"] button:active {
        background-color: #a02834;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
col_eliminar, _ = st.columns([1, 3])
with col_eliminar:
    if tiene_noticias:
        if st.button("🗑️ Eliminar seleccionadas", key="btn_eliminar_seleccionadas", use_container_width=True):
            seleccionadas = []
            for idx in range(len(df_actual)):
                if st.session_state.get(f"sel_{idx}", False):
                    seleccionadas.append(idx)
            if seleccionadas:
                df_actual = df_actual.drop(seleccionadas).reset_index(drop=True)
                df_actual["ID"] = range(1, len(df_actual) + 1)
                st.session_state.noticias_df = df_actual
                registrar(_usuario, "sintesis_noticias", "eliminar_seleccionadas", detalle={
                    "num_eliminadas": len(seleccionadas),
                })
                st.toast(f"Eliminadas {len(seleccionadas)} fila(s)", icon="🗑️")
                st.rerun()
            else:
                st.warning("Selecciona al menos un registro")

# =========================================================
# TABLA DE NOTICIAS
# =========================================================
if tiene_noticias:
    st.subheader(f"Resultados: {len(df_actual)} noticias")

    editando_idx = st.session_state.get("editando_idx", None)

    if editando_idx is not None and editando_idx < len(df_actual):
        fila = df_actual.iloc[editando_idx]
        st.subheader(f"Editando registro #{int(fila.get('ID', editando_idx+1))}")

        with st.form("form_edicion"):
            col1, col2 = st.columns(2)
            with col1:
                nuevo_orden = st.number_input("Orden:", value=int(fila.get("Orden", 1)), min_value=1)
                nuevo_titulo = st.text_input("Título:", value=fila.get("Título", ""))
                nuevo_fuente = st.text_input("Fuente:", value=fila.get("Fuente", ""))
                nuevo_categoria = st.selectbox(
                    "Categoría:", options=list(CATEGORIAS_KEYWORDS.keys()) + ["Otra"], index=0
                )
            with col2:
                nuevo_resumen = st.text_area("Resumen Ejecutivo:", value=fila.get("Resumen Ejecutivo", ""), height=100)
                nuevo_verificacion = st.selectbox(
                    "Verificación:", ["Verificada", "No verificada"],
                    index=0 if fila.get("Verificación") == "Verificada" else 1,
                )
                nuevo_enfoque = st.selectbox(
                    "Enfoque:", ["Positivo", "Neutral", "Negativo"],
                    index=["Positivo", "Neutral", "Negativo"].index(fila.get("Enfoque", "Neutral"))
                    if fila.get("Enfoque", "Neutral") in ["Positivo", "Neutral", "Negativo"] else 1,
                )
                nuevo_fecha = st.text_input("Fecha:", value=fila.get("Fecha", ""))

            col_guardar, col_cancelar = st.columns(2)
            with col_guardar:
                guardar = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)
            with col_cancelar:
                cancelar = st.form_submit_button("Cancelar", use_container_width=True)

            if guardar:
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Orden")] = nuevo_orden
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Título")] = nuevo_titulo
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Resumen Ejecutivo")] = nuevo_resumen
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Fuente")] = nuevo_fuente
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Categoría")] = nuevo_categoria
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Verificación")] = nuevo_verificacion
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Enfoque")] = nuevo_enfoque
                df_actual.iloc[editando_idx, df_actual.columns.get_loc("Fecha")] = nuevo_fecha
                if "Relevancia_SHCP" in df_actual.columns:
                    df_actual = df_actual.sort_values("Relevancia_SHCP", ascending=False).reset_index(drop=True)
                else:
                    df_actual = df_actual.sort_values("Orden").reset_index(drop=True)
                df_actual["ID"] = range(1, len(df_actual) + 1)
                st.session_state.noticias_df = df_actual
                st.session_state.editando_idx = None
                st.toast("Registro actualizado", icon="✅")
                st.rerun()

            if cancelar:
                st.session_state.editando_idx = None
                st.rerun()

    else:
        # Generar resumen de noticia
        generando_idx = st.session_state.get("generando_resumen_idx", None)
        if generando_idx is not None and generando_idx < len(df_actual):
            fila = df_actual.iloc[generando_idx]
            url = fila.get("Enlace_URL", "")
            titulo = fila.get("Título", "")
            fuente = fila.get("Fuente", "")
            st.subheader(f"Generando resumen: {titulo[:60]}...")
            with st.spinner("Leyendo la noticia (entra al enlace) y generando resumen..."):
                resultado, proveedor = ejecutar_cascada(
                    "generar_resumen_noticia",
                    st.session_state.get("ai_news_provider", "Gemini (gratis)"),
                    _claves_ia(),
                    _registrar_uso,
                    titulo, url, fuente,
                )
                if resultado is None:
                    registrar(_usuario, "sintesis_noticias", "generar_resumen_noticia", exito=False, detalle={"titulo": titulo})
                    st.error("Ninguna IA disponible. Revisa la configuración de API keys.")
                    st.session_state.generando_resumen_idx = None
                else:
                    df_actual.iloc[generando_idx, df_actual.columns.get_loc("Resumen Ejecutivo")] = resultado["resumen"]
                    df_actual.iloc[generando_idx, df_actual.columns.get_loc("Sentimiento")] = resultado["sentimiento"]
                    df_actual.iloc[generando_idx, df_actual.columns.get_loc("Enfoque")] = resultado["sentimiento"]
                    st.session_state.noticias_df = df_actual
                    st.session_state.generando_resumen_idx = None
                    registrar(_usuario, "sintesis_noticias", "generar_resumen_noticia", detalle={
                        "titulo": titulo, "proveedor": proveedor,
                    })
                    st.toast(f"Resumen generado con {proveedor}", icon="🤖")
                    st.rerun()

        # ANÁLISIS DE RELEVANCIA (en segundo plano, no se reinicia con el mouse)
        if st.session_state.get("analizando_relevancia"):
            ctx = st.session_state.get("relevancia_ctx")
            if ctx is None:
                st.session_state.analizando_relevancia = False
            else:
                st.info("🔍 Leyendo y analizando cada noticia. Puede tomar varios minutos.")
                st.caption(
                    "El análisis corre en segundo plano: puedes mover el cursor y "
                    "hacer clic en la página sin que se reinicie."
                )
                with _RELEV_LOCK:
                    status = dict(ctx.get("status") or {})
                    done = ctx.get("done")
                    error = ctx.get("error")
                    cancel = ctx.get("cancel")
                actual = int(status.get("actual", 0) or 0)
                total = int(status.get("total", 0) or 0)
                titulo = str(status.get("titulo", ""))

                if done:
                    with _RELEV_LOCK:
                        eventos = ctx.pop("uso", [])
                    for ev in eventos:
                        _registrar_uso(*ev)
                    if error:
                        st.error(f"Error durante el análisis: {error}")
                        registrar(_usuario, "sintesis_noticias", "analizar_relevancia", exito=False, detalle={"error": error})
                    else:
                        try:
                            st.session_state.noticias_df = pd.read_json(io.StringIO(ctx.get("df_json", "")))
                        except Exception as e:
                            st.error(f"No se pudo aplicar el análisis: {e}")
                        registrar(_usuario, "sintesis_noticias", "analizar_relevancia", detalle={"num_noticias": total})
                        if cancel:
                            st.warning("Análisis cancelado; se conservan los resultados parciales.")
                        else:
                            st.toast("Relevancia analizada y noticias ordenadas", icon="✅")
                    st.session_state.analizando_relevancia = False
                    st.session_state.relevancia_ctx = None
                    st.rerun()
                else:
                    st.progress(
                        min(float(actual / total), 1.0) if total else 0.0,
                        text=f"Analizando noticia {actual} de {total}: {titulo[:50]}..."
                    )
                    if st.button("❌ Cancelar", type="secondary", key="btn_cancelar_relevancia"):
                        with _RELEV_LOCK:
                            ctx["cancel"] = True
                        st.toast("Cancelando tras la noticia en curso…", icon="⚠️")
                    time.sleep(1.0)
                    st.rerun()

        # TABLA DE NOTICIAS
        for idx in range(len(df_actual)):
            row = df_actual.iloc[idx]
            with st.container():
                col_check, col_info, col_edit = st.columns([0.5, 4, 1])

                with col_check:
                    selected = st.checkbox(
                        f"Seleccionar: {row.get('Título', 'noticia sin título')}",
                        key=f"sel_{idx}",
                        label_visibility="collapsed",
                    )

                with col_info:
                    relevancia = row.get("Relevancia_SHCP", 0)
                    enfoque = row.get("Enfoque", "Neutral")
                    if enfoque == "Positivo":
                        emoji_enf = "🟢"
                        bg_enf = "#d4edda"
                    elif enfoque == "Negativo":
                        emoji_enf = "🔴"
                        bg_enf = "#ffcccc"
                    else:
                        emoji_enf = "⚪"
                        bg_enf = "#e9ecef"

                    if relevancia >= 8:
                        color_rel = "🔴"
                        bg_rel = "#ffcccc"
                    elif relevancia >= 5:
                        color_rel = "🟡"
                        bg_rel = "#fff3cd"
                    elif relevancia > 0:
                        color_rel = "🟢"
                        bg_rel = "#d4edda"
                    else:
                        color_rel = "⚪"
                        bg_rel = "#f8f9fa"

                    st.markdown(f"**#{int(row.get('ID', idx+1))}** | **{row.get('Título', '')}**")
                    st.markdown(
                        f"📌 {row.get('Categoría', '')} | 📰 {row.get('Fuente', '')} | "
                        f"✅ {row.get('Verificación', '')} | 📅 {row.get('Fecha', '')}"
                    )
                    st.markdown(
                        f"""
                        <div style='display:inline-block; padding:4px 12px; border-radius:8px;
                                    background:{bg_rel}; margin:2px 0; font-weight:bold; font-size:14px;'>
                            {color_rel} Relevancia SHCP: <b>{relevancia}/10</b>
                        </div>
                        &nbsp;&nbsp;
                        <div style='display:inline-block; padding:4px 12px; border-radius:8px;
                                    background:{bg_enf}; margin:2px 0; font-size:14px;'>
                            {emoji_enf} Enfoque: <b>{enfoque}</b>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if row.get("Razón_Relevancia", "") and row.get("Razón_Relevancia") != "Pendiente de analizar":
                        st.caption(f"💡 {row.get('Razón_Relevancia', '')}")
                    st.caption(f"Resumen: {row.get('Resumen Ejecutivo', 'No disponible')[:100]}...")
                    url = row.get("Enlace_URL", "")
                    if url and isinstance(url, str) and url.startswith("http"):
                        st.markdown(f"[🔗 Abrir noticia]({url})")

                with col_edit:
                    if st.button("✏️ Editar", key=f"edit_{idx}", use_container_width=True):
                        st.session_state.editando_idx = idx
                        st.rerun()
                    if st.button("📰 Generar resumen", key=f"resumen_{idx}", use_container_width=True):
                        st.session_state.generando_resumen_idx = idx
                        st.rerun()

                st.divider()

        # =========================================================
        # EXPANSORES (Fuentes)
        # =========================================================
        with st.expander("📰 Fuentes confiables"):
            for f in FUENTES_CONFIABLES:
                st.markdown(f"- {f}")

else:
    st.info("Usa los filtros y haz clic en 'Buscar noticias' para comenzar.")

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
