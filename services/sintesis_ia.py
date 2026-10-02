"""
Cascada de IA para la Síntesis de Noticias.

Recorre los proveedores disponibles en orden (primero la selección del usuario,
luego la cascada) y ejecuta la operación con el primer agente que funcione:
Gemini → Anthropic → OpenRouter → Cerebras → Groq → Ollama local.
Ollama queda al final: el servidor de producción no tiene RAM suficiente para
correrlo (ver services/resumen_mananera.py), así que las APIs gratuitas con
key van primero.
"""
from typing import Callable, Dict, List, Optional

from ai.anthropic_agent import AnthropicAgent
from ai.gemini_agent import GeminiAgent
from ai.news_agent import NewsAgent
from ai.ollama_agent import OllamaAgent
from ai.openai_compat_agent import OpenAICompatAgent, PROVIDER_PRESETS

CADENA_IA = [
    "Gemini (gratis)",
    "Anthropic Claude",
    "OpenRouter",
    "Cerebras",
    "Groq",
    "Ollama (local)",
]


def cadena_providers(primario: str) -> List[str]:
    """Orden de proveedores: primero la selección del usuario, luego la cascada."""
    return [primario] + [p for p in CADENA_IA if p != primario]


def crear_backend(provider: str, keys: Dict[str, str]) -> Optional[object]:
    """Crea el proveedor de IA (backend), o None si no tiene key/configuración."""
    if provider == "Gemini (gratis)":
        key = keys.get("gemini", "")
        return GeminiAgent(key) if key else None
    if provider == "Anthropic Claude":
        key = keys.get("anthropic", "")
        return AnthropicAgent(key) if key else None
    if provider == "Ollama (local)":
        return OllamaAgent()
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        key = keys.get(provider.lower(), "")
        if not key:
            return None
        return OpenAICompatAgent(preset["base_url"], key, preset["model"])
    return None


def _es_error(res) -> bool:
    """Detecta errores en strings o dicts (resumen/razonamiento)."""
    if res is None:
        return True
    if isinstance(res, dict):
        for campo in ("resumen", "razonamiento"):
            v = res.get(campo)
            if isinstance(v, str) and (not v.strip() or v.lstrip().lower().startswith("error")):
                return True
        return False
    if not isinstance(res, str):
        return False
    if res.strip() == "" or res == "__QUOTA_EXCEEDED__":
        return True
    return res.lstrip().lower().startswith("error")


def ejecutar_cascada(
    operacion: str,
    primario: str,
    keys: Dict[str, str],
    on_uso: Optional[Callable[[str, str, bool, str], None]] = None,
    *args,
):
    """Ejecuta la operación sobre el primer proveedor disponible que funcione.

    Retorna (resultado, proveedor) o (None, None) si ninguno funcionó.
    on_uso(operacion, proveedor, ok, detalle) se invoca por cada intento.
    """
    for provider in cadena_providers(primario):
        backend = crear_backend(provider, keys)
        if backend is None:
            if on_uso:
                on_uso(operacion, provider, False, "sin key")
            continue
        agente = NewsAgent(backend, provider)
        if not agente.is_available:
            if on_uso:
                on_uso(operacion, provider, False, "no disponible")
            continue
        try:
            metodo = getattr(agente, operacion)
            resultado = metodo(*args)
        except Exception as e:
            if on_uso:
                on_uso(operacion, provider, False, f"excepción: {e}")
            continue
        if _es_error(resultado):
            if on_uso:
                detalle = resultado if isinstance(resultado, str) else str(resultado)
                on_uso(operacion, provider, False, detalle[:120])
            continue
        if on_uso:
            on_uso(operacion, provider, True)
        return resultado, provider
    return None, None
