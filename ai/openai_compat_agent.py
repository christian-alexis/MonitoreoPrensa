"""
Agente genérico para proveedores compatibles con la API de OpenAI
(/chat/completions). Cubre Groq, Cerebras y OpenRouter con una sola clase.
"""
from typing import Optional

import requests


PROVIDER_PRESETS = {
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "qwen/qwen3.8-27b",
        "label": "Groq (Qwen 3.8 27B)",
    },
    "Cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "model": "gpt-oss-120b",
        "label": "Cerebras (GPT-OSS 120B)",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat-v3-0324",
        "label": "OpenRouter (DeepSeek V3)",
    },
}


class OpenAICompatAgent:
    """Agente OpenAI-compatible parametrizado por base_url/api_key/modelo."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 300,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout
        self._ok = bool(self.base_url and self.api_key and self.model)

    @property
    def is_available(self) -> bool:
        return self._ok

    @property
    def label(self) -> str:
        return f"{self.base_url.split('//')[-1].split('.')[0]} ({self.model})"

    def _call(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        if not self._ok:
            return "Error: Falta API key o configuración del proveedor."

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://shcp-local.app"
            headers["X-Title"] = "SHCP - Resumen Conferencia Matutina"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code != 200:
                err = data.get("error", {})
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
                low = msg.lower()
                if resp.status_code == 429 or "quota" in low or "rate limit" in low or "insufficient_quota" in low:
                    return "__QUOTA_EXCEEDED__"
                return f"Error con {self.label}: {resp.status_code} {msg}"
            content = data["choices"][0]["message"]["content"]
            return content if content else "Sin respuesta"
        except requests.RequestException as e:
            return f"Error de conexión con {self.label}: {e}"
        except (KeyError, IndexError, TypeError) as e:
            return f"Error al procesar respuesta de {self.label}: {e}"

    def generar_resumen(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        return self._call(system_prompt, user_message, max_tokens=max_tokens)
