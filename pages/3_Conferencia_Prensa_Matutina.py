"""
Página de Resumen de la Conferencia de Prensa Matutina y Análisis de notas.
"""
import os
import re
import json
import time
import threading

import streamlit as st
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import urllib.parse

try:
    from curl_cffi import requests as _cffi_requests
except Exception:
    _cffi_requests = None

from config import COPYRIGHT, CONTACTO_EMAILS
from utils.styles import get_header_html
from utils.pdf_generator import generar_pdf_conferencia
from services.resumen_mananera import procesar_conferencia, procesar_informe, procesar_notas
from utils.auth import require_auth
from utils.date_helpers import TZ_MX
from utils.audit_log import registrar

require_auth()
_usuario = st.session_state.get("username")

_HEADERS_GOB = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# Algunos medios (p. ej. La Jornada con Cloudflare) bloquean unas
# impersonaciones TLS pero permiten otras: se rotan ante un 403.
_IMPERSONACIONES = ["chrome", "safari15_5", "firefox133"]


def _get_gob(url: str, params=None, timeout: int = 20):
    ultimo = None
    if _cffi_requests is not None:
        for i, imp in enumerate(_IMPERSONACIONES):
            if i > 0:
                time.sleep(2)
            try:
                resp = _cffi_requests.get(
                    url, params=params, headers=_HEADERS_GOB,
                    timeout=timeout, impersonate=imp,
                )
                if resp.status_code == 403 and imp != _IMPERSONACIONES[-1]:
                    ultimo = resp
                    continue
                return resp
            except Exception as e:
                ultimo = e
                continue
        if isinstance(ultimo, Exception):
            raise ultimo
        return ultimo
    return requests.get(url, params=params, headers=_HEADERS_GOB, timeout=timeout)


def _ensure_encoding(resp) -> None:
    if hasattr(resp, "apparent_encoding"):
        resp.encoding = resp.apparent_encoding


def _extraer_jsonld(soup: BeautifulSoup) -> str:
    """Texto del artículo desde <script type='application/ld+json'> (articleBody)."""
    mejor = ""
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except Exception:
            continue
        pila = data if isinstance(data, list) else [data]
        for it in pila:
            if not isinstance(it, dict):
                continue
            grafo = it.get("@graph")
            if isinstance(grafo, list):
                pila.extend([g for g in grafo if isinstance(g, dict)])
            cuerpo = it.get("articleBody") or ""
            if isinstance(cuerpo, str) and len(cuerpo) > len(mejor):
                mejor = cuerpo
    return mejor.strip()


def _extraer_articlebody_regex(html: str) -> str:
    """Texto desde JSON incrustado tipo \"articleBody\":\"...\" (p. ej. El País)."""
    mejor = ""
    dec = json.JSONDecoder()
    for m in re.finditer(r'"articleBody"\s*:\s*"', html):
        try:
            val, _ = dec.raw_decode(html[m.end() - 1:])
            if isinstance(val, str) and len(val) > len(mejor):
                mejor = val
        except Exception:
            continue
    return mejor.strip()


def _extraer_texto_de_url(url: str) -> str:
    """Extrae texto de una URL cualquiera (gob.mx, notas de prensa, etc.)."""
    try:
        resp = _get_gob(url, timeout=30)
        estado = getattr(resp, "status_code", 200) or 200
        if estado in (401, 403, 404, 410):
            return (
                f"Error al leer la URL: el sitio respondió HTTP {estado} "
                "(acceso denegado o nota no encontrada)."
            )
        _ensure_encoding(resp)
        html = resp.text or ""
        if "Just a moment" in html[:5000] and "cloudflare" in html[:5000].lower():
            return (
                "Error al leer la URL: el sitio mostró un desafío anti-bots "
                "(Cloudflare) y bloqueó la lectura automática."
            )
        soup = BeautifulSoup(html, "html.parser")

        # Título + descripción como encabezado del texto
        encabezado = ""
        if soup.title and soup.title.string:
            encabezado = soup.title.string.strip() + "\n"
        desc = ""
        for m in soup.find_all("meta"):
            if m.get("name") == "description" or m.get("property") == "og:description":
                desc = (m.get("content") or "").strip()
                if desc:
                    break
        if desc:
            encabezado += desc + "\n"

        candidatos = []
        ld = _extraer_jsonld(soup)
        if len(ld) > 200:
            candidatos.append(ld)
        ab = _extraer_articlebody_regex(html)
        if len(ab) > 200:
            candidatos.append(ab)

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        for selector in ["div.article-body", "div.col-md-7", "article", "main", "div.content"]:
            contenedor = soup.select_one(selector)
            if contenedor:
                t = contenedor.get_text(separator="\n", strip=True)
                if len(t) > 200:
                    candidatos.append(t)
                    break

        # Respaldo: párrafos largos (densidad de texto)
        paras = [
            p.get_text(separator=" ", strip=True)
            for p in soup.find_all("p")
        ]
        paras = [p for p in paras if len(p) > 40]
        if paras:
            candidatos.append("\n".join(paras))

        if not candidatos:
            candidatos.append(soup.get_text(separator="\n", strip=True))

        texto = max(candidatos, key=len)
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        texto = "\n".join(lineas)[:200000]
        if encabezado:
            texto = encabezado + "\n" + texto
        return texto
    except Exception as e:
        return f"Error al leer la URL: {e}"


