"""
Agente unificado de noticias.

Envuelve cualquier proveedor (Gemini, Anthropic, Groq, OpenRouter, Cerebras,
Ollama) y le da la interfaz común de la Síntesis de Noticias: leer el artículo
completo desde el enlace, generar resumen por noticia, analizar relevancia,
resumen ejecutivo y chat.

Reglas de fidelidad: los resúmenes deben conservar EXACTAMENTE los nombres,
cargos, cifras, fechas y datos tal como aparecen en el artículo.
"""
import json

import requests as req
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": "https://news.google.com/",
}
MAX_ARTICULO = 12000

SYSTEM_ANALISTA = (
    "Eres un analista senior de la Unidad de Política y Estrategia para Resultados (UPER) "
    "de la SHCP (Secretaría de Hacienda y Crédito Público de México). "
    "Extraes información únicamente del texto que se te proporciona. "
    "Nunca uses tu conocimiento previo ni inventes nombres, cargos, citas, cifras o datos."
)


def _invocar(backend, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
    """Llama al proveedor con la interfaz interna que tenga disponible."""
    if hasattr(backend, "_call") and callable(getattr(backend, "_call")):
        return backend._call(system, user, max_tokens=max_tokens, temperature=temperature)
    if hasattr(backend, "_call_ollama_streaming"):
        return backend._call_ollama_streaming(
            system, user, max_tokens=max_tokens, temperature=temperature
        )
    if hasattr(backend, "_call_ollama"):
        return backend._call_ollama(system, user, max_tokens, temperature)
    if hasattr(backend, "generar_resumen"):
        return backend.generar_resumen(system, user, max_tokens=max_tokens)
    return "Error: Agente de IA no disponible."


def leer_articulo(url: str) -> str:
    """Descarga la noticia y extrae el texto completo del artículo desde el enlace."""
    # Los redirects de Google News no se pueden leer directamente; se decodifican
    # a la URL real (método offline rápido + batchexecute con cache).
    if "news.google.com" in url:
        from utils.google_news import decodificar_google_news
        url = decodificar_google_news(url)
        if "news.google.com" in url:
            return ""
    resp = req.get(url, headers=HEADERS, timeout=20)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    for el in soup.select(
        "script, style, nav, header, footer, aside, form, iframe, "
        ".ad, [class*=banner], [id*=banner], [class*=advertisement]"
    ):
        el.decompose()

    contenedor = (
        soup.select_one("article")
        or soup.select_one("main")
        or soup.select_one("[class*=article]")
        or soup.select_one("[class*=body]")
        or soup
    )
    texto = ""
    for tag in contenedor.find_all(["p", "h1", "h2", "h3", "blockquote", "li"]):
        t = tag.get_text(strip=True)
        if len(t) > 30:
            texto += t + "\n"
    if not texto:
        texto = soup.get_text()

    lineas = []
    for l in texto.splitlines():
        l = l.strip()
        if l and (not lineas or lineas[-1] != l):
            lineas.append(l)
    return "\n".join(lineas)[:MAX_ARTICULO]


def _parsear_json(respuesta: str, campo: str):
    """Extrae el primer JSON de la respuesta. Devuelve (campo, data_dict)."""
    try:
        start = respuesta.find("{")
        end = respuesta.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(respuesta[start:end])
            return data.get(campo, respuesta), data
    except (json.JSONDecodeError, ValueError):
        pass
    return respuesta, {}


class NewsAgent:
    """Interfaz común de noticias sobre cualquier proveedor de IA."""

    def __init__(self, backend, etiqueta: str):
        self._backend = backend
        self.etiqueta = etiqueta
        self.modelo = getattr(backend, "modelo", "") or etiqueta

    @property
    def is_available(self) -> bool:
        return bool(getattr(self._backend, "is_available", True))

    def _call(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        return _invocar(self._backend, system, user, max_tokens=max_tokens, temperature=temperature)

    # ---------------------------------------------------------
    def generar_resumen_noticia(self, titulo: str, url: str, fuente: str = "") -> dict:
        """Lee la noticia completa desde el enlace y la resume con fidelidad."""
        try:
            articulo = leer_articulo(url)
            if not articulo:
                return {"resumen": "No se pudo extraer el contenido de la noticia.", "sentimiento": "Neutral"}

            system = (
                SYSTEM_ANALISTA + "\n\n"
                "Lee el ARTÍCULO COMPLETO y redacta un RESUMEN EJECUTIVO de la noticia, "
                "en ESPAÑOL, con tono profesional y periodístico, como un brief para un "
                "directivo. Debe verse como si un analista lo hubiera escrito leyendo la nota.\n\n"
                "REGLAS OBLIGATORIAS:\n"
                "- Usa SOLO la información del artículo. NO uses conocimiento previo.\n"
                "- Incluye SIEMPRE los datos concretos del artículo: cifras exactas, "
                "porcentajes, precios, montos, fechas, nombres propios, cargos, empresas, "
                "instituciones y lugares, tal como están escritos.\n"
                "- Explica el QUÉ y el PORQUÉ: qué ocurrió, cuánto, cuándo, y las causas o "
                "factores que el propio artículo menciona.\n"
                "- Si el artículo cita a alguien, integra UNA cita textual corta entre "
                "comillas con las palabras exactas.\n"
                "- NO repitas el titular. NO digas frases vacías tipo: 'El artículo menciona...', "
                "'La información se obtuvo a través de...', 'No se proporcionan detalles "
                "adicionales', 'El artículo se enfoca en...'.\n"
                "- NO agregues análisis, causas, contexto ni conclusiones que NO estén en el texto.\n\n"
                "EXTENSIÓN: 3-5 oraciones, un solo párrafo limpio (60-100 palabras), sin "
                "encabezados ni viñetas.\n\n"
                "EJEMPLO DEL ESTILO ESPERADO:\n"
                "'El peso mexicano se apreció un 0.25% para cotizar en 17.2107 por dólar, "
                "impulsado por una menor demanda de activos refugio ante la posible desescalada "
                "del conflicto en Irán y la debilidad del billete verde, que ronda mínimos de "
                "seis semanas. Los mercados reaccionaron a señales económicas mixtas: por un lado, "
                "Estados Unidos reportó una desaceleración en la creación de empleo privado en "
                "julio previa a datos clave de desempleo; por el otro, en México la inversión "
                "empresarial cayó en mayo tras dos meses al alza, lo que moderó el optimismo "
                "sobre el crecimiento económico local.'\n\n"
                "Después indica el SENTIMIENTO: Positivo, Negativo o Neutral.\n"
                'Responde SOLO con JSON: {"resumen": "<texto>", "sentimiento": "Positivo|Negativo|Neutral"}'
            )
            user = f"ARTÍCULO COMPLETO:\n{articulo}\n\nTítulo: {titulo}\nFuente: {fuente}"
            respuesta = self._call(system, user, max_tokens=1024, temperature=0.3)

            resumen, data = _parsear_json(respuesta, "resumen")
            sentimiento = data.get("sentimiento", "Neutral")
            if sentimiento not in ("Positivo", "Negativo", "Neutral"):
                sentimiento = "Neutral"
            return {"resumen": resumen, "sentimiento": sentimiento}
        except Exception as e:
            return {"resumen": f"Error al leer la noticia: {e}", "sentimiento": "Neutral"}

    # ---------------------------------------------------------
    def analizar_relevancia(self, titulo: str, url: str, fuente: str = "") -> dict:
        """Lee la noticia completa y puntúa su relevancia para la SHCP/UPER (0-10)."""
        try:
            articulo = leer_articulo(url)
            if not articulo:
                return {"relevancia": 0, "razonamiento": "No se pudo extraer el contenido de la noticia."}

            system = (
                "Eres un analista senior de la Unidad de Política y Estrategia para Resultados (UPER) "
                "de la SHCP.\n\n"
                "Tu tarea es evaluar qué tan relevante es una noticia para la SHCP "
                "(Secretaría de Hacienda y Crédito Público) y su unidad UPER.\n\n"
                "Una noticia es ALTAMENTE relevante si menciona o se relaciona con:\n"
                "- Secretaría de Hacienda, SHCP, Hacienda Pública\n"
                "- Presupuesto de Egresos de la Federación (PEF)\n"
                "- Política tributaria, impuestos, ingresos públicos, recaudación\n"
                "- Deuda pública, finanzas públicas, déficit fiscal\n"
                "- Política económica, crecimiento económico, PIB\n"
                "- Gasto público, egresos, subejercicio\n"
                "- Crédito público, financiamiento, inversión pública\n\n"
                "También considera relevante si se relaciona con la UPER:\n"
                "- Indicadores de resultados y gestión\n"
                "- Informe Presupuestal\n"
                "- Evaluación de programas\n"
                "- Planeación estratégica, monitoreo\n"
                "- Rendición de cuentas\n\n"
                "REGLAS DE PUNTUACIÓN:\n"
                "- Si menciona DIRECTAMENTE a la SHCP o Hacienda: 9-10\n"
                "- Si habla de presupuesto, ingresos, gasto o deuda pública: 7-8\n"
                "- Si aborda política económica, PIB, inflación o inversión: 5-6\n"
                "- Si toca temas afines (programas, indicadores, evaluación): 3-4\n"
                "- Sin relación alguna: 0-2\n\n"
                'Responde SOLO con JSON: {"relevancia": <número entero 0-10>, "razonamiento": "<explicación en 2-3 oraciones>"}'
            )
            user = f"ARTÍCULO COMPLETO:\n{articulo}\n\nTítulo: {titulo}\nFuente: {fuente}"
            respuesta = self._call(system, user, max_tokens=512, temperature=0.2)

            _, data = _parsear_json(respuesta, "relevancia")
            try:
                score = int(data.get("relevancia", 5))
            except (TypeError, ValueError):
                score = 5
            score = max(0, min(10, score))
            return {"relevancia": score, "razonamiento": data.get("razonamiento", "")}
        except Exception as e:
            return {"relevancia": 0, "razonamiento": f"Error al leer la noticia: {e}"}

    # ---------------------------------------------------------
    def generar_resumen_ejecutivo(self, noticias: list) -> str:
        """Consolida las noticias seleccionadas en un resumen ejecutivo fiel."""
        if not noticias:
            return "No hay noticias seleccionadas para generar el resumen."

        noticias_texto = "\n".join(
            f"- [{n.get('Categoría', 'N/A')}] {n.get('Título', '')} "
            f"(Fuente: {n.get('Fuente', '')}, Enfoque: {n.get('Enfoque', 'Neutral')}, "
            f"Relevancia SHCP: {n.get('Relevancia_SHCP', 'N/A')}/10)"
            for n in noticias
        )

        system = (
            "Eres un analista senior de la Unidad de Política y Estrategia para Resultados (UPER) "
            "de la SHCP.\n\n"
            "Genera un RESUMEN EJECUTIVO para un Director General de la SHCP que lo lea en 2 minutos.\n\n"
            "REGLAS DE FIDELIDAD:\n"
            "- Usa ÚNICAMENTE la información proporcionada. No inventes datos.\n"
            "- Conserva EXACTAMENTE los nombres, cargos, dependencias, cifras, fechas y fuentes indicados.\n"
            "- NO redondees ni cambies montos, porcentajes o fechas.\n\n"
            "Estructura obligatoria:\n"
            "## Resumen Ejecutivo de Noticias\n\n"
            "### Análisis por noticia\n"
            "[Un párrafo por noticia, con los datos exactos dados.]\n\n"
            "### Relevancia para la SHCP/UPER\n"
            "[Indica qué noticias tocan presupuesto, gasto, ingresos, deuda, evaluación de "
            "programas, indicadores o rendición de cuentas.]\n\n"
            "### Implicaciones para la política pública\n"
            "[Solo lo sustentable con la información dada.]\n\n"
            "### Conclusión general\n"
            "[Breve conclusión basada solo en las noticias.]\n\n"
            "Máximo 500 palabras. Tono formal y objetivo. No inventes nada."
        )
        user = f"Genera el resumen ejecutivo para estas noticias:\n\n{noticias_texto}"
        return self._call(system, user, max_tokens=2048, temperature=0.3)

    # ---------------------------------------------------------
    def chat(self, mensaje: str, contexto: str = "") -> str:
        system = (
            "Eres el asistente de IA de la Unidad de Política y Estrategia para Resultados "
            "de la SHCP (Secretaría de Hacienda y Crédito Público de México). "
            "Ayudas a analizar noticias y cartones editoriales. "
            "Respondes de forma concisa, profesional y en español. "
            "Si no tienes suficiente información, lo indicas."
        )
        user = mensaje
        if contexto:
            user = f"Contexto de datos cargados:\n{contexto}\n\nPregunta del usuario:\n{mensaje}"
        return self._call(system, user, max_tokens=1024, temperature=0.3)
