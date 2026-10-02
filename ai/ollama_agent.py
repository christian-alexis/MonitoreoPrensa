"""
Agente de IA para análisis de prensa.
Soporta Ollama (local/gratis) como opción principal.
"""
import os
import json
import requests as req


class OllamaAgent:
    """Agente de IA para análisis de prensa usando Ollama (local)."""

    def __init__(self, api_key: str = None):
        self.ollama_url = "http://localhost:11434"
        self.modelo = "qwen2.5:3b-instruct"
        self._check_ollama()

    def _check_ollama(self):
        """Verifica si Ollama está corriendo. Prioriza modelos ligeros (3B-8B),
        pensados para correr en CPU sin GPU dedicada; si hay modelos más grandes
        instalados (servidor con más recursos/GPU), se usan esos en su lugar."""
        try:
            resp = req.get(f"{self.ollama_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                disponibles = [m["name"] for m in data.get("models", [])]
                preferencia = [
                    "qwen2.5:3b", "llama3.2:3b", "phi3.5", "gemma2:2b",
                    "qwen2.5:7b", "llama3.1:8b", "gemma2",
                    "mixtral", "qwen2.5:14b", "qwen2.5:32b", "llama3.1:70b",
                    "llama3.2", "llama3", "gemma", "phi",
                ]
                for patron in preferencia:
                    for m in disponibles:
                        if patron in m.lower():
                            self.modelo = m
                            break
                    else:
                        continue
                    break
                self._ollama_ok = True
            else:
                self._ollama_ok = False
        except Exception:
            self._ollama_ok = False

    @property
    def is_available(self) -> bool:
        return self._ollama_ok

    @property
    def status_msg(self) -> str:
        if self._ollama_ok:
            return f"Ollama conectado ({self.modelo})"
        return "Ollama no detectado. Instala desde ollama.com y ejecuta: ollama pull llama3.2"

    def _call_ollama(self, system_prompt: str, user_message: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        """Llama a la API de Ollama (no streaming)."""
        if not self._ollama_ok:
            return (
                "Ollama no está corriendo.\n\n"
                "**Para instalar:**\n"
                "1. Ve a https://ollama.com y descarga Ollama\n"
                "2. Abre Terminal y ejecuta: `ollama pull llama3.2`\n"
                "3. Reinicia esta aplicación"
            )

        try:
            payload = {
                "model": self.modelo,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            resp = req.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "Sin respuesta")
            else:
                return f"Error de Ollama: {resp.status_code}"
        except Exception as e:
            return f"Error al conectar con Ollama: {e}"

    def _call_ollama_streaming(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        on_progress=None,
    ) -> str:
        """Streaming con callback on_progress(pct: int). La barra avanza con tokens reales."""
        if not self._ollama_ok:
            return self._call_ollama(system_prompt, user_message, max_tokens, temperature)

        try:
            payload = {
                "model": self.modelo,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            resp = req.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                stream=True,
                timeout=120,
            )
            resp.encoding = "utf-8"

            full_content = ""
            token_count = 0
            for line in resp.iter_lines(decode_unicode=True):
                if line:
                    data = json.loads(line)
                    delta = data.get("message", {}).get("content", "")
                    full_content += delta
                    if delta:
                        token_count += 1
                        if on_progress:
                            pct = min(int(token_count / max_tokens * 100), 99)
                            on_progress(pct)
                    if data.get("done"):
                        break

            if on_progress:
                on_progress(100)
            return full_content
        except Exception as e:
            return f"Error al conectar con Ollama: {e}"

    def resumir_noticias(self, noticias: list) -> str:
        """Genera un resumen ejecutivo de una lista de noticias."""
        if not noticias:
            return "No hay noticias para resumir."

        noticias_texto = "\n".join(
            f"- [{n.get('Categoría', n.get('categoria', 'N/A'))}] "
            f"{n.get('Título', n.get('title', ''))} "
            f"(Fuente: {n.get('Fuente', n.get('source_name', ''))}, "
            f"Fecha: {n.get('Fecha', n.get('fecha_display', ''))})"
            for n in noticias
        )

        system_prompt = (
            "Eres un analista de prensa del gobierno de México (SHCP). "
            "Genera resúmenes ejecutivos concisos y profesionales. "
            "Usa un tono formal y objetivo. "
            "Responde en español."
        )

        user_message = (
            f"Genera un resumen ejecutivo de las siguientes noticias:\n\n"
            f"{noticias_texto}\n\n"
            f"Incluye:\n"
            f"1. Resumen general (2-3 párrafos)\n"
            f"2. Temas principales identificados\n"
            f"3. Posibles implicaciones para la política pública"
        )

        return self._call_ollama(system_prompt, user_message)

    def analizar_enfoque(self, titulo: str, fuente: str = "") -> dict:
        """Analiza el enfoque de una noticia."""
        system_prompt = (
            "Eres un analista de medios. Analiza el enfoque de noticias del gobierno mexicano. "
            'Responde SOLO con un JSON: {"enfoque": "Positivo|Neutral|Negativo", '
            '"razonamiento": "breve explicación"}'
        )

        user_message = f"Noticia: {titulo}\nFuente: {fuente}"
        respuesta = self._call_ollama(system_prompt, user_message)

        try:
            # Intentar extraer JSON de la respuesta
            start = respuesta.find("{")
            end = respuesta.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(respuesta[start:end])
        except json.JSONDecodeError:
            pass
        return {"enfoque": "Neutral", "razonamiento": "No se pudo analizar"}

    def generar_resumen_carton(self, titulo: str, fuente: str) -> str:
        """Genera una descripción breve de un cartón editorial."""
        system_prompt = (
            "Eres un analista de prensa. Describe brevemente el tema "
            "probable de un cartón editorial basado en su título y fuente. "
            "Máximo 2 oraciones. Responde en español."
        )

        user_message = f"Cartón: {titulo}\nFuente: {fuente}"
        return self._call_ollama(system_prompt, user_message)

    def analizar_relevancia(self, titulo: str, url: str, fuente: str = "") -> dict:
        """Lee la noticia completa y analiza su relevancia para la SHCP y la UPER."""
        try:
            import requests as req
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            resp = req.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            # Extraer texto del artículo
            articulo = ""
            for tag in soup.find_all(["article", "main", "p", "h1", "h2", "h3"]):
                texto = tag.get_text(strip=True)
                if len(texto) > 30:
                    articulo += texto + "\n"

            if not articulo:
                articulo = soup.get_text()[:5000]

            articulo = articulo[:5000]

            system_prompt = (
                "Eres un analista senior de la Unidad de Política y Estrategia para Resultados (UPER) "
                "de la SHCP (Secretaría de Hacienda y Crédito Público de México).\n\n"
                "Tu tarea es evaluar qué tan relevante es una noticia para la SHCP "
                "(Secretaría de Hacienda y Crédito Público) y su unidad UPER.\n\n"
                "La SHCP es la máxima prioridad de análisis. Una noticia es ALTAMENTE relevante "
                "si menciona o se relaciona con:\n"
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
                "Y las categorías de análisis:\n"
                "- Núcleo presupuestario: presupuesto, gasto, egresos, subejercicio\n"
                "- Planeación y política pública: políticas, programas, planeación, desarrollo, "
                "evaluación, indicadores, resultados, impacto\n"
                "- Anexos transversales: anexo transversal, anexos transversales, presupuesto etiquetado por transversalidad\n"
                "- Control y rendición de cuentas: auditoría, ASF, fiscalización, cumplimiento\n"
                "- Contexto económico: inflación, crecimiento, PIB, inversión, empleo\n\n"
                "REGLAS DE PUNTUACIÓN:\n"
                "- Si la noticia menciona DIRECTAMENTE a la SHCP o Hacienda: 9-10\n"
                "- Si habla de presupuesto, ingresos, gasto o deuda pública: 7-8\n"
                "- Si aborda política económica, PIB, inflación o inversión: 5-6\n"
                "- Si toca temas afines (programas, indicadores, evaluación): 3-4\n"
                "- Sin relación alguna: 0-2\n\n"
                'Responde SOLO con un JSON válido: {"relevancia": <número entero 0-10>, "razonamiento": "<explicación detallada en 2-3 oraciones>"}'
            )

            user_message = (
                f"ARTÍCULO COMPLETO:\n{articulo}\n\n"
                f"Título: {titulo}\nFuente: {fuente}"
            )

            respuesta = self._call_ollama(system_prompt, user_message)

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
        """Lee la noticia desde la URL y genera un resumen ejecutivo + sentimiento."""
        try:
            import requests as req
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            resp = req.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            # Extraer texto del artículo
            articulo = ""
            for tag in soup.find_all(["article", "main", "p", "h1", "h2", "h3"]):
                texto = tag.get_text(strip=True)
                if len(texto) > 30:
                    articulo += texto + "\n"

            if not articulo:
                articulo = soup.get_text()[:5000]

            # Limitar longitud
            articulo = articulo[:4000]

            system_prompt = (
                "Eres un analista senior de la Unidad de Política y Estrategia para Resultados "
                "de la SHCP (Secretaría de Hacienda y Crédito Público de México).\n\n"
                "Lee el siguiente artículo de prensa y genera:\n\n"
                "1. RESUMEN EJECUTIVO (5-6 oraciones, tono formal gubernamental):\n"
                "Debe seguir este estilo exacto:\n"
                "La nota informa que [tema principal del artículo]. [Detalle específico con datos "
                "o cifras si las hay]. [Contexto o antecedente relevante]. "
                "Este resultado refleja [análisis de lo que implica]. "
                "La evolución de [factor analizado] constituye un indicador relevante para el "
                "seguimiento de [área de interés para la SHCP/UPER].\n\n"
                "2. SENTIMIENTO: Positivo, Negativo o Neutral\n\n"
                "REGLAS IMPORTANTES:\n"
                "- El resumen debe ser EXACTAMENTE 5-6 oraciones, conciso y directo\n"
                "- NO incluyas 'Resumen Ejecutivo:' al inicio\n"
                "- NO incluyas 'Referencia:' ni el nombre de la fuente al final\n"
                "- El resumen debe ser SOLO el párrafo limpio\n"
                "- Tono formal, gubernamental, profesional\n"
                "- Incluir la relevancia para la SHCP/UPER\n"
                "- Mencionar implicaciones para la política pública\n"
                "- Incluir datos específicos si los hay\n\n"
                'Responde SOLO con un JSON: {"resumen": "<texto del resumen>", "sentimiento": "Positivo|Negativo|Neutral"}'
            )

            user_message = (
                f"ARTÍCULO COMPLETO:\n{articulo}\n\n"
                f"Título: {titulo}\nFuente: {fuente}"
            )

            respuesta = self._call_ollama(system_prompt, user_message)

            try:
                start = respuesta.find("{")
                end = respuesta.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(respuesta[start:end])
                    return {
                        "resumen": data.get("resumen", respuesta),
                        "sentimiento": data.get("sentimiento", "Neutral")
                    }
            except (json.JSONDecodeError, ValueError):
                pass

            return {"resumen": respuesta, "sentimiento": "Neutral"}

        except Exception as e:
            return {"resumen": f"Error al leer la noticia: {e}", "sentimiento": "Neutral"}

    def generar_resumen_ejecutivo(self, noticias: list) -> str:
        """Genera un resumen ejecutivo estilo SHCP para la Unidad de Política y Estrategia para Resultados."""
        if not noticias:
            return "No hay noticias seleccionadas para generar el resumen."

        noticias_texto = "\n".join(
            f"- [{n.get('Categoría', 'N/A')}] {n.get('Título', '')} "
            f"(Fuente: {n.get('Fuente', '')}, Enfoque: {n.get('Enfoque', 'Neutral')}, "
            f"Relevancia SHCP: {n.get('Relevancia_SHCP', 'N/A')}/10)"
            for n in noticias
        )

        system_prompt = (
        "Eres un analista senior de la Unidad de Política y Estrategia para Resultados "
        "de la SHCP (Secretaría de Hacienda y Crédito Público de México).\n\n"
        "Se te proporciona la VERSIÓN ESTENOGRÁFICA COMPLETA de la conferencia matutina "
        "(Mañanera) de la presidenta de México.\n\n"
        "Genera un RESUMEN EJECUTIVO que cumpla estos cuatro criterios:\n"
        "1. Nivel de detalle: Incluye nombres, cifras, fechas, montos y datos específicos "
        "que aparezcan en la conferencia. No te quedes en lo genérico.\n"
        "2. Concisión: Cada línea debe aportar información valiosa. Sin rodeos, sin "
        "relleno, sin repeticiones. Ve directo al punto.\n"
        "3. Tono institucional: Redacción formal, objetiva y neutral. Sin opiniones, "
        "sin adjetivos calificativos innecesarios. Parece un memo interno de gobierno.\n"
        "4. Utilidad para un directivo: El lector es un Director General de la SHCP. "
        "Debe poder leerlo en 2 minutos y saber: ¿qué pasó?, ¿qué me importa como SHCP?, "
        "¿hay algo que requiera acción o seguimiento?\n\n"
        "Estructura obligatoria:\n\n"
        "## Resumen Ejecutivo – Conferencia Matutina del {fecha}\n\n"
        "### Resumen general\n"
        "[3-5 líneas que sinteticen TODA la conferencia: quién habló, "
        "eje central, tono. Incluye datos específicos.]\n\n"
        "### Temas abordados\n"
        "- [Tema 1]: [explicación con datos concretos]\n"
        "- [Tema 2]: [explicación con datos concretos]\n"
        "- ...\n"
        "[TODOS los temas en orden de aparición. Para cada uno: qué se dijo, quién lo dijo, "
        "y algún detalle relevante (cifra, fecha, monto).]\n\n"
        "### Anuncios o compromisos\n"
        "- [Anuncio 1]: [quién, qué, cuándo]\n"
        "- [Anuncio 2]: [quién, qué, cuándo]\n"
        "- ...\n"
        "[Si aplica.]\n\n"
        "### Relevancia para la SHCP/UPER\n"
        "[Evalúa ÚNICAMENTE si algún tema de la conferencia se relaciona de forma DIRECTA "
        "con las funciones específicas de la Unidad de Política y Estrategia para Resultados (UPER). "
        "Considera EXCLUSIVAMENTE los siguientes temas: Presupuesto de Egresos de la Federación (PEF), "
        "Presupuesto basado en Resultados (PbR), Evaluación de Políticas y Programas Públicos, "
        "Gasto Federalizado (participaciones, aportaciones, convenios de coordinación fiscal), "
        "Matriz de Indicadores para Resultados (MIR), sistema de evaluación del desempeño, "
        "y seguimiento a programas presupuestarios.\n"
        "NO consideres como relevante para esta sección temas generales de la SHCP que no correspondan "
        "directamente a la UPER (por ejemplo: política monetaria, deuda pública general, ingresos "
        "tributarios, tipo de cambio, mercados financieros, banca, comercio exterior), ni temas "
        "genéricos de la Administración Pública Federal (comunicación gubernamental, seguridad, "
        "salud, programas sociales) salvo que se mencione explícitamente su vínculo con el PEF, "
        "el PbR, la evaluación de políticas públicas o el gasto federalizado.\n"
        "Si ningún tema de la conferencia toca estos temas específicos de la UPER, indícalo "
        "claramente con una frase como: 'No se identificaron temas con relación directa a las "
        "funciones de la UPER en esta conferencia.' NO fuerces una conexión ni generalices "
        "a partir de temas hacendarios amplios.]\n\n"
        "REGLAS ESTRICTAS:\n"
        "- NO inventes ni modifiques nombres, cargos, fechas ni datos. Usa lo que dice el texto.\n"
        "- Cubre TODA la conferencia, no solo un segmento.\n"
        "- Máximo 500 palabras.\n"
        "- Sin opiniones ni recomendaciones. Solo hechos.\n"
        "- Si hay datos fiscales, económicos o presupuestarios, resáltalos con negritas así."
    )

        user_message = (
            f"Genera el resumen ejecutivo para las siguientes noticias seleccionadas:\n\n"
            f"{noticias_texto}\n\n"
            f"Incluye:\n"
            f"1. Análisis párrafo por párrafo de cada noticia seleccionada\n"
            f"2. Relevancia específica para la SHCP\n"
            f"3. Implicaciones para la política pública\n"
            f"4. Conclusión general"
        )

        return self._call_ollama(system_prompt, user_message)

    def clasificar_sentimiento(self, noticias: list) -> list:
        """Clasifica el sentimiento de cada noticia: positivo, negativo o neutral."""
        if not noticias:
            return []

        noticias_texto = "\n".join(
            f"{i+1}. {n.get('Título', '')} (Fuente: {n.get('Fuente', '')})"
            for i, n in enumerate(noticias)
        )

        system_prompt = (
            "Eres un analista de medios del gobierno mexicano (SHCP). "
            "Clasifica el sentimiento de cada noticia respecto a la imagen "
            "y gestión del gobierno/función pública.\n\n"
            'Responde SOLO con un JSON: {"resultados": [{"idx": 1, "sentimiento": "Positivo|Negativo|Neutral", "razon": "breve"}]}\n\n'
            "Criterios:\n"
            "- Positivo: buena gestión, logros, avances, confianza\n"
            "- Negativo: críticas, problemas, escándalos, deterioro\n"
            "- Neutral: informativo, sin carga emocional clara"
        )

        user_message = f"Clasifica el sentimiento de estas noticias:\n\n{noticias_texto}"
        respuesta = self._call_ollama(system_prompt, user_message)

        try:
            start = respuesta.find("{")
            end = respuesta.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(respuesta[start:end])
                return data.get("resultados", [])
        except (json.JSONDecodeError, ValueError):
            pass
        return []

    def chat(self, mensaje: str, contexto: str = "") -> str:
        """Chat interactivo con contexto de noticias/cartones cargados."""
        system_prompt = (
            "Eres el asistente de IA de la Unidad de Política y Estrategia para Resultados "
            "de la SHCP (Secretaría de Hacienda y Crédito Público de México). "
            "Ayudas a analizar noticias y cartones editoriales. "
            "Respondes de forma concisa, profesional y en español. "
            "Si no tienes suficiente información, lo indicas."
        )

        user_message = mensaje
        if contexto:
            user_message = (
                f"Contexto de datos cargados:\n{contexto}\n\n"
                f"Pregunta del usuario:\n{mensaje}"
            )

        return self._call_ollama(system_prompt, user_message)
