"""
Pipeline map-reduce para el resumen de la Conferencia Matutina (Mañanera).

Fase 1 (map): divide la versión estenográfica en bloques y genera un resumen
parcial por bloque, en paralelo, usando la IA de bloques seleccionada
(Groq / OpenRouter / Cerebras / Ollama), con respaldo a Ollama local.

Fase 2 (reduce): una IA maestra consolida todos los resúmenes parciales en el
Resumen Ejecutivo Final siguiendo las reglas de negocio SHCP/UPER. La IA
maestra prueba la selección del usuario primero y luego cae en cascada:
Gemini → OpenRouter → Cerebras → Groq → Ollama local.
"""
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ai.anthropic_agent import AnthropicAgent
from ai.gemini_agent import GeminiAgent
from ai.ollama_agent import OllamaAgent
from ai.openai_compat_agent import OpenAICompatAgent, PROVIDER_PRESETS
from utils.extractive_summary import resumen_extractivo

MAX_CHARS_BLOQUE = 8000
PALABRAS_MAX_PARCIAL = 650
MAX_CHARS_MAESTRO = 14000

# Orden de la cascada de respaldo para el resumen maestro. La selección del
# usuario se intenta primero; si falla, se recorre esta lista en orden.
# Ollama (local) queda al final: requiere el servicio instalado localmente y
# el servidor de producción (2 vCPU / 2GB RAM) no tiene memoria suficiente
# para correrlo, así que las APIs gratuitas (con key) van primero. Si ningún
# proveedor responde (o no hay keys), se usa el respaldo extractivo sin IA
# (ver utils/extractive_summary.py) como última instancia.
CADENA_MAESTRO = [
    "Gemini (gratis)",
    "Anthropic Claude",
    "OpenRouter",
    "Cerebras",
    "Groq",
    "Ollama (local)",
]