def _extraer_nota(url: str) -> dict:
    """Extrae título y texto de una nota periodística a partir de su URL."""
    try:
        resp = _get_gob(url, timeout=30)
        _ensure_encoding(resp)
        soup = BeautifulSoup(resp.text, "html.parser")

        titulo = ""
        if soup.title and soup.title.string:
            titulo = soup.title.string.strip()
        if not titulo:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                titulo = og["content"].strip()

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        texto = ""
        for selector in ["div.article-body", "div.col-md-7", "article", "main", "div.content"]:
            contenedor = soup.select_one(selector)
            if contenedor:
                texto = contenedor.get_text(separator="\n", strip=True)
                break
        if not texto:
            texto = soup.get_text(separator="\n", strip=True)

        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        texto_limpio = "\n".join(lineas)[:200000]
        return {"titulo": titulo or url, "url": url, "texto": texto_limpio, "error": None}
    except Exception as e:
        return {"titulo": url, "url": url, "texto": "", "error": str(e)}


# =========================================================
# HEADER
# =========================================================
st.markdown(get_header_html("CONFERENCIA DE PRENSA / ANÁLISIS DE NOTAS"), unsafe_allow_html=True)

# =========================================================
# SESSION STATE
# =========================================================
if "conferencia_resumen" not in st.session_state:
    st.session_state.conferencia_resumen = ""
if "conferencia_fecha" not in st.session_state:
    st.session_state.conferencia_fecha = None
if "conferencia_uso" not in st.session_state:
    st.session_state.conferencia_uso = None
if "conferencia_pdf_titulo" not in st.session_state:
    st.session_state.conferencia_pdf_titulo = ""
if "conferencia_pdf_link" not in st.session_state:
    st.session_state.conferencia_pdf_link = ""
if "api_key_anthropic" not in st.session_state:
    st.session_state.api_key_anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
if "api_key_gemini" not in st.session_state:
    st.session_state.api_key_gemini = os.environ.get("GEMINI_API_KEY", "")
if "api_key_groq" not in st.session_state:
    st.session_state.api_key_groq = os.environ.get("GROQ_API_KEY", "")
if "api_key_groq_2" not in st.session_state:
    st.session_state.api_key_groq_2 = os.environ.get("GROQ_API_KEY_2", "")
if "api_key_groq_3" not in st.session_state:
    st.session_state.api_key_groq_3 = os.environ.get("GROQ_API_KEY_3", "")
if "api_key_groq_4" not in st.session_state:
    st.session_state.api_key_groq_4 = os.environ.get("GROQ_API_KEY_4", "")
if "api_key_groq_5" not in st.session_state:
    st.session_state.api_key_groq_5 = os.environ.get("GROQ_API_KEY_5", "")
if "api_key_groq_6" not in st.session_state:
    st.session_state.api_key_groq_6 = os.environ.get("GROQ_API_KEY_6", "")
if "api_key_groq_7" not in st.session_state:
    st.session_state.api_key_groq_7 = os.environ.get("GROQ_API_KEY_7", "")
if "api_key_openrouter" not in st.session_state:
    st.session_state.api_key_openrouter = os.environ.get("OPENROUTER_API_KEY", "")
if "api_key_openrouter_2" not in st.session_state:
    st.session_state.api_key_openrouter_2 = os.environ.get("OPENROUTER_API_KEY_2", "")
