"""
Servicio de Cartones del Día.
Scraping de cartones editoriales de múltiples fuentes mexicanas.
"""
from typing import Optional
import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import pandas as pd

from config import SOURCES_CFG, TIMEZONE_MX
from utils.http_helpers import safe_get, safe_head
from utils.html_helpers import (
    fetch_page,
    get_best_image,
    get_og_title,
    get_fallback_image,
    get_meta_content,
    extract_links,
    extract_date_from_html,
    extract_datetime_eluniversal,
)
from utils.date_helpers import parsear_fecha, TZ_MX


def make_id(url: str) -> str:
    """Genera un ID único basado en la URL."""
    return "c_" + hashlib.md5(url.encode()).hexdigest()[:12]


def read_cartoon_from_url(source: str, url: str, fecha_override=None) -> Optional[dict]:
    """
    Lee la metadata de un cartón desde su URL.
    Retorna un dict con: id, fuente, titulo, fecha, url, img
    """
    soup = fetch_page(url)
    if soup is None:
        return None

    # Imagen (prefiere la versión completa, no recortada por el CDN)
    img = get_best_image(soup, url)
    if not img:
        img = get_fallback_image(soup, url)

    # Título
    ttl = get_og_title(soup)
    if source == "El Sol de México":
        # og:title es genérico ("Cartones políticos - El Sol de México");
        # el título real del cartón está en el h1.
        h1 = soup.find("h1")
        ttl = h1.get_text(strip=True) if h1 else (ttl or "(sin título)")
    if not ttl:
        title_tag = soup.find("title")
        ttl = title_tag.get_text(strip=True) if title_tag else "(sin título)"

    # Fecha
    published = (
        get_meta_content(soup, prop="article:published_time")
        or get_meta_content(soup, prop="og:updated_time")
        or get_meta_content(soup, name="date")
    )

    # Fallbacks específicos por fuente
    if source == "Milenio" and not published:
        published = extract_date_from_html(soup)
    if source == "El Universal" and not published:
        published = extract_datetime_eluniversal(soup)

    fecha = fecha_override or _fecha_desde_url_imagen(img) or parsear_fecha(published)

    return {
        "id": make_id(url),
        "fuente": source,
        "titulo": ttl,
        "fecha": fecha,
        "url": url,
        "img": img,
    }


def _fecha_desde_url_imagen(img: Optional[str]):
    """
    Extrae la fecha de publicación desde la URL de la imagen, que es
    inequívoca (a diferencia de fechas DD/MM vs MM/DD del HTML):
      - Milenio:  /uploads/media/YYYY/MM/DD/...
      - Vanguardia: ..._YYYYMMDDHHMMSS.ext
    Retorna datetime tz-aware en zona MX, o None.
    """
    if not img or not isinstance(img, str):
        return None

    m = re.search(r"/uploads/media/(\d{4})/(\d{2})/(\d{2})/", img)
    if m:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ_MX
        )

    m = re.search(r"_(\d{4})(\d{2})(\d{2})", img)
    if m:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ_MX
        )

    # El Sol de México: la imagen lleva /img/<id>/<unix_ts>/...
    m = re.search(r"/img/[^/]+/(\d{10})/", img)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), tz=TZ_MX)

    return None


def process_source_eluniversal(cfg: dict, verbose: bool = False) -> list[dict]:
    """
    El Universal: la fecha real del cartón está en el listado
    (span .cartoon-list__date con formato DD/MM/YYYY), no en la
    página del cartón. Extrae (url, fecha) del listado y la imagen
    de la página del artículo.
    """
    items = []
    soup = fetch_page(cfg["list_url"])
    if soup is None:
        return items

    seen = set()
    for container in soup.select(".cartoon-list__data-container"):
        title_a = container.select_one(".cartoon-list__title a[href]")
        date_span = container.select_one(".cartoon-list__date")
        if title_a is None or date_span is None:
            continue
        href = urljoin(cfg["list_url"], title_a["href"])
        if not re.search(cfg["must_contain"], href):
            continue
        if href in seen:
            continue
        seen.add(href)

        fecha = None
        ds = date_span.get_text(strip=True)
        try:
            fecha = datetime.strptime(ds, "%d/%m/%Y").replace(tzinfo=TZ_MX)
        except ValueError:
            fecha = parsear_fecha(ds)
        cartoon = read_cartoon_from_url(cfg["fuente"], href, fecha_override=fecha)
        if cartoon:
            items.append(cartoon)
        if len(items) >= 60:
            break

    if verbose:
        print(f"[{cfg['fuente']}] items leídos: {len(items)}")

    return items


