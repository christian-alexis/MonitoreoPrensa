"""
Resumen extractivo sin IA (TextRank puro-Python, sin dependencias externas).

Selecciona las oraciones más representativas del texto original en vez de
generar texto nuevo, así que nunca puede alucinar cifras, nombres o fechas.
Sirve como último respaldo gratuito y sin API keys cuando ningún proveedor
de IA (ni siquiera Ollama local) está disponible.
"""
import math
import re
from collections import Counter
from typing import List

_STOPWORDS_ES = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "y", "o", "u", "e", "que", "en", "a", "con", "por", "para", "su", "sus",
    "se", "lo", "le", "les", "es", "son", "fue", "fueron", "ser", "estar",
    "esta", "este", "estos", "estas", "como", "más", "mas", "pero", "sin",
    "sobre", "entre", "también", "no", "sí", "si", "ya", "muy", "hay", "ha",
    "han", "así", "cuando", "donde", "cual", "cuales", "quien", "quienes",
    "desde", "hasta", "durante", "tras", "ante", "bajo", "cabe", "contra",
    "según", "mediante", "todo", "toda", "todos", "todas", "otro", "otra",
    "otros", "otras",
}

_ORACION_RE = re.compile(r"(?<=[\.\!\?])\s+(?=[A-ZÁÉÍÓÚÑ0-9])")
_PALABRA_RE = re.compile(r"[a-záéíóúñü]+")


def _dividir_oraciones(texto: str) -> List[str]:
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if not texto:
        return []
    partes = _ORACION_RE.split(texto)
    return [p.strip() for p in partes if len(p.strip()) > 15]


def _tokenizar(oracion: str) -> List[str]:
    palabras = _PALABRA_RE.findall(oracion.lower())
    return [p for p in palabras if p not in _STOPWORDS_ES and len(p) > 2]


def _similitud(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    comunes = set(ca) & set(cb)
    if not comunes:
        return 0.0
    numerador = sum(min(ca[w], cb[w]) for w in comunes)
    denom = math.log(len(a) + 1) + math.log(len(b) + 1)
    return numerador / denom if denom else 0.0


def _text_rank(oraciones: List[str], iteraciones: int = 20, d: float = 0.85) -> List[float]:
    n = len(oraciones)
    if n == 0:
        return []
    tokens = [_tokenizar(o) for o in oraciones]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = _similitud(tokens[i], tokens[j])
            sim[i][j] = s
            sim[j][i] = s
    sumas = [sum(fila) or 1.0 for fila in sim]
    scores = [1.0] * n
    for _ in range(iteraciones):
        nuevos = []
        for i in range(n):
            total = sum((sim[j][i] / sumas[j]) * scores[j] for j in range(n) if j != i)
            nuevos.append((1 - d) + d * total)
        scores = nuevos
    return scores


def resumen_extractivo(texto: str, max_palabras: int = 400) -> str:
    """Extrae las oraciones más relevantes del texto (sin generar contenido nuevo).

    Devuelve las oraciones seleccionadas en su orden original de aparición,
    hasta acercarse al límite de palabras indicado.
    """
    oraciones = _dividir_oraciones(texto)
    if not oraciones:
        return ""
    if len(oraciones) <= 3:
        return " ".join(oraciones)

    scores = _text_rank(oraciones)
    orden = sorted(range(len(oraciones)), key=lambda i: scores[i], reverse=True)

    seleccion_idx = []
    palabras_acum = 0
    for i in orden:
        n_palabras = len(oraciones[i].split())
        if palabras_acum + n_palabras > max_palabras and seleccion_idx:
            continue
        seleccion_idx.append(i)
        palabras_acum += n_palabras
        if palabras_acum >= max_palabras:
            break

    seleccion_idx.sort()
    return " ".join(oraciones[i] for i in seleccion_idx)