if "api_key_openrouter_3" not in st.session_state:
    st.session_state.api_key_openrouter_3 = os.environ.get("OPENROUTER_API_KEY_3", "")
if "api_key_gemini_2" not in st.session_state:
    st.session_state.api_key_gemini_2 = os.environ.get("GEMINI_API_KEY_2", "")
if "api_key_gemini_3" not in st.session_state:
    st.session_state.api_key_gemini_3 = os.environ.get("GEMINI_API_KEY_3", "")
if "ai_provider" not in st.session_state:
    st.session_state.ai_provider = "Gemini (gratis)"
if "ai_block_providers" not in st.session_state:
    st.session_state.ai_block_providers = ["Groq", "OpenRouter", "Gemini (gratis)"]
if "ai_master_provider" not in st.session_state:
    st.session_state.ai_master_provider = "Groq"
if "resumen_bg_ctx" not in st.session_state:
    st.session_state.resumen_bg_ctx = None
if "generando_resumen_bg" not in st.session_state:
    st.session_state.generando_resumen_bg = False
if "conferencia_texto" not in st.session_state:
    st.session_state.conferencia_texto = ""
if "conferencia_texto_titulo" not in st.session_state:
    st.session_state.conferencia_texto_titulo = ""
if "conferencia_texto_ver" not in st.session_state:
    st.session_state.conferencia_texto_ver = 0
if "_pdf_link_pendiente" not in st.session_state:
    st.session_state._pdf_link_pendiente = ""

# Lock para el contexto de generación en segundo plano: el hilo de trabajo
# SOLO toca este dict (nunca st.session_state), así un rerun disparado por
# cualquier interacción del usuario (mover el mouse, tocar un widget) no
# cancela la generación en curso — solo se sondea su progreso.
_RESUMEN_LOCK = threading.Lock()


@st.cache_data
def _pdf_bytes(resumen_md: str, titulo_personalizado: str = "", link_fuente: str = "") -> bytes:
    import tempfile
    import os
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    generar_pdf_conferencia(
        resumen=resumen_md,
        output_path=tmp.name,
        titulo_personalizado=titulo_personalizado,
        link_fuente=link_fuente,
    )
    with open(tmp.name, "rb") as f:
        data = f.read()
    os.unlink(tmp.name)
    return data


def _build_keys() -> dict:
    return {
        "groq": st.session_state.get("api_key_groq", ""),
        "groq_2": st.session_state.get("api_key_groq_2", ""),
        "groq_3": st.session_state.get("api_key_groq_3", ""),
        "groq_4": st.session_state.get("api_key_groq_4", ""),
        "groq_5": st.session_state.get("api_key_groq_5", ""),
        "groq_6": st.session_state.get("api_key_groq_6", ""),
        "groq_7": st.session_state.get("api_key_groq_7", ""),
        "openrouter": st.session_state.get("api_key_openrouter", ""),
        "openrouter_2": st.session_state.get("api_key_openrouter_2", ""),
        "openrouter_3": st.session_state.get("api_key_openrouter_3", ""),
        "gemini": st.session_state.get("api_key_gemini", ""),
        "gemini_2": st.session_state.get("api_key_gemini_2", ""),
        "gemini_3": st.session_state.get("api_key_gemini_3", ""),
        "anthropic": st.session_state.get("api_key_anthropic", ""),
    }


def _get_block_providers() -> list:
    return st.session_state.get("ai_block_providers") or ["Groq"]


# =========================================================
# FUNCIONES MAÑANERA
# =========================================================
def buscar_version_estenografica(fecha: datetime) -> str:
    meses_es = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }
    dia = fecha.day
    mes = meses_es[fecha.month]
    anio = fecha.year
    slug_buscar = f"{dia:02d}-de-{mes}-de-{anio}"
    url_base = "https://www.gob.mx/presidencia/es/archivo/articulos"

    for page in range(1, 6):
        try:
            resp = _get_gob(url_base, params={"page": page}, timeout=15)
            _ensure_encoding(resp)
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"].strip('\\"')
                if "version-estenografica" in href and slug_buscar in href:
                    url_articulo = f"https://www.gob.mx{href}" if href.startswith("/") else href
                    return _extraer_texto_de_url(url_articulo)
        except Exception as e:
            return f"Error al buscar: {e}"
    return f"No se encontró la versión estenográfica para {fecha.strftime('%d/%m/%Y')}."


