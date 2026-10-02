"""
Agente de IA usando Anthropic Claude API.
"""
import anthropic


class AnthropicAgent:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.modelo = "claude-sonnet-4-20250514"

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def generar_resumen(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        try:
            response = self.client.messages.create(
                model=self.modelo,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except Exception as e:
            return f"Error con Anthropic API: {e}"
