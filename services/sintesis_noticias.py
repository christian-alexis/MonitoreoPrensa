"""
Servicio de Síntesis de Noticias.
Scraping de Google News RSS con fuentes confiables mexicanas.
"""
from typing import Optional
import re
from datetime import timedelta

import pandas as pd

from config import (
    CATEGORIAS_KEYWORDS,
    FUENTES_CONFIABLES,
    GOOGLE_NEWS_PARAMS,
    GOOGLE_NEWS_RSS_URL,
    USER_AGENT,
)
from utils.html_helpers import parse_xml, parse_html
from utils.date_helpers import (
    parsear_fecha,
    extraer_fecha_de_url,
    formatear_fecha_dmy,
    hoy_mx,
)


def es_fuente_confiable(fuente: str) -> bool:
    """Verifica si una fuente está en la lista de fuentes confiables."""
    if not fuente:
        return False
    fuente_lower = fuente.lower()
    return any(f.lower() in fuente_lower for f in FUENTES_CONFIABLES)


def decodificar_url_gn(url_gn: str) -> str:
    """
    Decodifica una URL real desde un ID base64 de Google News RSS.
    Solo intenta el método offline (rápido); los URLs nuevos se decodifican
    después, de forma perezosa, al leer el artículo (ver ai/news_agent.py).
    """
    if not url_gn or "news.google.com" not in url_gn:
        return url_gn

    from utils.google_news import decodificar_google_news
    return decodificar_google_news(url_gn, online=False)


ANEXOS_TRANSVERSALES_KW = ("anexo transversal", "anexos transversales")


def _limpiar_termino(p: str) -> str:
    """Limpia un término de búsqueda: quita '+' y otros símbolos que Google News
    RSS no sabe interpretar (ej. 'LGBTI+' regresa 0 items, 'LGBTI' funciona)."""
    return " ".join(p.replace("+", " ").split())


def construir_query(palabras: list[str]) -> str:
    """Construye una query tipo Google News con OR.

    Los términos se unen SIN comillas: Google exige que cada palabra aparezca
    (AND implícito por término) pero no exige que sea la frase exacta. Esto es
    clave para términos como "Anexo 33 PEF": buscado como frase exacta devuelve
    0 resultados, mientras que suelto encuentra notas reales.
    """
    parts = []
    for p in palabras:
        p = _limpiar_termino(p)
        if not p:
            continue
        parts.append(p)
    return " OR ".join(parts)


MAX_BUSQUEDA_FALLBACK = 4