def _iniciar_resumen_bg(fn, texto: str, fecha_dt: datetime, keys: dict, block_providers: list, master_provider: str, meta: dict):
    """Lanza la generación del resumen ejecutivo en un hilo daemon.

    El hilo NUNCA toca st.session_state (solo el dict `ctx`, protegido por
    lock), así la generación sobrevive a cualquier rerun que dispare la UI
    mientras corre (mover el mouse, tocar otro widget). El script principal
    solo sondea `ctx` y refresca la barra de progreso.
    """
    ctx = {
        "pct": 0, "resumen": None, "error": None,
        "uso_eventos": [], "done": False, "meta": meta, "fecha": fecha_dt,
    }

    def _run():
        def on_progress(pct):
            with _RESUMEN_LOCK:
                ctx["pct"] = pct

        def on_uso(fase, proveedor, ok, detalle=""):
            with _RESUMEN_LOCK:
                ctx["uso_eventos"].append({"fase": fase, "proveedor": proveedor, "ok": bool(ok), "detalle": detalle or ""})

        try:
            resumen = fn(
                texto=texto, fecha=fecha_dt,
                block_providers=block_providers, master_provider=master_provider,
                keys=keys, on_progress=on_progress, on_uso=on_uso,
            )
            with _RESUMEN_LOCK:
                ctx["resumen"] = resumen
        except Exception as e:
            with _RESUMEN_LOCK:
                ctx["error"] = str(e)
        finally:
            with _RESUMEN_LOCK:
                ctx["done"] = True

    thread = threading.Thread(target=_run, daemon=True)
    st.session_state.resumen_bg_ctx = ctx
    st.session_state.resumen_bg_thread = thread
    st.session_state.generando_resumen_bg = True
    thread.start()


def construir_uso(eventos: list, fecha: datetime) -> dict:
    bloques: dict = {}
    intentos: list = []
    maestro_usado = None
    for ev in eventos:
        if ev["fase"] == "bloque":
            bloques[ev["proveedor"]] = bloques.get(ev["proveedor"], 0) + 1
        else:
            intentos.append(ev)
            if ev["ok"]:
                maestro_usado = ev["proveedor"]
    return {"fecha": fecha.strftime("%d/%m/%Y"), "bloques": bloques, "intentos": intentos, "maestro_usado": maestro_usado}


@st.dialog("🤖 IAs utilizadas para este resumen", width="medium")
def dialog_uso():
    uso = st.session_state.get("conferencia_uso")
    if not uso:
        st.info("Aún no hay resumen generado.")
        return
    if uso.get("fecha"):
        st.caption(f"Resumen del {uso['fecha']}")
    st.markdown("**🧩 Resumen de bloques**")
    bloques = uso.get("bloques") or {}
    if bloques:
        for prov, n in bloques.items():
            st.markdown(f"- **{n}** bloque(s) con **{prov}**")
    else:
        st.markdown("- Ningún bloque completado")
    st.divider()
    st.markdown("**🥇 Resumen maestro**")
    usado = uso.get("maestro_usado")
    if usado:
        st.success(f"Se usó **{usado}** para el resumen final")
    else:
        st.warning("Ninguna IA maestra tuvo éxito")
    intentos = uso.get("intentos") or []
    if intentos:
        with st.expander("🪜 Intentos en cascada", expanded=True):
            for ev in intentos:
                prov = ev["proveedor"]
                if ev["ok"]:
                    st.markdown(f"- ✅ **{prov}** — resumen generado")
                elif ev["detalle"] == "sin key":
                    st.markdown(f"- ⏭️ {prov} — sin key (se omitió)")
                else:
                    st.markdown(f"- ❌ {prov} — {ev['detalle'][:90]}")


# =========================================================
# POLLING DEL RESUMEN EN SEGUNDO PLANO
# =========================================================
def _snapshot_ctx() -> dict:
    """Copia thread-safe del ctx de la generación en background."""
    ctx = st.session_state.get("resumen_bg_ctx")
    if not ctx:
        return {}
    with _RESUMEN_LOCK:
        return {
            "pct": ctx["pct"],
            "done": ctx["done"],
            "error": ctx["error"],
            "resumen": ctx["resumen"],
            "uso_eventos": list(ctx["uso_eventos"]),
            "meta": dict(ctx.get("meta") or {}),
        }