def process_source(cfg: dict, verbose: bool = False) -> list[dict]:
    """
    Procesa una fuente completa: extrae links y lee cada cartón.
    Retorna lista de dicts con metadata de cartones.
    """
    try:
        if cfg["fuente"] == "El Universal":
            return process_source_eluniversal(cfg, verbose=verbose)

        links = extract_links(
            list_url=cfg["list_url"],
            must_contain=cfg["must_contain"],
            exclude_exact=cfg.get("exclude_exact"),
        )
        links = links[:60]  # Limitar

        if verbose:
            print(f"[{cfg['fuente']}] links candidatos: {len(links)}")

        items = []
        for link in links:
            cartoon = read_cartoon_from_url(cfg["fuente"], link)
            if cartoon:
                items.append(cartoon)

        if verbose:
            print(f"[{cfg['fuente']}] items leídos: {len(items)}")

        return items
    except Exception as e:
        if verbose:
            print(f"[{cfg['fuente']}] ERROR: {e}")
        return []


def build_candidates(
    all_items: list[dict],
    lookback_days: int = 1,
    target_n: int = 20,
    buffer: int = 8,
) -> pd.DataFrame:
    """
    Construye candidatos para validación de imágenes.
    Aplica cuotas por fuente y filtrado por fecha.
    """
    if not all_items:
        return pd.DataFrame()

    df = pd.DataFrame(all_items)

    # Filtrar por fecha
    cutoff = datetime.now(TZ_MX).date() - timedelta(days=lookback_days)
    if "fecha" in df.columns:
        df["fecha_date"] = df["fecha"].apply(
            lambda x: x.date() if isinstance(x, datetime) else x
        )
        df = df[df["fecha_date"].notna() & (df["fecha_date"] >= cutoff)]

    # Filtrar por imagen válida
    df = df[df["img"].notna() & (df["img"] != "")]

    if df.empty:
        return df

    # Ordenar por fuente y fecha
    df = df.sort_values(["fuente", "fecha"], ascending=[True, False])

    # Deduplicar por imagen
    df = df.drop_duplicates(subset=["img"], keep="first")

    # Asignar cuotas por fuente
    fuentes = df["fuente"].unique()
    n_fuentes = len(fuentes)
    base = target_n // n_fuentes if n_fuentes > 0 else target_n
    rem = target_n % n_fuentes if n_fuentes > 0 else 0

    quotas = {}
    for i, f in enumerate(fuentes):
        quotas[f] = base + (1 if i < rem else 0)

    # Seleccionar candidatos con buffer
    selected = []
    for fuente, grupo in df.groupby("fuente"):
        quota = quotas.get(fuente, 0) + buffer
        selected.append(grupo.head(quota))

    if not selected:
        return pd.DataFrame()

    result = pd.concat(selected, ignore_index=True)
    result = result.sort_values(
        ["fuente", "fecha"], ascending=[True, False]
    ).reset_index(drop=True)

    return result


def validate_images(candidates: pd.DataFrame, progress_callback=None) -> dict[str, bool]:
    """
    Valida que las imágenes de los candidatos sean accesibles.
    Retorna un dict {url: bool}.
    """
    img_ok = {}
    total = len(candidates)

    for i, (_, row) in enumerate(candidates.iterrows()):
        img_url = row.get("img", "")
        if not img_url:
            img_ok[img_url] = False
            continue

        ok, _ = safe_head(img_url)
        img_ok[img_url] = ok

        if progress_callback:
            progress_callback(i / total, f"Validando imagen {i+1} de {total}...")

    if progress_callback:
        progress_callback(1.0, "Validación completa")

    return img_ok


