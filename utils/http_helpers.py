"""
Funciones auxiliares para peticiones HTTP.
"""
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import USER_AGENT


def create_session() -> requests.Session:
    """Crea una sesión con reintentos automáticos."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Charset": "utf-8,iso-8859-1;q=0.8,*;q=0.1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _fix_encoding(resp: requests.Response) -> None:
    """Corrige el encoding de la respuesta para soporte UTF-8 correcto."""
    if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "windows-1252", "latin-1"):
        # Estos encodings son incorrectos para contenido español
        # Usar apparent_encoding que detecta el encoding real del contenido
        resp.encoding = resp.apparent_encoding or "utf-8"


def safe_get(url: str, timeout: int = 20, extra_headers: Optional[dict] = None) -> Optional[requests.Response]:
    """
    Realiza un GET seguro con headers y timeout.
    Retorna None si hay error.
    """
    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return None
        _fix_encoding(resp)
        return resp
    except requests.RequestException:
        return None


def safe_head(url: str, timeout: int = 12) -> tuple:
    """
    Realiza un HEAD request para verificar si un recurso es accesible.
    Retorna (es_accesible, content_type).
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        resp = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        ct = resp.headers.get("content-type", "")
        if resp.status_code < 400 and "image/" in ct.lower():
            return True, ct
    except requests.RequestException:
        pass

    # Fallback: intentar GET con rango limitado
    try:
        headers["Range"] = "bytes=0-20480"
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
        ct = resp.headers.get("content-type", "")
        if resp.status_code < 400 and "image/" in ct.lower():
            return True, ct
    except requests.RequestException:
        pass

    return False, ""


def get_text(url: str, timeout: int = 20, encoding: str = "UTF-8") -> Optional[str]:
    """
    Obtiene el contenido de texto de una URL.
    Retorna None si hay error.
    """
    resp = safe_get(url, timeout=timeout)
    if resp is None:
        return None
    text = resp.text
    if not text or not text.strip():
        return None
    return text