def _buscar_rss(q: str) -> list:
    """Consulta Google News RSS y devuelve la lista de <item>.

    Sin reintentos cuando la respuesta es 200 pero vacía: Google responde 0
    items de forma determinista para queries con 3+ frases OR, y reintentar no
    sirve. Solo se reintenta ante errores de conexión / HTTP.
    """
    import time as _time
    import requests as req

    params = {
        "q": q,
        "hl": "es-419",
        "gl": "MX",
        "ceid": "MX:es",
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/xml",
    }
    for intento in range(3):
        try:
            resp = req.get(GOOGLE_NEWS_RSS_URL, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                soup = parse_xml(resp.text)
                return soup.find_all("item") if soup else []
        except Exception as e:
            print(f"Error al consultar Google News RSS (intento {intento + 1}): {e}")
        _time.sleep(2 * (intento + 1))
    return []


def obtener_noticias_confiables(
    query: str,
    solo_confiables: bool = True,
    dias: int = 7,
) -> Optional[pd.DataFrame]:
    """
    Busca noticias en Google News RSS.
    Retorna un DataFrame con columnas:
        title, url, publishedAt, source_name, confiable, fecha_procesada, categoria

    dias: ventana de días hacia atrás (0 = solo hoy, 1 = hoy y ayer, etc.)
    """
    try:
        palabras = [p.strip() for p in query.split(",") if p.strip()]
        if not palabras:
            palabras = [query]

        # Intento 1: una sola consulta con OR (rápida). Google News RSS regresa 0
        # items cuando el OR integra 3+ frases de varias palabras.
        items = _buscar_rss(construir_query(palabras))
        if not items:
            # Intento 2: una consulta POR palabra clave y unión de resultados.
            vistos = set()
            for kw_raw in palabras[:MAX_BUSQUEDA_FALLBACK]:
                kw = _limpiar_termino(kw_raw)
                if not kw or kw in vistos:
                    continue
                vistos.add(kw)
                nuevos = _buscar_rss(kw)
                if nuevos:
                    items.extend(nuevos)

        if not items:
            return None

        rows = []
        for item in items:
            titulo_raw = item.find("title")
            titulo_raw = titulo_raw.get_text(strip=True) if titulo_raw else ""

            enlace_gn = item.find("link")
            enlace_gn = enlace_gn.get_text(strip=True) if enlace_gn else ""

            fecha = item.find("pubDate")
            fecha = fecha.get_text(strip=True) if fecha else ""

            fuente = item.find("source")
            fuente = fuente.get_text(strip=True) if fuente else ""

            # Limpiar título: remover " - Nombre Fuente" del final
            titulo = titulo_raw
            if fuente:
                suffix = f" - {fuente}"
                if titulo.endswith(suffix):
                    titulo = titulo[: -len(suffix)].strip()

            # Intentar obtener enlace original desde description
            desc_tag = item.find("description")
            desc_raw = desc_tag.get_text(strip=True) if desc_tag else ""
            enlace_final = enlace_gn

            if desc_raw:
                desc_soup = parse_html(f"<div>{desc_raw}</div>")
                if desc_soup:
                    a_tags = desc_soup.find_all("a", href=True)
                    hrefs_ext = [
                        a["href"] for a in a_tags
                        if "news.google.com" not in a["href"]
                    ]
                    if hrefs_ext:
                        enlace_final = hrefs_ext[0]

            # Si sigue siendo URL de Google News, decodificar
            if "news.google.com" in enlace_final:
                enlace_final = decodificar_url_gn(enlace_final)

            confiable = es_fuente_confiable(fuente)

            # Detección de Anexos Transversales (presupuesto etiquetado por tema)
            texto_deteccion = f"{titulo} {desc_raw}".lower()
            es_anexo_transversal = any(k in texto_deteccion for k in ANEXOS_TRANSVERSALES_KW)

            rows.append({
                "title": titulo,
                "url": enlace_final,
                "publishedAt": fecha,
                "source_name": fuente,
                "confiable": confiable,
                "es_anexo_transversal": es_anexo_transversal,
            })

        if not rows:
            return None

        df = pd.DataFrame(rows)

        if solo_confiables:
            df = df[df["confiable"] == True]
            if df.empty:
                return None

        # Procesar fechas
        df["fecha_url"] = df["url"].apply(
            lambda u: extraer_fecha_de_url(u)
        )
        df["fecha_pub"] = df["publishedAt"].apply(
            lambda f: parsear_fecha(f, return_date=True)
        )
        df["fecha_procesada"] = df["fecha_pub"]
        mask_url = df["fecha_url"].notna()
        df.loc[mask_url, "fecha_procesada"] = df.loc[mask_url, "fecha_url"]

        # Filtrar noticias por ventana de días (0 = solo hoy)
        hoy = hoy_mx().date()
        desde = hoy - timedelta(days=dias)
        df = df[
            df["fecha_procesada"].notna() &
            (df["fecha_procesada"] >= desde)
        ]

        if df.empty:
            return None

        # Deduplicar y ordenar
        df = df.drop_duplicates(subset=["title", "url"])
        df = df.sort_values("fecha_procesada", ascending=False).reset_index(drop=True)

        return df

    except Exception as e:
        print(f"Error al obtener noticias: {e}")
        return None


def buscar_por_categorias(
    categorias: list[str],
    solo_confiables: bool = True,
    num_noticias: int = 10,
    dias: int = 7,
    progress_callback=None,
) -> pd.DataFrame:
    """
    Busca noticias para múltiples categorías.
    Retorna un DataFrame combinado y filtrado.
    """
    all_results = []
    n_cats = len(categorias)

    for i, cat_nombre in enumerate(categorias):
        if progress_callback:
            progress_callback(i / n_cats, f"Buscando categoría {i+1} de {n_cats}...")

        keywords = CATEGORIAS_KEYWORDS.get(cat_nombre, [])
        if not keywords:
            keywords = [cat_nombre]

        query = ", ".join(keywords)
        df_cat = obtener_noticias_confiables(
            query, solo_confiables=solo_confiables, dias=dias
        )

        if df_cat is not None and not df_cat.empty:
            df_cat["categoria"] = cat_nombre
            if "es_anexo_transversal" in df_cat.columns:
                es_anexo = df_cat["es_anexo_transversal"].fillna(False).astype(bool)
                df_cat.loc[es_anexo, "categoria"] = "Anexos transversales"
            all_results.append(df_cat)

    if progress_callback:
        progress_callback(1.0, "Procesando resultados...")

    if not all_results:
        return pd.DataFrame()

    df_combined = pd.concat(all_results, ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=["title", "url"])
    df_combined = df_combined.sort_values("fecha_procesada", ascending=False)

    # Limitar al número deseado
    df_combined = df_combined.head(num_noticias).reset_index(drop=True)

    # Agregar columnas para la UI
    df_combined["fecha_display"] = df_combined["fecha_procesada"].apply(formatear_fecha_dmy)
    df_combined["verificacion"] = df_combined["confiable"].apply(
        lambda c: "Verificada" if c else "No verificada"
    )
    df_combined["enfoque"] = "Positivo"
    df_combined["resumen"] = "Resumen no disponible"

    return df_combined