def final_select_by_quota(
    candidates: pd.DataFrame,
    target_n: int,
    img_ok_map: dict[str, bool],
) -> pd.DataFrame:
    """
    Selección final con distribución por cuotas por fuente.
    Solo incluye imágenes validadas.
    """
    if candidates.empty:
        return candidates

    # Filtrar solo imágenes válidas
    candidates = candidates.copy()
    candidates["img_ok"] = candidates["img"].map(lambda x: img_ok_map.get(x, False))
    valid = candidates[candidates["img_ok"] == True].copy()

    if valid.empty:
        return valid

    # Cuotas por fuente
    fuentes = valid["fuente"].unique()
    n_fuentes = len(fuentes)
    base = target_n // n_fuentes if n_fuentes > 0 else target_n
    rem = target_n % n_fuentes if n_fuentes > 0 else 0

    quotas = {}
    for i, f in enumerate(fuentes):
        quotas[f] = base + (1 if i < rem else 0)

    # Seleccionar por cuota
    picked = []
    for fuente, grupo in valid.groupby("fuente"):
        quota = quotas.get(fuente, 0)
        selected = grupo.sort_values("fecha", ascending=False).head(quota)
        picked.append(selected)

    if not picked:
        return pd.DataFrame()

    result = pd.concat(picked, ignore_index=True)

    # Si faltan, agregar extras
    faltan = target_n - len(result)
    if faltan > 0:
        extras = valid[~valid["id"].isin(result["id"])]
        extras = extras.sort_values(
            ["fuente", "fecha"], ascending=[True, False]
        )
        result = pd.concat([result, extras.head(faltan)], ignore_index=True)

    # Ordenar final
    result = result.sort_values(
        ["fuente", "fecha"], ascending=[True, False]
    ).head(target_n)

    return result.reset_index(drop=True)


def fetch_all_cartones(
    lookback_days: int = 1,
    target_n: int = 20,
    verbose: bool = False,
    progress_callback=None,
) -> tuple[pd.DataFrame, list[dict], dict]:
    """
    Función principal: ejecuta todo el pipeline de cartones.
    Retorna:
        - df_final: DataFrame con los cartones seleccionados
        - all_items: lista de todos los items crudos
        - source_status: dict con estado de cada fuente
    """
    source_status = {}
    all_items = []

    fuentes_cfg = SOURCES_CFG
    total_fuentes = len(fuentes_cfg)

    # Fase 1: Scraping de fuentes
    for i, cfg in enumerate(fuentes_cfg):
        fuente = cfg["fuente"]
        if progress_callback:
            progress_callback(
                i / total_fuentes,
                f"Procesando {fuente} ({i+1}/{total_fuentes})...",
            )

        source_status[fuente] = {"status": "Procesando", "count": 0}

        items = process_source(cfg, verbose=verbose)
        all_items.extend(items)

        if items:
            source_status[fuente] = {"status": "OK", "count": len(items)}
        else:
            source_status[fuente] = {"status": "Error", "count": 0}

    # Fase 2: Construir candidatos
    if progress_callback:
        progress_callback(0.7, "Construyendo candidatos...")

    candidates = build_candidates(
        all_items,
        lookback_days=lookback_days,
        target_n=target_n,
        buffer=8,
    )

    if candidates.empty:
        return pd.DataFrame(), all_items, source_status

    # Fase 3: Validar imágenes
    if progress_callback:
        progress_callback(0.75, "Validando imágenes...")

    img_ok_map = validate_images(
        candidates,
        progress_callback=lambda p, m: progress_callback(
            0.75 + 0.2 * p, m
        ) if progress_callback else None,
    )

    # Fase 4: Selección final
    if progress_callback:
        progress_callback(0.95, "Selección final...")

    df_final = final_select_by_quota(candidates, target_n, img_ok_map)

    if progress_callback:
        progress_callback(1.0, "Completado")

    return df_final, all_items, source_status