# =========================================================
# DIVISIÓN EN BLOQUES
# =========================================================
def dividir_en_bloques(texto: str, max_chars: int = MAX_CHARS_BLOQUE) -> List[str]:
    """Divide el texto en bloques coherentes, sin cortar a media oración."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if len(texto) <= max_chars:
        return [texto]

    parrafos = [p.strip() for p in texto.split("\n") if p.strip()]
    bloques: List[str] = []
    actual = ""

    for p in parrafos:
        if len(p) > max_chars:
            # Párrafo gigante: cortar en el último punto antes del límite
            if actual:
                bloques.append(actual)
                actual = ""
            resto = p
            while len(resto) > max_chars:
                corte = resto.rfind(". ", 0, max_chars)
                if corte < max_chars * 0.5:
                    corte = max_chars
                bloques.append(resto[: corte + 1].strip())
                resto = resto[corte + 1:].strip()
            actual = resto
        elif len(actual) + len(p) + 1 <= max_chars:
            actual = f"{actual}\n{p}" if actual else p
        else:
            bloques.append(actual)
            actual = p

    if actual:
        bloques.append(actual)

    return [b for b in bloques if b]


# =========================================================
# PROMPTS
# =========================================================
def _system_prompt_base() -> str:
    return (
        "Eres un analista senior de política fiscal y gasto público de la SHCP. "
        "Extraes información únicamente del texto que se te proporciona. "
        "Nunca uses tu conocimiento previo ni inventes nombres, cargos, citas, "
        "cifras o datos. Mantienes un tono objetivo, técnico y exhaustivo."
    )


def prompt_parcial(idx: int, total: int, fecha_display: str) -> Dict[str, str]:
    """Prompts para generar el resumen parcial de un bloque."""
    system = _system_prompt_base()
    user = (
        "{bloque}\n\n---\n\n"
        "INSTRUCCIONES: Este es el BLOQUE {idx} de {total} de la versión estenográfica "
        "de la Conferencia Matutina del {fecha}. Genera un RESUMEN PARCIAL estructurado "
        "y denso de esta sección, pensado para que otro analista lo consolide después:\n\n"
        "- TEMA(S): lista numerada de los temas del bloque. Incluye TODOS los nombres de "
        "personas con su cargo exacto, dependencias, programas, montos, cifras y fechas "
        "que aparezcan en este bloque. No descartes temas por parecer menores.\n"
        "- ANUNCIOS O COMPROMISOS: solo lo que aplique en este bloque (quién, qué, cuándo).\n"
        "- CIFRAS Y DATOS CLAVE: cada cifra con su contexto breve.\n\n"
        "VIGILA ESPECÍFICAMENTE estos sectores y NO los omitas si aparecen en el bloque:\n"
        "- Infraestructura carretera y puentes\n"
        "- Puertos, aduanas y transporte marítimo\n"
        "- Aeropuertos y conectividad\n"
        "- Igualdad de género, derechos de las mujeres y programas sociales\n"
        "- Seguridad, justicia y defensa\n"
        "- Salud, educación, medio ambiente, energía (CFE/PEMEX), agua (CONAGUA), turismo, campo y bienestar\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del bloque proporcionado. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios, dependencias y el de la Presidenta deben coincidir EXACTAMENTE con la versión estenográfica.\n"
        "- COBERTURA COMPLETA: No omitas ningún tema ni dependencia que haya presentado información.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "- No compactes de más: conserva la información clave de cada tema, nombres y cargos, porque este resumen alimentará la síntesis final.\n"
        "- Respeta el orden de aparición de los temas en el bloque.\n"
        "- Máximo {max_palabras} palabras."
    )
    return {
        "system": system,
        "user": user,
        "max_tokens": 3000,
    }


def prompt_maestro(fecha_display: str) -> Dict[str, str]:
    """Prompts para el resumen maestro final (reglas de negocio SHCP/UPER)."""
    system = _system_prompt_base()
    user = (
        "{parciales}\n\n---\n\n"
        "INSTRUCCIONES:\n\n"
        "Aplica una metodología de análisis rigurosa de dos fases (Map-Reduce interno) para procesar el texto:\n\n"
        "1. Extrae la fecha oficial de la conferencia a partir de la transcripción de la URL.\n"
        "2. Mapea la totalidad del texto extrayendo: temas de política pública, dependencias participantes (SEMARNAT, CONAGUA, IMSS, CFE, PEMEX, SICT, SEP, SADER, etc.), programas gubernamentales, anuncios, acuerdos, cifras cuantitativas exactas y preguntas/respuestas relevantes.\n"
        "3. Genera la síntesis final aplicando de forma estricta las reglas y la estructura institucional descritas a continuación.\n\n"
        "LEE COMPLETAMENTE TODOS LOS RESUMENES PARCIALES DE PRINCIPIO A FIN. "
        "No empieces a redactar hasta haber procesado el texto completo.\n\n"
        "PASO 1 — Extrae internamente una lista numerada de TODOS los elementos de la conferencia:\n"
        "- temas de política pública, COMO MÍNIMO estos sectores: economía y finanzas públicas; infraestructura carretera y puentes; puertos y aduanas; aeropuertos; igualdad de género; seguridad y justicia; salud; educación; medio ambiente; energía (CFE/PEMEX); agua (CONAGUA); turismo; campo y programas sociales\n"
        "- dependencias que presentaron información (SEMARNAT, CONAGUA, IMSS, CFE, PEMEX, SICT, SEP, SADER, etc.)\n"
        "- programas gubernamentales\n"
        "- anuncios y compromisos\n"
        "- cifras y datos cuantitativos (porcentajes, montos, km, habitantes, fechas)\n"
        "- secciones especiales (Mujeres en la Historia, preguntas y respuestas, etc.)\n\n"
        "PASO 2 — Redacta el resumen ejecutivo asegurándote de que CADA elemento de tu lista "
        "aparezca al menos una vez en el Resumen general o en Temas abordados.\n"
        "Si una dependencia presentó información técnica, incluye el resumen de su exposición.\n"
        "Integra los nombres de dependencias de forma natural en la narrativa.\n"
        "Cada tema en Temas abordados debe tener 6-8 líneas de descripción detallada.\n"
        "Incluye anuncios relevantes surgidos en preguntas y respuestas.\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del texto fuente. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios, dependencias y el de la Presidenta deben coincidir EXACTAMENTE con la versión estenográfica.\n"
        "- COBERTURA COMPLETA: No omitas ningún tema ni dependencia que haya presentado información, incluidos los temas carreteros, portuarios, de igualdad de género y de seguridad.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "---\n"
        "### ESTRUCTURA OBLIGATORIA DE ENTREGA\n\n"
        "Entrega ÚNICAMENTE el siguiente documento (comenzando exactamente en la línea de título y finalizando en el Análisis de Impacto, sin texto introductorio ni conclusiones adicionales):\n\n"
        f"## Resumen Ejecutivo – Conferencia Matutina del {fecha_display}\n\n"
        "Resumen general:\n"
        "[700 a 1200 palabras. Un párrafo detallado por cada tema de la conferencia. "
        "Menciona las dependencias que presentaron y las cifras exactas. Cubre TODO, "
        "incluidos infraestructura carretera, puertos, igualdad de género y seguridad.]\n\n"
        "Temas abordados:\n"
        "- [Tema 1 — 6 a 8 líneas detalladas con dependencias y cifras]\n"
        "- [Tema 2 — 6 a 8 líneas detalladas con dependencias y cifras]\n"
        "- [ídem para CADA tema, ninguno omitido]\n\n"
        "Acuerdos, Compromisos y Nuevos Proyectos (Política de Gasto):\n"
        "- [Acuerdo con dependencia, monto exacto y plazo]\n"
        "- [Lista completa]\n\n"
        "Puntos relevantes y cifras clave:\n"
        "- [Cifra exacta del texto: contexto breve]\n"
        "- [Lista completa]\n\n"
        "Análisis e impacto para la SHCP:\n"
        "[10 a 16 líneas. Describe implicaciones presupuestales concretas con sustento del texto. "
        "No uses frases genéricas. Sé técnico y específico.]\n\n"
        "---\n"
        "VERIFICACIÓN FINAL (HERRAMIENTA INTERNA — PROHIBIDO INCLUIRLA EN LA RESPUESTA):\n"
        "Usa esta lista solo para comprobar tu borrador ANTES de escribir la respuesta final:\n"
        "☐ El nombre de la Presidenta coincide EXACTAMENTE con la versión estenográfica.\n"
        "☐ Los nombres de funcionarios y sus cargos coinciden EXACTAMENTE.\n"
        "☐ Están TODOS los temas sin excepción (ninguno omitido), incluidos carreteras, puertos, igualdad de género y seguridad si aparecen.\n"
        "☐ Las cifras son IDÉNTICAS a las de la transcripción (sin redondeos).\n"
        "☐ Las fechas son IDÉNTICAS.\n"
        "☐ Cada dependencia que presentó información está representada.\n"
        "☐ Cada ítem de Temas abordados tiene 6-8 líneas.\n"
        "☐ Se incluyeron anuncios de preguntas y respuestas y secciones especiales.\n"
        "REGLAS DE ENTREGA:\n"
        "- NO incluyas esta verificación, sus checkmarks, ni ninguna nota tipo \"verificación\" en la respuesta.\n"
        "- Tu respuesta final debe empezar con \"## Resumen Ejecutivo\" y terminar en la sección "
        "\"Análisis e impacto para la SHCP\". Nada después."
    )
    return {"system": system, "user": user, "max_tokens": 4096}


# =========================================================
# PROMPTS — ANÁLISIS DE NOTAS
# =========================================================
def prompt_informe_parcial(idx: int, total: int, fecha_display: str) -> Dict[str, str]:
    """Prompts para generar el resumen parcial de un bloque de la nota."""
    system = _system_prompt_base()
    user = (
        "{bloque}\n\n---\n\n"
        "INSTRUCCIONES: Este es el BLOQUE {idx} de {total} de la nota "
        "del {fecha}. Genera un RESUMEN PARCIAL estructurado y denso de esta sección, "
        "pensado para que otro analista lo consolide después:\n\n"
        "- TEMA(S): lista numerada de los temas del bloque. Incluye TODOS los nombres de "
        "personas con su cargo exacto, dependencias, programas, montos, cifras y fechas "
        "que aparezcan en este bloque. No descartes temas por parecer menores.\n"
        "- LOGROS Y AVANCES: solo lo que aplique en este bloque (quién, qué, cuándo, cifras).\n"
        "- CIFRAS Y DATOS CLAVE: cada cifra con su contexto breve.\n\n"
        "VIGILA ESPECÍFICAMENTE estos sectores y NO los omitas si aparecen en el bloque:\n"
        "- Infraestructura carretera y puentes\n"
        "- Puertos, aduanas y transporte marítimo\n"
        "- Aeropuertos y conectividad\n"
        "- Igualdad de género, derechos de las mujeres y programas sociales\n"
        "- Seguridad, justicia y defensa\n"
        "- Salud, educación, medio ambiente, energía (CFE/PEMEX), agua (CONAGUA), turismo, campo y bienestar\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del bloque proporcionado. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios, dependencias y el de la Presidenta deben coincidir EXACTAMENTE con la nota.\n"
        "- COBERTURA COMPLETA: No omitas ningún tema ni dependencia que haya entregado información.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "- No compactes de más: conserva la información clave de cada tema, nombres y cargos, porque este resumen alimentará la síntesis final.\n"
        "- Respeta el orden de aparición de los temas en el bloque.\n"
        "- Máximo {max_palabras} palabras."
    )
    return {
        "system": system,
        "user": user,
        "max_tokens": 3000,
    }


def prompt_informe_maestro(fecha_display: str) -> Dict[str, str]:
    """Prompts para el resumen maestro del Análisis de notas (reglas de negocio SHCP/UPER)."""
    system = _system_prompt_base()
    user = (
        "{parciales}\n\n---\n\n"
        "INSTRUCCIONES:\n\n"
        "Aplica una metodología de análisis rigurosa de dos fases (Map-Reduce interno) para procesar el texto:\n\n"
        "1. Extrae la fecha de publicación de la nota a partir del texto.\n"
        "2. Mapea la totalidad de la nota extrayendo: temas de política pública, dependencias participantes (SHCP, SEMARNAT, CONAGUA, IMSS, CFE, PEMEX, SICT, SEP, SADER, etc.), programas gubernamentales, anuncios, acuerdos, cifras cuantitativas exactas y resultados reportados.\n"
        "3. Genera la síntesis final aplicando de forma estricta las reglas y la estructura institucional descritas a continuación.\n\n"
        "LEE COMPLETAMENTE TODOS LOS RESUMENES PARCIALES DE PRINCIPIO A FIN. "
        "No empieces a redactar hasta haber procesado el texto completo.\n\n"
        "PASO 1 — Extrae internamente una lista numerada de TODOS los elementos de la Nota:\n"
        "- objetivos y metas del gobierno\n"
        "- temas de política pública, COMO MÍNIMO estos sectores: economía y finanzas públicas; infraestructura carretera y puentes; puertos y aduanas; aeropuertos; igualdad de género; seguridad y justicia; salud; educación; medio ambiente; energía (CFE/PEMEX); agua (CONAGUA); turismo; campo y programas sociales\n"
        "- dependencias mencionadas (SHCP, SEMARNAT, CONAGUA, IMSS, CFE, PEMEX, SICT, SEP, SADER, etc.)\n"
        "- programas gubernamentales y resultados alcanzados\n"
        "- compromisos y avances reportados\n"
        "- cifras y datos cuantitativos (porcentajes, montos, km, habitantes, fechas)\n"
        "- indicadores de desempeño y evaluación\n\n"
        "PASO 2 — Redacta el resumen ejecutivo asegurándote de que CADA elemento de tu lista "
        "aparezca al menos una vez en el Resumen general o en Temas abordados.\n"
        "Si una dependencia presentó resultados, incluye el resumen de su apartado.\n"
        "Integra los nombres de dependencias de forma natural en la narrativa.\n"
        "Cada tema en Temas abordados debe tener 6-8 líneas de descripción detallada.\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del texto fuente. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios, dependencias y el de la Presidenta deben coincidir EXACTAMENTE con la nota.\n"
        "- COBERTURA COMPLETA: No omitas ningún tema ni dependencia que haya entregado información, incluidos los temas carreteros, portuarios, de igualdad de género y de seguridad.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "---\n"
        "### ESTRUCTURA OBLIGATORIA DE ENTREGA\n\n"
        "Entrega ÚNICAMENTE el siguiente documento (comenzando exactamente en la línea de título y finalizando en el Análisis de Impacto, sin texto introductorio ni conclusiones adicionales):\n\n"
        f"## Resumen Ejecutivo – Análisis de nota del {fecha_display}\n\n"
        "Resumen general:\n"
        "[700 a 1200 palabras. Un párrafo detallado por cada eje o tema de la nota. "
        "Menciona las dependencias que reportaron y las cifras exactas. Cubre TODO, "
        "incluidos infraestructura carretera, puertos, igualdad de género y seguridad.]\n\n"
        "Temas abordados:\n"
        "- [Tema 1 — 6 a 8 líneas detalladas con dependencias y cifras]\n"
        "- [Tema 2 — 6 a 8 líneas detalladas con dependencias y cifras]\n"
        "- [ídem para CADA tema, ninguno omitido]\n\n"
        "Resultados y logros destacados:\n"
        "- [Logro 1: dependencia, monto/indicador exacto y resultado]\n"
        "- [Lista completa]\n\n"
        "Puntos relevantes y cifras clave:\n"
        "- [Cifra exacta del texto: contexto breve]\n"
        "- [Lista completa]\n\n"
        "Relevancia para la SHCP:\n"
        "[Evalúa ÚNICAMENTE si algún tema de la nota se relaciona de forma DIRECTA "
        "con las funciones de la SHCP: Presupuesto de Egresos de la Federación (PEF), "
        "política tributaria, deuda pública, gasto público, finanzas públicas, "
        "evaluación de programas, indicadores de desempeño, PbR, gasto federalizado. "
        "NO consideres temas generales sin vínculo directo con la SHCP. "
        "Si ningún tema toca estas áreas, indícalo claramente.]\n\n"
        "Análisis e impacto para la SHCP:\n"
        "[10 a 16 líneas. Describe implicaciones presupuestales y de política fiscal "
        "concretas con sustento del texto. No uses frases genéricas. Sé técnico y específico.]\n\n"
        "---\n"
        "VERIFICACIÓN FINAL (HERRAMIENTA INTERNA — PROHIBIDO INCLUIRLA EN LA RESPUESTA):\n"
        "☐ Los nombres de funcionarios y sus cargos coinciden EXACTAMENTE con la nota.\n"
        "☐ Están TODOS los temas sin excepción (ninguno omitido), incluidos carreteras, puertos, igualdad de género y seguridad si aparecen.\n"
        "☐ Las cifras son IDÉNTICAS a las de la nota (sin redondeos).\n"
        "☐ Las fechas son IDÉNTICAS.\n"
        "☐ Cada dependencia que reportó está representada.\n"
        "☐ Cada ítem de Temas abordados tiene 6-8 líneas.\n"
        "REGLAS DE ENTREGA:\n"
        "- NO incluyas esta verificación, sus checkmarks, ni ninguna nota tipo \"verificación\" en la respuesta.\n"
        "- Tu respuesta final debe empezar con \"## Resumen Ejecutivo\" y terminar en la sección "
        "\"Análisis e impacto para la SHCP\". Nada después."
    )
    return {"system": system, "user": user, "max_tokens": 4096}


def procesar_informe(
    texto: str,
    fecha: datetime,
    block_providers: Optional[List[str]] = None,
    master_provider: str = "Groq",
    keys: Optional[Dict[str, str]] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    on_uso: Optional[Callable[[str, str, bool, str], None]] = None,
) -> str:
    """
    Pipeline map-reduce para el Análisis de notas.
    Misma arquitectura que procesar_conferencia pero con prompts adaptados.
    """
    keys = keys or {}
    fecha_display = fecha.strftime("%d/%m/%Y")
    bloques = dividir_en_bloques(texto)
    n = len(bloques)

    if on_uso is None:
        def on_uso(*_a, **_k):
            pass

    if n == 0:
        return "Error: No hay texto para resumir."

    providers_lista = block_providers or ["Groq"]
    agentes_disponibles: List[tuple] = []
    for prov in providers_lista:
        agentes_disponibles.extend(_agentes_para_provider(prov, keys))

    def _resumir_bloque(i: int):
        return _generar_bloque(i, bloques, agentes_disponibles, prompt_informe_parcial, fecha_display)

    parciales: List[str] = [""] * n
    if on_progress:
        on_progress(5)

    max_workers = min(n, max(len(agentes_disponibles), 1), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = [pool.submit(_resumir_bloque, i) for i in range(n)]
        done = 0
        for fut in as_completed(futuros):
            i, res, proveedor = fut.result()
            parciales[i] = res
            if proveedor:
                on_uso("bloque", proveedor, True)
            done += 1
            if on_progress:
                pct = 5 + int(done / n * 60)
                on_progress(pct)

    fallos = [r for r in parciales if _es_error(r)]
    if len(fallos) == n:
        return f"Error: No se pudo generar el resumen de bloques. {fallos[0]}"

    prompt = prompt_informe_maestro(fecha_display)
    return _consolidar_parciales(
        parciales, fecha_display, keys, master_provider, prompt,
        on_uso=on_uso, on_progress=on_progress,
    )


# =========================================================
# PROMPTS — NOTAS PERIODÍSTICAS
# =========================================================
def prompt_notas_parcial(idx: int, total: int, fecha_display: str) -> Dict[str, str]:
    """Prompts para generar el resumen parcial de un bloque de notas periodísticas."""
    system = _system_prompt_base()
    user = (
        "{bloque}\n\n---\n\n"
        "INSTRUCCIONES: Este es el BLOQUE {idx} de {total} de las notas periodísticas "
        "recopiladas el {fecha}. Cada nota inicia con su título y fuente. Genera un "
        "RESUMEN PARCIAL estructurado y denso de esta sección, pensado para que otro "
        "analista lo consolide después:\n\n"
        "- TEMA(S): lista numerada de los temas de las notas de este bloque, indicando a "
        "qué nota pertenece cada uno (usa el título exacto de la nota). Incluye TODOS los "
        "nombres de personas con su cargo exacto, dependencias, programas, montos, cifras "
        "y fechas que aparezcan.\n"
        "- HECHOS CLAVE: qué ocurrió, quién lo dijo o hizo, cuándo y dónde, por nota.\n"
        "- CIFRAS Y DATOS CLAVE: cada cifra con su contexto breve.\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del bloque proporcionado. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios y dependencias deben coincidir EXACTAMENTE con la nota.\n"
        "- COBERTURA COMPLETA: No omitas ninguna nota ni tema relevante del bloque.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "- No compactes de más: conserva la información clave de cada nota, nombres y cargos, porque este resumen alimentará la síntesis final.\n"
        "- Respeta el orden de aparición de las notas en el bloque.\n"
        "- Máximo {max_palabras} palabras."
    )
    return {
        "system": system,
        "user": user,
        "max_tokens": 3000,
    }


def prompt_notas_maestro(fecha_display: str) -> Dict[str, str]:
    """Prompts para el resumen maestro de Notas Periodísticas (reglas de negocio SHCP/UPER)."""
    system = _system_prompt_base()
    user = (
        "{parciales}\n\n---\n\n"
        "INSTRUCCIONES:\n\n"
        "Consolida los resúmenes parciales de las notas periodísticas en UNA síntesis "
        "ejecutiva única. Identifica los temas comunes entre notas, evita repetir la misma "
        "información dos veces y organiza el contenido priorizando lo más relevante para "
        "la SHCP.\n\n"
        "LEE COMPLETAMENTE TODOS LOS RESÚMENES PARCIALES DE PRINCIPIO A FIN. "
        "No empieces a redactar hasta haber procesado el texto completo.\n\n"
        "PASO 1 — Extrae internamente una lista numerada de TODOS los temas y notas cubiertos.\n"
        "PASO 2 — Redacta el resumen ejecutivo asegurándote de que CADA tema relevante "
        "aparezca al menos una vez en el Resumen general o en Temas abordados. Cuando sea "
        "útil para el lector, identifica de qué nota proviene cada tema usando su título "
        "exacto dentro de la narrativa.\n\n"
        "### REGLAS NORMATIVAS Y ESTRICTAS (SHCP/UPER)\n"
        "- NO INVENTES NADA: Extrae información únicamente del texto fuente. No uses conocimiento previo.\n"
        "- FIDELIDAD DE CIFRAS Y DATOS: Mantén exactamente los valores y fechas reportados. PROHIBIDO redondear o simplificar montos (ejemplo: escribe \"2,635 millones\", NUNCA \"2 mil millones\" o \"más de 2,000 millones\").\n"
        "- NOMBRES Y CARGOS: Los nombres de funcionarios y dependencias deben coincidir EXACTAMENTE con las notas.\n"
        "- COBERTURA COMPLETA: No omitas ninguna nota ni tema relevante.\n"
        "- TONO Y ESTILO: Técnico, objetivo, formal y exhaustivo.\n"
        "- NO incluyas enlaces, URLs ni una lista de fuentes en tu respuesta: esa lista se agrega por separado, automáticamente, después de tu resumen.\n"
        "---\n"
        "### ESTRUCTURA OBLIGATORIA DE ENTREGA\n\n"
        "Entrega ÚNICAMENTE el siguiente documento (comenzando exactamente en la línea de título y finalizando en el Análisis e impacto, sin texto introductorio ni conclusiones adicionales, y SIN lista de fuentes/enlaces):\n\n"
        f"## Resumen Ejecutivo – Síntesis de Notas Periodísticas del {fecha_display}\n\n"
        "Resumen general:\n"
        "[500 a 900 palabras. Un párrafo detallado por cada tema relevante cubierto por las "
        "notas. Menciona las dependencias, funcionarios y cifras exactas mencionadas.]\n\n"
        "Temas abordados:\n"
        "- [Tema 1 — 4 a 6 líneas detalladas con dependencias, nombres y cifras]\n"
        "- [Tema 2 — 4 a 6 líneas detalladas con dependencias, nombres y cifras]\n"
        "- [ídem para CADA tema relevante, ninguno omitido]\n\n"
        "Puntos relevantes y cifras clave:\n"
        "- [Cifra exacta del texto: contexto breve]\n"
        "- [Lista completa]\n\n"
        "Análisis e impacto para la SHCP:\n"
        "[8 a 14 líneas. Describe implicaciones presupuestales o de política fiscal "
        "concretas con sustento del texto, si las hay. No uses frases genéricas. Sé técnico "
        "y específico. Si ninguna nota se relaciona con la SHCP, indícalo claramente.]\n\n"
        "---\n"
        "VERIFICACIÓN FINAL (HERRAMIENTA INTERNA — PROHIBIDO INCLUIRLA EN LA RESPUESTA):\n"
        "Usa esta lista solo para comprobar tu borrador ANTES de escribir la respuesta final:\n"
        "☐ Los nombres de funcionarios y sus cargos coinciden EXACTAMENTE con las notas.\n"
        "☐ Están TODOS los temas relevantes sin excepción.\n"
        "☐ Las cifras son IDÉNTICAS a las de las notas (sin redondeos).\n"
        "☐ Las fechas son IDÉNTICAS.\n"
        "☐ NO incluí enlaces, URLs ni una lista de fuentes.\n"
        "REGLAS DE ENTREGA:\n"
        "- NO incluyas esta verificación, sus checkmarks, ni ninguna nota tipo \"verificación\" en la respuesta.\n"
        "- Tu respuesta final debe empezar con \"## Resumen Ejecutivo\" y terminar en la sección "
        "\"Análisis e impacto para la SHCP\". Nada después."
    )
    return {"system": system, "user": user, "max_tokens": 4096}


def procesar_notas(
    texto: str,
    fecha: datetime,
    block_providers: Optional[List[str]] = None,
    master_provider: str = "Groq",
    keys: Optional[Dict[str, str]] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    on_uso: Optional[Callable[[str, str, bool, str], None]] = None,
) -> str:
    """
    Pipeline map-reduce para la Síntesis de Notas Periodísticas.
    Misma arquitectura que procesar_informe pero con prompts adaptados a notas.
    """
    keys = keys or {}
    fecha_display = fecha.strftime("%d/%m/%Y")
    bloques = dividir_en_bloques(texto)
    n = len(bloques)

    if on_uso is None:
        def on_uso(*_a, **_k):
            pass

    if n == 0:
        return "Error: No hay texto para resumir."

    providers_lista = block_providers or ["Groq"]
    agentes_disponibles: List[tuple] = []
    for prov in providers_lista:
        agentes_disponibles.extend(_agentes_para_provider(prov, keys))

    def _resumir_bloque(i: int):
        return _generar_bloque(i, bloques, agentes_disponibles, prompt_notas_parcial, fecha_display)

    parciales: List[str] = [""] * n
    if on_progress:
        on_progress(5)

    max_workers = min(n, max(len(agentes_disponibles), 1), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = [pool.submit(_resumir_bloque, i) for i in range(n)]
        done = 0
        for fut in as_completed(futuros):
            i, res, proveedor = fut.result()
            parciales[i] = res
            if proveedor:
                on_uso("bloque", proveedor, True)
            done += 1
            if on_progress:
                pct = 5 + int(done / n * 60)
                on_progress(pct)

    fallos = [r for r in parciales if _es_error(r)]
    if len(fallos) == n:
        return f"Error: No se pudo generar el resumen de bloques. {fallos[0]}"

    prompt = prompt_notas_maestro(fecha_display)
    return _consolidar_parciales(
        parciales, fecha_display, keys, master_provider, prompt,
        on_uso=on_uso, on_progress=on_progress,
    )


# =========================================================
# FÁBRICA DE AGENTES
# =========================================================
def _keys_del_provider(keys: Dict[str, str], base: str) -> List[str]:
    """Devuelve todas las keys del provider presentes en el dict (base, base_2, base_3, ...)."""
    return [v for k, v in keys.items() if v and (k == base or k.startswith(base + "_"))]


def _agentes_para_provider(provider: str, keys: Dict[str, str]) -> List[tuple]:
    """Retorna una tupla (nombre, agente) por CADA key del provider.

    Las múltiples keys se usan en round-robin para los bloques (más keys = más
    paralelismo). La concurrencia por provider se limita con un semáforo
    (_MAX_CONCURRENTES_PROVIDER) para no saturar los límites por cuenta.
    """
    if provider == "Gemini (gratis)":
        return [("Gemini", GeminiAgent(k)) for k in _keys_del_provider(keys, "gemini")]
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        base = provider.lower()
        return [(provider, OpenAICompatAgent(preset["base_url"], k, preset["model"])) for k in _keys_del_provider(keys, base)]
    if provider == "Ollama (local)":
        ag = OllamaAgent()
        if ag.is_available:
            return [("Ollama", ag)]
    return []


_MAX_CONCURRENTES_PROVIDER = 2
_CAP_CONCURRENTES = {"Groq": 2, "OpenRouter": 2, "Gemini": 3, "Ollama": 1}
_semaforos_provider: Dict[str, threading.Semaphore] = {}

# Cooldowns por provider: al recibir cuota/rate-limit (429) se espera 45s antes
# de volver a intentarlo, en vez de descartarlo por toda la corrida (se auto-recupera).
_COOLDOWN_QUOTA_S = 45
_cooldowns_until: Dict[str, float] = {}


def _en_cooldown(nombre: str) -> bool:
    return _time.monotonic() < _cooldowns_until.get(nombre, 0)


def _marcar_cooldown(nombre: str, segundos: int = _COOLDOWN_QUOTA_S):
    _cooldowns_until[nombre] = _time.monotonic() + segundos


def _semaforo_provider(nombre: str) -> threading.Semaphore:
    sem = _semaforos_provider.get(nombre)
    if sem is None:
        cap = _CAP_CONCURRENTES.get(nombre, _MAX_CONCURRENTES_PROVIDER)
        sem = _semaforos_provider[nombre] = threading.Semaphore(cap)
    return sem


def _generar_bloque(i: int, bloques: List[str], agentes: List[tuple], prompt_fn: Callable, fecha_display: str) -> tuple:
    """Genera el resumen parcial del bloque i probando cada agente en round-robin
    (con rotación para repartir las keys) y respetando el límite de concurrencia
    por provider (semáforo). Retorna (i, resumen, proveedor) o (i, error, None).

    Los providers con cuota agotada entran en cooldown (45s) y se omiten hasta
    que se recuperen, para no quemar intentos ni dejar de usarlos toda la corrida.
    """
    n = len(bloques)
    bloque = bloques[i]
    n_agentes = len(agentes)
    if n_agentes == 0:
        # Sin ningún proveedor de IA disponible (ni siquiera Ollama local):
        # se usa un resumen extractivo (oraciones reales del texto, sin IA).
        res = resumen_extractivo(bloque, max_palabras=PALABRAS_MAX_PARCIAL)
        return i, res, "Extractivo (sin IA)"

    prompt = prompt_fn(i + 1, n, fecha_display)
    user = prompt["user"].format(
        bloque=bloque, idx=i + 1, total=n,
        fecha=fecha_display, max_palabras=PALABRAS_MAX_PARCIAL,
    )
    ultimo_error = ""
    for offset in range(n_agentes):
        prov_name, agente = agentes[(i + offset) % n_agentes]
        if _en_cooldown(prov_name):
            continue
        if not _semaforo_provider(prov_name).acquire(timeout=300):
            continue
        try:
            res = _llamar(agente, prompt["system"], user, prompt["max_tokens"], timeout=120)
        finally:
            _semaforo_provider(prov_name).release()
        if not _es_error(res):
            return i, res, prov_name
        if _es_cuota(res):
            _marcar_cooldown(prov_name)
            continue
        ultimo_error = res
    return i, f"[Bloque {i+1}/{n} omitido: {ultimo_error}]", None


def agente_bloques(provider: str, keys: Dict[str, str]) -> Optional[object]:
    """Crea el agente para la fase de bloques, o None si no está configurado."""
    if provider == "Gemini (gratis)":
        key = keys.get("gemini", "")
        if not key:
            return None
        return GeminiAgent(key)
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        key = keys.get(provider.lower(), "")
        if not key:
            return None
        return OpenAICompatAgent(preset["base_url"], key, preset["model"])
    if provider == "Ollama (local)":
        return OllamaAgent()
    return None


def agente_maestro(provider: str, keys: Dict[str, str]) -> Optional[object]:
    """Crea el agente para la fase maestra."""
    if provider == "Gemini (gratis)":
        key = keys.get("gemini", "")
        if not key:
            return None
        return GeminiAgent(key)
    if provider == "Anthropic Claude":
        key = keys.get("anthropic", "")
        if not key:
            return None
        return AnthropicAgent(key)
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        key = keys.get(provider.lower(), "")
        if not key:
            return None
        return OpenAICompatAgent(preset["base_url"], key, preset["model"])
    if provider == "Ollama (local)":
        return OllamaAgent()
    return None


def _llamar(agente, system: str, user: str, max_tokens: int, on_progress=None, timeout: int = 180) -> str:
    """Llama al agente con la interfaz común (generar_resumen) con timeout."""
    if getattr(agente, "is_available", True) is False:
        return "Error: Agente de IA no disponible."
    if hasattr(agente, "_call_ollama_streaming"):
        return agente._call_ollama_streaming(
            system, user, max_tokens=max_tokens, temperature=0.3, on_progress=on_progress
        )

    def _ejecutar():
        return agente.generar_resumen(system, user, max_tokens=max_tokens)

    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(_ejecutar)
        try:
            return futuro.result(timeout=timeout)
        except Exception:
            return f"Error: Timeout o fallo con {getattr(agente, 'label', type(agente).__name__)}"


def _generar_maestro(agente, prompt_system, prompt_user, max_tokens, on_progress=None, reintentos=3, timeout=120):
    """Llama al maestro con reintentos solo para errores transitorios (503/timeout).

    La cuota agotada (429/quota/rate-limit) NO se reintenta: no se libera en
    segundos, y conviene fallar rápido para que la cascada pruebe otra key o
    proveedor. Incluye un "pulse" de progreso durante llamadas largas.
    """
    import time as _time
    stop_pulse = threading.Event()
    if on_progress is not None:
        def _pulse():
            pct = 5
            try:
                while not stop_pulse.is_set():
                    stop_pulse.wait(4)
                    if stop_pulse.is_set():
                        break
                    pct = min(pct + 15, 90)
                    on_progress(pct)
            except Exception:
                pass
        threading.Thread(target=_pulse, daemon=True).start()
    try:
        for intento in range(reintentos):
            res = _llamar(agente, prompt_system, prompt_user, max_tokens, timeout=timeout)
            if not _es_error(res):
                return res
            low = (res or "").lower()
            if "quota" in low or "rate limit" in low or "429" in low:
                return res
            if "503" in low or "timeout" in low:
                _time.sleep(3 * (intento + 1))
                continue
            return res
    finally:
        stop_pulse.set()
    return res


def _agentes_para_maestro(provider: str, keys: Dict[str, str]) -> List[tuple]:
    """Tuplas (nombre, agente) con TODAS las keys del provider para el maestro."""
    if provider == "Gemini (gratis)":
        return [("Gemini", GeminiAgent(k)) for k in _keys_del_provider(keys, "gemini")]
    if provider == "Anthropic Claude":
        k = keys.get("anthropic", "")
        return [("Anthropic Claude", AnthropicAgent(k))] if k else []
    if provider == "Ollama (local)":
        ag = OllamaAgent()
        return [("Ollama", ag)] if ag.is_available else []
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        base = provider.lower()
        return [(provider, OpenAICompatAgent(preset["base_url"], k, preset["model"])) for k in _keys_del_provider(keys, base)]
    return []


PROMPT_FUSION_SISTEMA = (
    "Eres un analista senior de la SHCP. Consolida varios resúmenes parciales en "
    "UN resumen parcial único, denso y estructurado, SIN omitir ningún tema, nombre "
    "de funcionario con cargo, dependencia, cifra o fecha. Máximo 500 palabras."
)


def _fusionar_parciales(parciales_grupo: List[str], keys, master_provider, on_uso, on_progress) -> str:
    cuerpo = "\n\n".join(f"{i + 1}. {p}" for i, p in enumerate(parciales_grupo))
    user = f"{PROMPT_FUSION_SISTEMA}\n\nResúmenes parciales a consolidar:\n\n{cuerpo}"

    def _prog_fusion(pct):
        if on_progress:
            on_progress(min(70 + int(pct / 100 * 10), 80))

    realizados = 0
    for provider in cadena_maestro_providers(master_provider):
        for nombre, agente in _agentes_para_maestro(provider, keys):
            if _en_cooldown(nombre):
                continue
            if not _semaforo_provider(nombre).acquire(timeout=240):
                continue
            realizados += 1
            try:
                res = _generar_maestro(agente, PROMPT_FUSION_SISTEMA, user, 2048, on_progress=_prog_fusion)
            finally:
                _semaforo_provider(nombre).release()
            if not _es_error(res):
                on_uso("fusion", nombre, True)
                return res
            if _es_cuota(res):
                _marcar_cooldown(nombre)
                continue
            on_uso("fusion", nombre, False, res)
            if on_progress:
                on_progress(min(74 + realizados * 2, 83))
    return ""


def _consolidar_extractivo(buenos: List[str], fecha_display: str) -> str:
    """Consolidación sin IA: reduce los parciales (ya extractivos o narrativos)
    a un documento único mediante TextRank, sin generar texto nuevo. Último
    respaldo cuando ningún proveedor de IA (ni Ollama) respondió."""
    cuerpo = "\n\n".join(buenos)
    resumen_general = resumen_extractivo(cuerpo, max_palabras=600) or cuerpo[:2000]
    temas = "\n".join(f"- {resumen_extractivo(p, max_palabras=60) or p[:200]}" for p in buenos)
    return (
        f"## Resumen Ejecutivo (extractivo, sin IA) del {fecha_display}\n\n"
        "Resumen general:\n"
        f"{resumen_general}\n\n"
        "Temas abordados:\n"
        f"{temas}\n\n"
        "Nota: ningún proveedor de IA (ni Ollama local) estaba disponible al generar "
        "este documento. Las líneas anteriores son oraciones extraídas directamente "
        "del texto original (sin generación de contenido nuevo)."
    )


def _consolidar_parciales(parciales, fecha_display, keys, master_provider, prompt_final, on_uso, on_progress) -> str:
    """Reduce los resúmenes parciales al resumen ejecutivo final.

    Estrategia "directo primero": se intenta el maestro con TODO el contenido
    (Gemini aguanta contextos grandes) para no multiplicar llamadas. Solo si
    falla en todos los proveedores disponibles, se hacen rondas de fusión
    jerárquica para reducir el prompt. Prueba TODAS las keys de cada proveedor
    y no insiste en providers con cuota agotada.
    """
    buenos = [p for p in parciales if not _es_error(p)]
    if not buenos:
        return "Error: Ningún bloque generó contenido para consolidar."

    def _prog_master(pct):
        if on_progress:
            on_progress(min(70 + int(pct / 100 * 25), 95))

    def _intentar_final(cuerpo: str):
        user = prompt_final["user"].format(parciales=cuerpo)
        ultimo = "sin agentes maestros configurados"
        realizados = 0
        for provider in cadena_maestro_providers(master_provider):
            for nombre, agente in _agentes_para_maestro(provider, keys):
                if _en_cooldown(nombre):
                    continue
                if not _semaforo_provider(nombre).acquire(timeout=240):
                    continue
                realizados += 1
                try:
                    res = _generar_maestro(agente, prompt_final["system"], user, prompt_final["max_tokens"], on_progress=_prog_master, timeout=90)
                finally:
                    _semaforo_provider(nombre).release()
                ultimo = f"{nombre}: {res}"
                if not _es_error(res):
                    on_uso("maestro", nombre, True)
                    if on_progress:
                        on_progress(100)
                    return _quitar_verificacion_final(res), ultimo
                if _es_cuota(res):
                    _marcar_cooldown(nombre)
                    continue
                on_uso("maestro", nombre, False, res)
                if on_progress:
                    on_progress(min(72 + realizados * 2, 94))
        return None, ultimo

    # PASO 1: intento directo con TODO el contenido de los parciales, SOLO si
    # cabe en el límite del prompt maestro. Con los parciales actuales (hasta
    # 650 palabras c/u) una mañanera completa excede el límite, así que se va
    # directo a la fusión jerárquica para no disparar prompts gigantes que
    # fallen por contexto o se queden colgados en timeouts.
    if on_progress:
        on_progress(70)
    cuerpo_completo = "\n\n".join(f"### Resumen parcial {i + 1}/{len(buenos)}\n{p}" for i, p in enumerate(buenos))
    if len(cuerpo_completo) <= MAX_CHARS_MAESTRO or len(buenos) <= 2:
        res, ultimo = _intentar_final(cuerpo_completo)
        if res is not None:
            return res
        if ultimo == "sin agentes maestros configurados":
            return _consolidar_extractivo(buenos, fecha_display)
        return f"Error: No se pudo generar el resumen final. {ultimo}"

    # PASO 2: respaldo — rondas de fusión jerárquica para reducir el prompt
    ronda = 0
    while len(buenos) > 2:
        cuerpo = "\n\n".join(f"### Resumen parcial {i + 1}/{len(buenos)}\n{p}" for i, p in enumerate(buenos))
        if len(cuerpo) <= MAX_CHARS_MAESTRO:
            break
        grupos = []
        grupo, largo = [], 0
        for p in buenos:
            if grupo and largo + len(p) > int(MAX_CHARS_MAESTRO * 0.9):
                grupos.append(grupo)
                grupo, largo = [], 0
            grupo.append(p)
            largo += len(p)
        if grupo:
            grupos.append(grupo)
        if len(grupos) == 1:
            break
        nuevos = []
        for g in grupos:
            if len(g) == 1:
                nuevos.append(g[0])
                continue
            f = _fusionar_parciales(g, keys, master_provider, on_uso, on_progress)
            nuevos.append(f if not _es_error(f) else "\n".join(g))
        buenos = nuevos
        ronda += 1
        if on_progress:
            on_progress(min(70 + ronda * 4, 84))

    cuerpo = "\n\n".join(f"### Resumen parcial {i + 1}/{len(buenos)}\n{p}" for i, p in enumerate(buenos))
    res, ultimo = _intentar_final(cuerpo)
    if res is not None:
        return res
    if ultimo == "sin agentes maestros configurados":
        return _consolidar_extractivo(buenos, fecha_display)
    return f"Error: No se pudo generar el resumen final. {ultimo}"


def _es_cuota(res: str) -> bool:
    """True si el error indica cuota/rate-limit agotado (conviene no reintentar)."""
    if res is None:
        return False
    low = res.lower()
    return "quota" in low or "rate limit" in low or "429" in low or "resource_exhausted" in low


def _es_error(res: str) -> bool:
    if res is None or res.strip() == "" or res == "__QUOTA_EXCEEDED__":
        return True
    low = res.lstrip().lower()
    return low.startswith("error") or low.startswith("[bloque")


def _quitar_verificacion_final(res: str) -> str:
    """Elimina una sección 'Verificación Final' que la IA incluya en la respuesta.

    Solo corta si el encabezado aparece hacia el final del texto, para no dañar
    frases narrativas que contengan la expresión en medio del resumen.
    """
    if not res:
        return res
    lineas = res.splitlines()
    total = len(lineas)
    for i, linea in enumerate(lineas):
        if "verificación final" in linea.lower():
            if total == 0 or i >= total * 0.6:
                partes = lineas[:i]
                while partes and not partes[-1].strip():
                    partes.pop()
                if partes and set(partes[-1].strip()) <= {"-", "*", "_"}:
                    partes.pop()
                return "\n".join(partes).rstrip()
    return res


def cadena_maestro_providers(primario: str) -> List[str]:
    """Orden de proveedores maestros: primero la selección del usuario, luego la cascada."""
    return [primario] + [p for p in CADENA_MAESTRO if p != primario]


# =========================================================
# ORQUESTADOR
# =========================================================
def procesar_conferencia(
    texto: str,
    fecha: datetime,
    block_provider: str = "Groq",
    block_providers: Optional[List[str]] = None,
    master_provider: str = "Gemini (gratis)",
    keys: Optional[Dict[str, str]] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    on_uso: Optional[Callable[[str, str, bool, str], None]] = None,
) -> str:
    """
    Ejecuta el pipeline map-reduce completo.
    Retorna el resumen final o un string que inicia con "Error:".

    on_uso(fase, proveedor, ok, detalle) se invoca cada vez que se usa (o se
    descarta) una IA: fase "bloque" (por cada bloque) o "maestro" (cada intento
    de la cascada). detalle = "" en éxito, "sin key" si no hay clave, o el error.
    """
    keys = keys or {}
    fecha_display = fecha.strftime("%d/%m/%Y")
    bloques = dividir_en_bloques(texto)
    n = len(bloques)

    if on_uso is None:
        def on_uso(*_a, **_k):
            pass

    if n == 0:
        return "Error: No hay texto para resumir."

    # ---- Construir lista de agentes para bloques (round-robin con todas las keys) ----
    providers_lista = block_providers or [block_provider]
    agentes_disponibles: List[tuple] = []  # (provider_name, agente)
    for prov in providers_lista:
        agentes_disponibles.extend(_agentes_para_provider(prov, keys))

    def _resumir_bloque(i: int):
        return _generar_bloque(i, bloques, agentes_disponibles, prompt_parcial, fecha_display)

    # ---- FASE 1: bloques en paralelo ----
    parciales: List[str] = [""] * n
    usados: List[str] = [""] * n
    if on_progress:
        on_progress(5)

    max_workers = min(n, max(len(agentes_disponibles), 1), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = [pool.submit(_resumir_bloque, i) for i in range(n)]
        done = 0
        for fut in as_completed(futuros):
            i, res, proveedor = fut.result()
            parciales[i] = res
            if proveedor:
                on_uso("bloque", proveedor, True)
            done += 1
            if on_progress:
                pct = 5 + int(done / n * 60)
                on_progress(pct)

    # Si TODOS los bloques fallaron
    fallos = [r for r in parciales if _es_error(r)]
    if len(fallos) == n:
        return f"Error: No se pudo generar el resumen de bloques. {fallos[0]}"

    # ---- FASE 2: resumen maestro con cascada de respaldo ----
    prompt = prompt_maestro(fecha_display)
    return _consolidar_parciales(
        parciales, fecha_display, keys, master_provider, prompt,
        on_uso=on_uso, on_progress=on_progress,
    )
