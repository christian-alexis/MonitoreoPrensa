"""
Funciones auxiliares para parsing de HTML y XML.
"""
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from utils.http_helpers import safe_get


def parse_html(text: str) -> Optional[BeautifulSoup]:
    """Parsea texto HTML y retorna un BeautifulSoup object."""
    if not text or not text.strip():
        return None
    return BeautifulSoup(text, "lxml")


def parse_xml(text: str) -> Optional[BeautifulSoup]:
    """Parsea texto XML (RSS) y retorna un BeautifulSoup object."""
    if not text or not text.strip():
        return None
    return BeautifulSoup(text, "lxml-xml")


def fetch_page(url: str, timeout: int = 20) -> Optional[BeautifulSoup]:
    """Descarga y parsea una página HTML."""
    resp = safe_get(url, timeout=timeout)
    if resp is None:
        return None
    return parse_html(resp.text)


def get_meta_content(soup: BeautifulSoup, prop: str = None, name: str = None) -> Optional[str]:
    """
    Obtiene el contenido de una meta tag por property o name.
    """
    if soup is None:
        return None
    tag = None
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
    elif name:
        tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def get_og_image(soup: BeautifulSoup, base_url: str = "") -> Optional[str]:
    """Obtiene la imagen og:image de una página."""
    img = get_meta_content(soup, prop="og:image")
    if img and base_url:
        img = urljoin(base_url, img)
    return img


def get_best_image(soup: BeautifulSoup, base_url: str = "") -> Optional[str]:
    """
    Obtiene la mejor imagen disponible.

    Vanguardia/El Universal sirven en og:image una versión YA RECORTADA por su
    CDN (URL binrepository con recorte tipo /0cNNN/ o con entrega forzada tipo
    /1200d1200/ que recorta el ancho a un formato cuadrado/4:3). Las URLs
    binrepository tienen el patrón /binrepository/{WxH}/{crop}/{delivery}/...

    Preferencia:
    1. Variantes con delivery "0d0": se entrega el original sin recorte de
       aspecto (imagen completa). Se prefiere la de mayor área y sin
       pre-recorte vertical (/0c0/).
    2. Sin variante completa: /0c0/ con mayor área (sin recorte vertical).
    3. og:image como respaldo.
    """
    if soup is None:
        return None

    import re

    # Arc Publishing (El Universal): el cartón completo está en la imagen del
    # cuerpo del artículo (img.story__img), NO en og:image, que es una versión
    # recortada (ej. 1200x740 horizontal).
    story = soup.select_one("img.story__img") or soup.select_one("picture.story__pic img")
    if story is not None:
        src = story.get("src") or story.get("data-src")
        if src:
            src = urljoin(base_url, src)
            # Quitar parámetros de recorte del resizer (smart=true, width, height)
            src = re.sub(r"[&?](smart=true|width=\d+|height=\d+)", "", src)
            src = src.replace("&&", "&").rstrip("&?")
            return src

    html_str = str(soup)
    base = base_url or ""

    # Todas las URLs binrepository presentes en el HTML
    urls = set(re.findall("https?://[^\"'\\s<>]+?binrepository[^\"'\\s<>]+", html_str))
    for tag in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            src = tag.get(attr)
            if src and "binrepository" in src:
                urls.add(urljoin(base, src))
    meta = get_og_image(soup, base)
    if meta:
        urls.add(meta)

    def _parts(u: str):
        """Retorna (dim, crop, delivery, area) o None si no es imagen binrepository."""
        seg = u.split("/")
        if "binrepository" not in seg:
            return None
        idx = seg.index("binrepository")
        if len(seg) <= idx + 3:
            return None
        dim = seg[idx + 1]
        crop = seg[idx + 2]
        delivery = seg[idx + 3]
        m = re.match(r"^(\d+)x(\d+)$", dim)
        area = int(m.group(1)) * int(m.group(2)) if m else 0
        return dim, crop, delivery, area

    parsed = [(u, p) for u in urls if (p := _parts(u)) is not None]

    # 1) Entrega 0d0 = original completo, sin recorte de aspecto
    full = [p for p in parsed if p[1][2] == "0d0"]
    full_ok = [p for p in full if p[1][3] >= 60000]  # descartar miniaturas diminutas
    if full_ok:
        return max(full_ok, key=lambda p: (p[1][1] == "0c0", p[1][3]))[0]

    # 2) Sin variante completa: /0c0/ con mayor área
    no_crop = [p for p in parsed if p[1][1] == "0c0"]
    if no_crop:
        return max(no_crop, key=lambda p: p[1][3])[0]

    if meta:
        return meta

    return get_fallback_image(soup, base)