@st.fragment(run_every="2s")
def panel_progreso_resumen():
    """Muestra el avance del hilo y recoge el resultado cuando termina."""
    snap = _snapshot_ctx()
    if not snap:
        return

    if not snap["done"]:
        pct = max(0, min(int(snap["pct"]), 100))
        st.progress(pct, text=f"Generando resumen ejecutivo... {pct}%")
        st.caption("Puedes seguir interactuando con la página; la generación no se cancela.")
        return

    meta = snap["meta"]
    modulo = meta.get("modulo", "mananera")
    accion = meta.get("accion", "generar_resumen")
    resumen = snap["resumen"]
    fecha_dt = st.session_state.get("conferencia_fecha")

    st.session_state.generando_resumen_bg = False
    st.session_state.resumen_bg_ctx = None
    st.session_state.resumen_bg_thread = None

    if snap["error"]:
        st.error(snap["error"])
        registrar(_usuario, modulo, accion, exito=False,
                  detalle={"motivo": "excepcion_hilo", "error": snap["error"][:200]})
        return

    if not resumen or resumen.startswith("Error:"):
        st.session_state.conferencia_resumen = ""
        st.error(resumen or "La generación no devolvió ningún resultado.")
        registrar(_usuario, modulo, accion, exito=False,
                  detalle={"motivo": "fallo_generacion_ia"})
        return

    st.session_state.conferencia_resumen = resumen
    if fecha_dt:
        st.session_state.conferencia_uso = construir_uso(snap["uso_eventos"], fecha_dt)
    st.session_state._pdf_link_pendiente = meta.get("link", "") or ""
    registrar(_usuario, modulo, accion, detalle={
        "maestro_usado": (st.session_state.conferencia_uso or {}).get("maestro_usado"),
    })
    st.rerun(scope="app")


