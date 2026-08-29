"""Backends de chat interpolables.

Esta es la unica pieza que "habla con un proveedor de IA". La capa A2A
(server.py) nunca sabe si detras hay OpenAI, Anthropic, un LLM local o un
echo fijo: solo conoce la interfaz `ChatBackend`.

Para verificar el protocolo sin gastar tokens, usa `provider="echo"`
(CHAT_PROVIDER=echo). Para produccion usa "openai" o escribe tu propio backend.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, Dict, List, Protocol

from .protocol import parts_to_text


class ChatBackend(Protocol):
    """Interfaz minima que debe implementar un proveedor de chat."""

    async def chat(self, *, system: str, history: List[Dict[str, Any]]) -> str: ...

    def stream(
        self, *, system: str, history: List[Dict[str, Any]]
    ) -> AsyncIterator[str]: ...


def history_to_openai(history: List[Dict[str, Any]], system: str) -> List[Dict[str, str]]:
    """Convierte history A2A (role user/agent + parts) al formato chat de OpenAI.

    Nota: aqui es donde se "puentea" el modelo de mensajes A2A al modelo de
    mensajes del proveedor. Es la misma traduccion que hace LangGraph entre
    su estado `messages` y el wire format A2A (pero transparente).
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for m in history:
        content = parts_to_text(m.get("parts", []))
        if not content:
            continue
        role = "user" if m.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": content})
    return messages


class OpenAIBackend:
    """Backend real usando el cliente oficial de OpenAI (async, con streaming)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.7):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def chat(self, *, system: str, history: List[Dict[str, Any]]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=history_to_openai(history, system),
            temperature=self._temperature,
        )
        return response.choices[0].message.content or ""

    def stream(self, *, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        return self._stream(system, history)

    async def _stream(self, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=history_to_openai(history, system),
            temperature=self._temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


class EchoBackend:
    """Backend de prueba: devuelve un echo del ultimo mensaje.

    Muy util para (1) verificar el protocolo sin API key y (2) demostrar la
    interoperabilidad Python<->TypeScript con un costo determinista.
    """

    def __init__(self, prefix: str = "Agent"):
        self._prefix = prefix

    def _last_text(self, history: List[Dict[str, Any]]) -> str:
        return parts_to_text(history[-1].get("parts", [])) if history else ""

    async def chat(self, *, system: str, history: List[Dict[str, Any]]) -> str:
        return f"{self._prefix} echo: {self._last_text(history)}"

    def stream(self, *, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        return self._stream(system, history)

    async def _stream(self, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        text = await self.chat(system=system, history=history)
        for char in text:
            yield char


def build_backend(
    provider: str = "openai",
    *,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
    agent_name: str = "Agent",
) -> ChatBackend:
    """Factory que elige backend segun configuracion (env CHAT_PROVIDER)."""
    if provider == "echo":
        return EchoBackend(prefix=agent_name)
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "provider=openai requiere OPENAI_API_KEY (o usa CHAT_PROVIDER=echo para pruebas)"
        )
    return OpenAIBackend(api_key=key, model=model)