def get_og_title(soup: BeautifulSoup) -> Optional[str]:
    """Obtiene el título og:title de una página."""
    return get_meta_content(soup, prop="og:title")


def get_fallback_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """
    Busca una imagen alternativa si no hay og:image.
    Excluye logos, iconos, avatares, ads.
    """
    if soup is None:
        return None

    # Intentar twitter:image primero
    tw_img = get_meta_content(soup, name="twitter:image")
    if tw_img:
        return urljoin(base_url, tw_img)

    # Buscar en tags <img>
    imgs = soup.find_all("img")
    exclude_pattern = "logo|sprite|icon|avatar|ads|doubleclick|pixel"
    import re
    for img_tag in imgs:
        src = img_tag.get("src", "")
        if not src or src.startswith("data:"):
            continue
        src = urljoin(base_url, src)
        if not re.search(exclude_pattern, src, re.IGNORECASE):
            return src

    return None


def extract_links(
    list_url: str,
    must_contain: str,
    exclude_exact: Optional[str] = None,
) -> list[str]:
    """
    Extrae enlaces de una página que coinciden con el patrón must_contain.
    Filtra redes sociales, mailto, javascript, etc.
    """
    import re

    soup = fetch_page(list_url)
    if soup is None:
        return []

    # Extraer todos los hrefs
    a_tags = soup.find_all("a", href=True)
    hrefs = list({a["href"].strip() for a in a_tags if a["href"].strip()})

    # Convertir a URLs absolutas y limpiar
    absolute = []
    for h in hrefs:
        if h in ("#", "/") or h.startswith("mailto:") or h.startswith("javascript:"):
            continue
        # Remover query strings y fragments
        h_clean = re.sub(r'\?.*$', '', h)
        h_clean = re.sub(r'#.*$', '', h_clean)
        if not h_clean.startswith("http"):
            h_clean = urljoin(list_url, h_clean)
        absolute.append(h_clean)

    # Filtrar por must_contain
    absolute = [u for u in absolute if re.search(must_contain, u)]

    # Excluir exacto
    if exclude_exact:
        absolute = [u for u in absolute if u != exclude_exact]

    # Filtrar redes sociales y otros
    social_pattern = r"facebook|twitter|x\.com|whatsapp|instagram|ads|doubleclick|mailto:|javascript:"
    absolute = [u for u in absolute if not re.search(social_pattern, u, re.IGNORECASE)]

    return list(dict.fromkeys(absolute))  # unique, preservando orden


def extract_date_from_html(soup: BeautifulSoup) -> Optional[str]:
    """Extrae una fecha en formato DD/MM/YYYY del HTML como fallback."""
    if soup is None:
        return None
    import re
    text = str(soup)
    matches = re.findall(r'\b\d{2}[./-]\d{2}[./-]\d{4}\b', text)
    matches = list(dict.fromkeys(matches))
    return matches[0] if matches else None


def extract_datetime_eluniversal(soup: BeautifulSoup) -> Optional[str]:
    """Extrae fecha/hora específica de El Universal."""
    if soup is None:
        return None

    # Intentar tag <time datetime="...">
    time_tags = soup.find_all("time", attrs={"datetime": True})
    if time_tags:
        return time_tags[0]["datetime"].strip()

    import re
    text = str(soup)

    # Intentar DD/MM/YYYY HH:MM
    matches = re.findall(r'\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\b', text)
    matches = list(dict.fromkeys(matches))
    if matches:
        return matches[0]

    # Solo fecha
    matches = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', text)
    matches = list(dict.fromkeys(matches))
    return matches[0] if matches else None
