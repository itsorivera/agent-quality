"""Puerto driven (contrato) hacia el proveedor de IA: `ChatBackend`.

Es la interfaz minima que debe cumplir cualquier backend de chat. Los
adapters concretos (OpenAI, echo, reglas de dominio, ...) viven en
sdk_variant/a2a_agent/llm.py y en agents/portfolio_qa_agent.py; la capa A2A
nunca sabe cual hay detras, solo conoce este puerto.

Regla: un contrato puro no importa infra (aquí no hay proveedores, ni HTTP,
ni SDK). ``ChatBackendBase`` es la base con Template Method que da streaming
gratis sobre ``chat()``; sigue siendo contrato, no implementacion concreta.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Protocol


class ChatBackend(Protocol):
    """Interfaz minima que debe implementar un proveedor de chat."""

    async def chat(self, *, system: str, history: List[Dict[str, Any]]) -> str: ...

    def stream(
        self, *, system: str, history: List[Dict[str, Any]]
    ) -> AsyncIterator[str]: ...


class ChatBackendBase:
    """Base con Template Method: stream() vive sobre chat().

    Las subclases solo implementan ``chat()``; aqui esta el contrato de
    streaming (trocear la respuesta sin complejidad). Un backend con
    streaming real (OpenAIBackend) sobreescribe ``stream``/_stream.
    """

    async def chat(self, *, system: str, history: List[Dict[str, Any]]) -> str:
        raise NotImplementedError

    def stream(self, *, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        return self._stream(system, history)

    async def _stream(self, system: str, history: List[Dict[str, Any]]) -> AsyncIterator[str]:
        text = await self.chat(system=system, history=history)
        for char in text:
            yield char