# =========================================================
# CONFIGURACIÓN DE IA (compartida)
# =========================================================
with st.expander("⚙️ Configuración de IA", expanded=False):
    st.caption(
        "Pipeline map-reduce: el texto se divide en bloques que se resumen "
        "en paralelo usando MÚLTIPLES IAs (round-robin), y después una IA maestra "
        "consolida el Resumen Ejecutivo Final."
    )
    col_bloque, col_maestro = st.columns(2)
    with col_bloque:
        st.markdown("**1. IAs para bloques (paralelo)**")
        block_opts = ["Groq", "OpenRouter", "Cerebras", "Gemini (gratis)", "Ollama (local)"]
        st.multiselect(
            "Bloques:", block_opts,
            key="ai_block_providers",
            label_visibility="collapsed",
        )
    with col_maestro:
        st.markdown("**2. IA para resumen maestro**")
        st.radio(
            "Maestro:",
            ["Gemini (gratis)", "Anthropic Claude", "Groq", "OpenRouter", "Cerebras", "Ollama (local)"],
            key="ai_master_provider",
            label_visibility="collapsed",
        )

    st.divider()
    st.markdown("**🔑 API keys**")
    st.caption("Cada key adicional = un bloque más en paralelo. Múltiples keys del mismo provider se rotan en round-robin (máx 2 llamadas simultáneas por provider).")
    col_gemini, col_groq, col_openrouter = st.columns(3)
    with col_gemini:
        st.markdown("**Gemini**")
        v = st.text_input("Gemini #1:", type="password", value=st.session_state.api_key_gemini, placeholder="AIza/AQ...")
        if v != st.session_state.api_key_gemini: st.session_state.api_key_gemini = v
        v = st.text_input("Gemini #2:", type="password", value=st.session_state.api_key_gemini_2, placeholder="AQ...")
        if v != st.session_state.api_key_gemini_2: st.session_state.api_key_gemini_2 = v
        v = st.text_input("Gemini #3:", type="password", value=st.session_state.api_key_gemini_3, placeholder="AQ...")
        if v != st.session_state.api_key_gemini_3: st.session_state.api_key_gemini_3 = v
    with col_groq:
        st.markdown("**Groq**")
        v = st.text_input("Groq #1:", type="password", value=st.session_state.api_key_groq, placeholder="gsk_...")
        if v != st.session_state.api_key_groq: st.session_state.api_key_groq = v
        v = st.text_input("Groq #2:", type="password", value=st.session_state.api_key_groq_2, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_2: st.session_state.api_key_groq_2 = v
        v = st.text_input("Groq #3:", type="password", value=st.session_state.api_key_groq_3, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_3: st.session_state.api_key_groq_3 = v
        v = st.text_input("Groq #4:", type="password", value=st.session_state.api_key_groq_4, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_4: st.session_state.api_key_groq_4 = v
        v = st.text_input("Groq #5:", type="password", value=st.session_state.api_key_groq_5, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_5: st.session_state.api_key_groq_5 = v
        v = st.text_input("Groq #6:", type="password", value=st.session_state.api_key_groq_6, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_6: st.session_state.api_key_groq_6 = v
        v = st.text_input("Groq #7:", type="password", value=st.session_state.api_key_groq_7, placeholder="gsk_...")
        if v != st.session_state.api_key_groq_7: st.session_state.api_key_groq_7 = v
    with col_openrouter:
        st.markdown("**OpenRouter**")
        v = st.text_input("OpenRouter #1:", type="password", value=st.session_state.api_key_openrouter, placeholder="sk-or-...")
        if v != st.session_state.api_key_openrouter: st.session_state.api_key_openrouter = v
        v = st.text_input("OpenRouter #2:", type="password", value=st.session_state.api_key_openrouter_2, placeholder="sk-or-...")
        if v != st.session_state.api_key_openrouter_2: st.session_state.api_key_openrouter_2 = v
        v = st.text_input("OpenRouter #3:", type="password", value=st.session_state.api_key_openrouter_3, placeholder="sk-or-...")
        if v != st.session_state.api_key_openrouter_3: st.session_state.api_key_openrouter_3 = v
    n_keys = sum(1 for k in [
        st.session_state.api_key_groq, st.session_state.api_key_groq_2, st.session_state.api_key_groq_3,
        st.session_state.api_key_groq_4, st.session_state.api_key_groq_5,
        st.session_state.api_key_groq_6, st.session_state.api_key_groq_7,
        st.session_state.api_key_openrouter, st.session_state.api_key_openrouter_2, st.session_state.api_key_openrouter_3,
        st.session_state.api_key_gemini, st.session_state.api_key_gemini_2, st.session_state.api_key_gemini_3,
    ] if k)
    if n_keys:
        st.success(f"**{n_keys} keys activas** — hasta {min(n_keys, 6)} bloques en paralelo.")


# =========================================================
# SELECTOR: MAÑANERA O ANÁLISIS DE NOTAS
# =========================================================
st.subheader("🎙️ Selecciona el tipo de resumen")
modo = st.radio(
    "¿Qué deseas resumir?",

    ["Conferencia de Prensa Matutina (Mañanera)", "Análisis de notas"],

    horizontal=True,
    label_visibility="collapsed",
)

_titulo_pdf_default = (
    "CONFERENCIA DE PRENSA MATUTINA (MAÑANERA)"
    if modo == "Conferencia de Prensa Matutina (Mañanera)"
    else "ANÁLISIS DE NOTAS"
)
if st.session_state.get("_modo_pdf_prev", "") != modo:
    st.session_state.conferencia_pdf_titulo = _titulo_pdf_default
    st.session_state._modo_pdf_prev = modo


# =========================================================
# MODO: MAÑANERA
# =========================================================
if modo == "Conferencia de Prensa Matutina (Mañanera)":
    st.markdown("### 📅 Conferencia de Prensa Matutina (Mañanera)")
    st.caption("Resumen ejecutivo desde la versión estenográfica oficial de gob.mx.")

    col_fecha, col_buscar = st.columns([3, 1])
    with col_fecha:
        fecha_input = st.date_input(
            "Selecciona la fecha:",
            value=datetime.now(TZ_MX).date(),
            max_value=datetime.now(TZ_MX).date(),
            format="DD/MM/YYYY",
        )
    with col_buscar:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.session_state.get("generando_resumen_bg"):
            st.button("⏳ Generando…", disabled=True, use_container_width=True, key="btn_mananera_disabled")
            buscar = False
        else:
            buscar = st.button("🔍 Buscar y resumir", type="primary", use_container_width=True)

    if buscar:
        fecha_dt = datetime.combine(fecha_input, datetime.min.time())
        st.session_state.conferencia_fecha = fecha_dt

        with st.spinner("Buscando versión estenográfica en gob.mx..."):
            texto = buscar_version_estenografica(fecha_dt)

        if texto.startswith("No se encontró") or texto.startswith("Error"):
            registrar(_usuario, "mananera", "buscar_y_resumir", exito=False, detalle={
                "fecha": fecha_dt.strftime("%d/%m/%Y"), "motivo": "version_no_encontrada",
            })
            st.error(texto)
            st.info("Puedes intentar en: https://www.gob.mx/presidencia/es/archivo/articulos")
        else:
            st.session_state.conferencia_texto = texto
            st.session_state.conferencia_texto_titulo = "📄 Ver versión estenográfica completa"
            st.session_state.conferencia_texto_ver += 1

            _iniciar_resumen_bg(
                procesar_conferencia, texto, fecha_dt,
                _build_keys(), _get_block_providers(), st.session_state.get("ai_master_provider", "Groq"),
                meta={
                    "modulo": "mananera", "accion": "buscar_y_resumir", "link": "",
                    "detalle": {"fecha": fecha_dt.strftime("%d/%m/%Y")},
                },
            )
            st.rerun()


# =========================================================
# MODO: ANÁLISIS DE NOTAS
# =========================================================
elif modo == "Análisis de notas":
    st.markdown("### 📋 Análisis de notas")
    st.caption("Pega la URL de la nota y genera un resumen ejecutivo estructurado.")

    col_url, col_gen = st.columns([4, 1])
    with col_url:
        url_informe = st.text_input(
            "URL de la nota:",
            placeholder="https://www.ejemplo.com/noticia/...",
            key="url_informe",
        )
    with col_gen:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.session_state.get("generando_resumen_bg"):
            st.button("⏳ Generando…", disabled=True, use_container_width=True, key="btn_informe_disabled")
            generar = False
        else:
            generar = st.button("🤖 Generar resumen", type="primary", use_container_width=True, key="btn_informe")

    if generar:
        if not url_informe or not url_informe.strip():
            st.warning("Ingresa una URL válida de la nota.")
        else:
            fecha_dt = datetime.combine(datetime.now(TZ_MX).date(), datetime.min.time())
            st.session_state.conferencia_fecha = fecha_dt

            with st.spinner("Extrayendo contenido de la nota..."):
                texto = _extraer_texto_de_url(url_informe.strip())

            if texto.startswith("Error"):
                st.error(texto)
            elif len(texto) < 200:
                st.error("No se pudo extraer contenido suficiente de la URL. Verifica que el enlace sea válido y accesible.")
            else:
                st.session_state.conferencia_texto = texto
                st.session_state.conferencia_texto_titulo = "📄 Ver texto extraído de la nota"
                st.session_state.conferencia_texto_ver += 1

                _iniciar_resumen_bg(
                    procesar_notas, texto, fecha_dt,
                    _build_keys(), _get_block_providers(), st.session_state.get("ai_master_provider", "Groq"),
                    meta={
                        "modulo": "analisis_notas", "accion": "generar_resumen",
                        "link": url_informe.strip(),
                        "detalle": {"url": url_informe.strip()},
                    },
                )
                st.rerun()


# =========================================================
# TEXTO FUENTE + PROGRESO (sobreviven al rerun)
# =========================================================
if st.session_state.conferencia_texto:
    with st.expander(st.session_state.conferencia_texto_titulo, expanded=False):
        st.text_area(
            "Texto completo:", st.session_state.conferencia_texto,
            height=300, key=f"txt_fuente_{st.session_state.conferencia_texto_ver}",
            disabled=True,
        )

if st.session_state.get("generando_resumen_bg"):
    panel_progreso_resumen()


# =========================================================
# MOSTRAR RESUMEN (común a ambos modos)
# =========================================================
if st.session_state.conferencia_resumen:
    fecha_display = st.session_state.conferencia_fecha
    fecha_para_archivo = fecha_display.strftime("%Y%m%d") if fecha_display else "sin_fecha"
    fecha_str = fecha_display.strftime("%d/%m/%Y") if fecha_display else ""

    st.divider()
    st.subheader("📝 Resumen Ejecutivo Generado")

    with st.expander("✏️ Editar resumen", expanded=False):
        texto_editado = st.text_area(
            "Resumen ejecutivo (puedes modificarlo antes de descargar; escribe [[LINK]] donde quieras el link):",
            value=st.session_state.conferencia_resumen,
            height=400,
            key="editor_resumen",
        )
        if texto_editado != st.session_state.conferencia_resumen:
            st.session_state.conferencia_resumen = texto_editado
            st.rerun()

    col_vista, col_ias = st.columns([3, 1])
    with col_vista:
        st.subheader("Vista previa")
    with col_ias:
        if st.button("🤖 Ver IAs usadas", use_container_width=True):
            dialog_uso()
    st.markdown(st.session_state.conferencia_resumen)

    titulo_pdf = st.text_input(
        "Título para el encabezado del PDF:",
        key="conferencia_pdf_titulo",
        help="Solo aparece en el encabezado de cada página del PDF (debajo de UNIDAD DE POLÍTICA Y ESTRATEGÍA PARA RESULTADOS / COORDINACIÓN DE FORTALECIMIENTO INSTITUCIONAL). No se muestra en el cuerpo del documento.",
    )

    if st.session_state._pdf_link_pendiente:
        st.session_state.conferencia_pdf_link = st.session_state._pdf_link_pendiente
        st.session_state._pdf_link_pendiente = ""

    link_nota = st.text_input(
        "Link de la nota (opcional):",
        key="conferencia_pdf_link",
        placeholder="https://...",
        help="Escribe [[LINK]] en el resumen, en el lugar donde quieras que aparezca la palabra 'Link' (clicable) en el PDF. Si lo dejas vacío no aparece nada.",
    )
    st.caption(
        "💡 Para colocar el link donde quieras: escribe `[[LINK]]` en el texto del resumen "
        "(puedes hacerlo en ✏️ Editar resumen), por ejemplo: `Fuente: [[LINK]]`. "
        "En el PDF ese marcador se convierte en la palabra **Link** que abre la URL de arriba."
    )
    if st.button("➕ Insertar `[[LINK]]` al final del resumen", use_container_width=False):
        if "[[LINK]]" not in st.session_state.conferencia_resumen:
            st.session_state.conferencia_resumen += "\n\nFuente: [[LINK]]"
            st.session_state.editor_resumen = st.session_state.conferencia_resumen
            st.rerun()
        else:
            st.toast("El marcador [[LINK]] ya está en el resumen.")
    titulo_efectivo = (titulo_pdf or "").strip() or _titulo_pdf_default
    link_efectivo = (link_nota or "").strip()

    _hay_marcador = bool(re.search(
        r"\[\[LINK\]\]|\[LINK\]|\{\{LINK\}\}",
        st.session_state.conferencia_resumen or "",
        re.IGNORECASE,
    ))
    if _hay_marcador and not link_efectivo:
        st.warning(
            "⚠️ Escribiste `[[LINK]]` en el resumen pero el campo "
            "**Link de la nota** está vacío: en el PDF no aparecerá nada. "
            "Captura la URL arriba."
        )
    elif link_efectivo and not _hay_marcador:
        st.info(
            "ℹ️ Capturaste una URL pero no hay `[[LINK]]` en el texto: "
            "el link no aparecerá en el PDF. Escríbelo donde quieras que salga "
            "o usa el botón ➕ de abajo."
        )
    elif _hay_marcador and link_efectivo:
        st.success("✅ El PDF mostrará la palabra **Link** (clicable) donde pusiste `[[LINK]]`.")

    col_pdf, col_txt, col_limpiar = st.columns(3)
    with col_pdf:
        try:
            descargado_pdf = st.download_button(
                "📄 Exportar PDF",
                data=_pdf_bytes(st.session_state.conferencia_resumen, titulo_efectivo, link_efectivo),
                file_name=f"resumen_{fecha_para_archivo}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
            if descargado_pdf:
                registrar(_usuario, "mananera", "exportar_pdf", detalle={"fecha": fecha_str})
        except Exception as e:
            st.error(f"Error al generar PDF: {e}")
    with col_txt:
        descargado_txt = st.download_button(
            "📥 Descargar TXT",
            data=st.session_state.conferencia_resumen,
            file_name=f"resumen_{fecha_para_archivo}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        if descargado_txt:
            registrar(_usuario, "mananera", "descargar_txt", detalle={"fecha": fecha_str})
    with col_limpiar:
        if st.button("🗑️ Limpiar resultado", use_container_width=True):
            st.session_state.conferencia_resumen = ""
            st.session_state.conferencia_fecha = None
            st.session_state.conferencia_uso = None
            st.session_state.conferencia_texto = ""
            st.session_state.conferencia_texto_titulo = ""
            st.session_state._pdf_link_pendiente = ""
            st.rerun()

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.markdown(
    f"""
    <div class="footer-main">
        <strong>{COPYRIGHT}</strong><br>
        {CONTACTO_EMAILS}
    </div>
    """,
    unsafe_allow_html=True,
)
