"""
Agente para la API de Gemini, usando peticiones HTTP directas (REST) en
vez del SDK de Google (`google-generativeai`/`google-genai`).

Motivo: el SDK autentica por header (`x-goog-api-key`), que no funciona
con las claves más recientes de AI Studio (formato "AQ...."). La API
REST con la clave como parámetro `?key=` en la URL sí funciona con ese
mismo tipo de clave (verificado directamente contra la API de Google).
"""
import json

import requests

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key or ""
        # gemini-2.0-flash agota su cuota gratuita en este proyecto;
        # gemini-3.1-flash-lite sí tiene cuota disponible (verificado
        # con la API real usando una clave válida).
        self.modelo = "gemini-3.1-flash-lite"
        self._ok = bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self._ok

    def _call(self, system_prompt: str, user_message: str, max_tokens: int = 2048, temperature: float = 0.3) -> str:
        if not self._ok:
            return "Error: Falta API key de Gemini."

        url = f"{BASE_URL}/{self.modelo}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        try:
            resp = requests.post(url, json=payload, timeout=300)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code != 200:
                err = data.get("error", {})
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
                if resp.status_code == 429 or err.get("status") == "RESOURCE_EXHAUSTED":
                    return "__QUOTA_EXCEEDED__"
                return f"Error con Gemini API: {resp.status_code} {msg}"
            candidatos = data.get("candidates") or []
            if not candidatos:
                return "Error con Gemini API: sin respuesta (posible bloqueo de contenido)"
            partes = candidatos[0].get("content", {}).get("parts", [])
            texto = "".join(p.get("text", "") for p in partes)
            return texto or "Sin respuesta"
        except requests.RequestException as e:
            return f"Error de conexión con Gemini API: {e}"
        except (KeyError, IndexError, TypeError) as e:
            return f"Error al procesar respuesta de Gemini API: {e}"

    def generar_resumen(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        return self._call(system_prompt, user_message, max_tokens)

    def generar_resumen_carton(self, titulo: str, fuente: str) -> str:
        system_prompt = (
            "Eres un analista de prensa. Describe brevemente el tema "
            "probable de un cartón editorial basado en su título y fuente. "
            "Máximo 2 oraciones. Responde en español."
        )
        user_message = f"Cartón: {titulo}\nFuente: {fuente}"
        return self._call(system_prompt, user_message, max_tokens=512)

    def analizar_enfoque(self, titulo: str, fuente: str = "") -> dict:
        system_prompt = (
            "Eres un analista de medios. Analiza el enfoque de noticias del gobierno mexicano. "
            'Responde SOLO con un JSON: {"enfoque": "Positivo|Neutral|Negativo", '
            '"razonamiento": "breve explicación"}'
        )
        user_message = f"Noticia: {titulo}\nFuente: {fuente}"
        respuesta = self._call(system_prompt, user_message, max_tokens=256, temperature=0.2)
        try:
            start = respuesta.find("{")
            end = respuesta.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(respuesta[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {"enfoque": "Neutral", "razonamiento": "No se pudo analizar"}

    def chat(self, mensaje: str, contexto: str = "") -> str:
        system_prompt = (
            "Eres el asistente de IA de la Unidad de Política y Estrategia para Resultados "
            "de la SHCP (Secretaría de Hacienda y Crédito Público de México). "
            "Ayudas a analizar noticias y cartones editoriales. "
            "Respondes de forma concisa, profesional y en español. "
            "Si no tienes suficiente información, lo indicas."
        )
        user_message = mensaje
        if contexto:
            user_message = f"Contexto de datos cargados:\n{contexto}\n\nPregunta del usuario:\n{mensaje}"
        return self._call(system_prompt, user_message, max_tokens=1024)

    def analizar_relevancia(self, titulo: str, url: str, fuente: str = "") -> dict:
        try:
            import requests as req
            from bs4 import BeautifulSoup

            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            resp = req.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            articulo = ""
            for tag in soup.find_all(["article", "main", "p", "h1", "h2", "h3"]):
                texto = tag.get_text(strip=True)
                if len(texto) > 30:
                    articulo += texto + "\n"
            if not articulo:
                articulo = soup.get_text()[:5000]
            articulo = articulo[:5000]

            system_prompt = (
                "Eres un analista senior de la UPER de la SHCP.\n\n"
                "Evalúa qué tan relevante es una noticia para la SHCP y la UPER.\n"
                "Puntúa 0-10 según:\n"
                "- Mención directa de SHCP/Hacienda: 9-10\n"
                "- Presupuesto, ingresos, gasto o deuda: 7-8\n"
                "- Política económica, PIB, inflación: 5-6\n"
                "- Programas, indicadores, evaluación: 3-4\n"
                "- Sin relación: 0-2\n\n"
                'Responde SOLO con JSON: {"relevancia": <0-10>, "razonamiento": "<explicación>"}'
            )
            user_message = f"ARTÍCULO COMPLETO:\n{articulo}\n\nTítulo: {titulo}\nFuente: {fuente}"
            respuesta = self._call(system_prompt, user_message, max_tokens=512, temperature=0.2)

            try:
                start = respuesta.find("{")
                end = respuesta.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(respuesta[start:end])
                    score = int(data.get("relevancia", 5))
                    score = max(0, min(10, score))
                    return {"relevancia": score, "razonamiento": data.get("razonamiento", "")}
            except (json.JSONDecodeError, ValueError):
                pass
            return {"relevancia": 5, "razonamiento": "No se pudo analizar"}
        except Exception as e:
            return {"relevancia": 0, "razonamiento": f"Error al leer la noticia: {e}"}

    def generar_resumen_noticia(self, titulo: str, url: str, fuente: str = "") -> dict:
        try:
            import requests as req
            from bs4 import BeautifulSoup

            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            resp = req.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            articulo = ""
            for tag in soup.find_all(["article", "main", "p", "h1", "h2", "h3"]):
                texto = tag.get_text(strip=True)
                if len(texto) > 30:
                    articulo += texto + "\n"
            if not articulo:
                articulo = soup.get_text()[:5000]
            articulo = articulo[:4000]

            system_prompt = (
                "Eres un analista senior de la UPER de la SHCP.\n\n"
                "Lee el artículo y genera:\n"
                "1. RESUMEN EJECUTIVO (5-6 oraciones, tono formal gubernamental):\n"
                "Sigue este estilo: 'La nota informa que [tema]. [Detalle con datos]. "
                "[Contexto]. Este resultado refleja [análisis]. "
                "La evolución de [factor] es un indicador relevante para [área SHCP/UPER].'\n"
                "2. SENTIMIENTO: Positivo, Negativo o Neutral\n\n"
                "NO incluyas 'Resumen Ejecutivo:' ni 'Referencia:' al inicio.\n"
                'Responde SOLO con JSON: {"resumen": "<texto>", "sentimiento": "Positivo|Negativo|Neutral"}'
            )
            user_message = f"ARTÍCULO COMPLETO:\n{articulo}\n\nTítulo: {titulo}\nFuente: {fuente}"
            respuesta = self._call(system_prompt, user_message, max_tokens=1024, temperature=0.3)

            try:
                start = respuesta.find("{")
                end = respuesta.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(respuesta[start:end])
                    return {"resumen": data.get("resumen", respuesta), "sentimiento": data.get("sentimiento", "Neutral")}
            except (json.JSONDecodeError, ValueError):
                pass
            return {"resumen": respuesta, "sentimiento": "Neutral"}
        except Exception as e:
            return {"resumen": f"Error al leer la noticia: {e}", "sentimiento": "Neutral"}

    def generar_resumen_ejecutivo(self, noticias: list) -> str:
        if not noticias:
            return "No hay noticias seleccionadas."

        noticias_texto = "\n".join(
            f"- [{n.get('Categoría', 'N/A')}] {n.get('Título', '')} "
            f"(Fuente: {n.get('Fuente', '')}, Enfoque: {n.get('Enfoque', 'Neutral')}, "
            f"Relevancia SHCP: {n.get('Relevancia_SHCP', 'N/A')}/10)"
            for n in noticias
        )

        system_prompt = (
            "Eres un analista senior de la UPER de la SHCP.\n\n"
            "Genera un RESUMEN EJECUTIVO con:\n"
            "1. Análisis párrafo por párrafo de cada noticia\n"
            "2. Relevancia específica para la SHCP\n"
            "3. Implicaciones para la política pública\n"
            "4. Conclusión general\n\n"
            "Tono formal, objetivo. Máximo 500 palabras.\n"
            "No inventes datos. Usa solo la información proporcionada."
        )
        user_message = f"Genera el resumen ejecutivo para estas noticias:\n\n{noticias_texto}"
        return self._call(system_prompt, user_message, max_tokens=2048, temperature=0.3)

    def clasificar_sentimiento(self, noticias: list) -> list:
        if not noticias:
            return []

        noticias_texto = "\n".join(
            f"{i+1}. {n.get('Título', '')} (Fuente: {n.get('Fuente', '')})"
            for i, n in enumerate(noticias)
        )

        system_prompt = (
            "Eres un analista de medios del gobierno mexicano (SHCP). "
            "Clasifica el sentimiento de cada noticia.\n\n"
            'Responde SOLO con JSON: {"resultados": [{"idx": 1, "sentimiento": "Positivo|Negativo|Neutral", "razon": "breve"}]}'
        )
        user_message = f"Clasifica el sentimiento de estas noticias:\n\n{noticias_texto}"
        respuesta = self._call(system_prompt, user_message, max_tokens=1024, temperature=0.2)

        try:
            start = respuesta.find("{")
            end = respuesta.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(respuesta[start:end])
                return data.get("resultados", [])
        except (json.JSONDecodeError, ValueError):
            pass
        return []
