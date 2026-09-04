"""Agente conversacional (``agent_id="conversational"``): receta + factory.

Cada agente vive en su propio modulo (patron "un agente = un archivo"). Este
solo declara el delta de su receta sobre AgentRecipe (a2a_protocol.a2a_recipe):
identidad, system prompt y skill. Todo el cableado (card + handler + adapter)
lo resuelve AgentRecipe.build() -> produce un AgentSpec listo para montar.

Sin transporte: no importa FastAPI/uvicorn. El composition root (app.py) y
el entrypoint (server.py) deciden la exposicion.
"""

from __future__ import annotations

import os

from a2a.types import AgentSkill

from a2a_manual.llm import build_backend
from a2a_protocol.a2a_recipe import AgentRecipe, AgentSettings
from ports.llm import ChatBackend
from ports.spec import AgentSpec


class ConversationalAgent(AgentRecipe):
    """Receta del agente conversacional: su unico delta respecto a la base.

    Identidad, backend y skill; todo el cableado (card + handler + adapter)
    lo resuelve AgentRecipe.build().
    """

    agent_id = "conversational"

    def __init__(
        self,
        *,
        settings: AgentSettings,
        backend: ChatBackend,
        name: str,
        description: str,
    ):
        super().__init__(settings=settings, backend=backend)
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def build_system_prompt(self) -> str:
        return os.getenv("SYSTEM_PROMPT") or f"You are {self.name}. {self.description}"

    def build_skills(self) -> list[AgentSkill]:
        return [
            AgentSkill(
                id="conversation",
                name="Conversational Chat",
                description="Participates in text conversations via the A2A protocol (SDK implementation).",
                tags=["chat", "conversation", "sdk"],
                examples=["Hello", "What can you help me with?"],
            )
        ]


def build_sdk_agent(
    settings: AgentSettings | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> AgentSpec:
    """Factory inyectable del agente conversacional.

    Si pasas ``settings``/``name``/``description`` explicitos, el unico
    entorno que aun lee es el del backend (CHAT_PROVIDER/OPENAI_*), con el
    fallback dev ``echo``. Para inyeccion estricta, server.py construye el
    ``ChatBackend`` y pasa el resto por parametro.
    """
    settings = settings or AgentSettings.from_env()
    name = name or os.getenv("AGENT_NAME", "SDK Conversational Agent")
    description = description or os.getenv(
        "AGENT_DESCRIPTION", "A conversational agent exposed over A2A via the official SDK."
    )
    backend = build_backend(
        os.getenv("CHAT_PROVIDER", "echo"),
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        agent_name=name,
    )
    return ConversationalAgent(
        settings=settings, backend=backend, name=name, description=description
    ).build()