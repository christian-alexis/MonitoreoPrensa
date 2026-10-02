"""
Decodifica URLs de redirect de Google News (news.google.com/rss/articles/...)
a la URL real del artículo.

Los URLs modernos (julio 2024+) usan un ID opaco que no se puede decodificar
offline; se resuelve con el método "batchexecute" de Google (2 peticiones).
Requiere curl_cffi para imitar el fingerprint TLS de un navegador real y
evitar el bloqueo por bot-detection.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Optional
from urllib.parse import quote, urlparse

try:
    from curl_cffi import requests as _cffi_requests
except Exception:  # pragma: no cover - dependencia opcional
    _cffi_requests = None

_PAGE_URL_TEMPLATES = (
    "https://news.google.com/articles/{}",
    "https://news.google.com/rss/articles/{}",
)
_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_IMPERSONATE = "chrome"

_CONSENT_COOKIE = {"CONSENT": "PENDING+987"}

_SG_RE = re.compile(r'data-n-a-sg="([^"]+)"')
_TS_RE = re.compile(r'data-n-a-ts="([^"]+)"')
_ARTICLE_ID_RE = re.compile(r"/(?:articles|read)/([^/?]+)")

_INNER_CONFIG = [
    ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
     None, None, None, None, None, 0, 1],
    "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
]

_NEW_STYLE_MARKER = "AU_yqL"

_cache: dict[str, str] = {}


def is_google_news_url(url: object) -> bool:
    """True si el URL es un redirect de Google News (articles/read)."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.hostname == "news.google.com"
        and bool(re.search(r"/(articles|read)/", parsed.path or ""))
    )


def _extract_article_id(url: str) -> str:
    match = _ARTICLE_ID_RE.search(urlparse(url).path or "")
    if not match:
        raise ValueError("no se pudo extraer el ID del artículo")
    return match.group(1)


def _try_offline_decode(article_id: str) -> Optional[str]:
    """Decodifica IDs legacy (pre-2024) sin red. Retorna None si es nuevo estilo."""
    try:
        padded = article_id + "=" * (-len(article_id) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except Exception:
        return None

    if raw[:3] == b"\x08\x13\x22":
        raw = raw[3:]
    if raw[-3:] == b"\xd2\x01\x00":
        raw = raw[:-3]
    if not raw:
        return None

    try:
        first = raw[0]
        if first & 0x80:
            length = (first & 0x7F) | (raw[1] << 7)
            start = 2
        else:
            length = first
            start = 1
        chunk = raw[start:start + length]
    except IndexError:
        return None

    text = chunk.decode("utf-8", "ignore")
    if text.startswith(_NEW_STYLE_MARKER):
        return None
    if text.startswith(("http://", "https://")):
        return text
    return None


def _make_session():
    if _cffi_requests is None:
        raise RuntimeError("curl_cffi no está instalado")
    return _cffi_requests.Session(impersonate=_IMPERSONATE)


def _fetch_decoding_params(session, article_id: str, timeout: float):
    """Petición 1: GET de la página del artículo para sacar firma y timestamp."""
    last_error: Optional[Exception] = None
    for template in _PAGE_URL_TEMPLATES:
        page_url = template.format(article_id)
        try:
            resp = session.get(page_url, cookies=_CONSENT_COOKIE, timeout=timeout)
        except Exception as exc:
            last_error = exc
            continue
        if resp.status_code != 200:
            last_error = RuntimeError(f"GET falló con HTTP {resp.status_code}")
            continue
        html = resp.text
        sg_match = _SG_RE.search(html)
        ts_match = _TS_RE.search(html)
        if sg_match and ts_match:
            return sg_match.group(1), ts_match.group(1)
        last_error = RuntimeError("params de decodificación no encontrados")
    raise RuntimeError(f"no se pudo obtener firma/timestamp: {last_error}")


def _parse_batchexecute(text: str) -> str:
    parts = text.split("\n\n", 1)
    if len(parts) < 2:
        raise ValueError("respuesta inesperada de batchexecute (sin payload)")

    frames = json.loads(parts[1])
    frame = next(
        (f for f in frames if isinstance(f, list) and f and f[0] == "wrb.fr"),
        None,
    )
    if frame is None:
        raise ValueError("sin frame de datos en la respuesta de batchexecute")

    inner_json = frame[2] if len(frame) > 2 else None
    if not inner_json:
        raise ValueError("Google no pudo resolver el URL (payload null)")

    decoded = json.loads(inner_json)
    if isinstance(decoded, list) and len(decoded) > 1 and isinstance(decoded[1], str):
        return decoded[1]
    raise ValueError("no se pudo extraer el URL de la respuesta")


def _batchexecute(session, article_id: str, signature: str, timestamp: str,
                  timeout: float) -> str:
    """Petición 2: POST garturlreq a batchexecute y parsea el resultado."""
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        raise ValueError(f"timestamp inválido: {timestamp!r}")

    inner = json.dumps(
        ["garturlreq", _INNER_CONFIG, article_id, timestamp_int, signature],
        separators=(",", ":"),
    )
    outer = json.dumps([[["Fbv4je", inner]]], separators=(",", ":"))
    body = "f.req=" + quote(outer)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://news.google.com",
        "Referer": "https://news.google.com/",
        "X-Same-Domain": "1",
    }

    resp = session.post(_BATCHEXECUTE_URL, data=body, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise ValueError(f"batchexecute falló con HTTP {resp.status_code}")
    return _parse_batchexecute(resp.text)


def decodificar_google_news(url: str, timeout: float = 15.0, online: bool = True) -> str:
    """Decodifica un redirect de Google News a la URL real del artículo.

    Retorna la URL real, o el URL original sin cambios si no se pudo decodificar.
    Resultados cacheados para no repetir llamadas a Google.
    """
    if not is_google_news_url(url):
        return url
    if url in _cache:
        return _cache[url]

    article_id = _extract_article_id(url)
    resultado = _try_offline_decode(article_id)
    if resultado is None and online:
        try:
            session = _make_session()
            try:
                signature, timestamp = _fetch_decoding_params(session, article_id, timeout)
                resultado = _batchexecute(session, article_id, signature, timestamp, timeout)
            finally:
                session.close()
        except Exception:
            resultado = url

    if resultado is not None:
        _cache[url] = resultado
    return resultado or url
