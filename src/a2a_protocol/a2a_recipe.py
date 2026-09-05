"""Receta base de un agente A2A: aplication/domain + Template Method.

Comun a todos los agentes del paquete. Los agentes concretos
(agents/sdk_agent.py, agents/portfolio_qa_agent.py) son subclases cortas que
solo declaran su "delta": identidad, skills, security y backend. Aqui NO hay
transporte — nada de FastAPI/uvicorn —, solo recetas puras que producen un
``AgentSpec`` (ports/spec.py); el wiring de HTTP vive en app.py y el
entrypoint en server.py.

Patrones aplicados:
  - ``AgentRecipe``: Template Method. ``build()`` monta card + adapter +
    handler y no debe sobreescribirse.
  - ``AgentSettings``: configuracion de despliegue compartida e inyectable
    (un solo punto para HOST/PORT/PUBLIC_URL y la card). La construyen los
    entrypoints una vez y la inyectan en las factorias.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SecurityRequirement,
    SecurityScheme,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0  # type: ignore[attr-defined]

from .a2a_adapter import SdkChatAgent, SdkChatExecutor
from ports.llm import ChatBackend
from ports.spec import AgentSpec


@dataclass(frozen=True)
class AgentSettings:
    """Configuracion compartida de despliegue (infra, no logica de negocio).

    Un solo punto para la URL base y los modos por defecto de la card.
    La construyen los entrypoints (app.py / server.py) una vez y la inyectan
    en las factorias: recetas puras y testables sin duplicar env reads.
    """

    host: str = "127.0.0.1"
    port: int = 2024
    public_url: str | None = None
    card_version: str = "0.1.0"
    enable_streaming: bool = True
    default_input_modes: tuple[str, ...] = ("text/plain",)
    default_output_modes: tuple[str, ...] = ("text/plain",)

    @property
    def base_url(self) -> str:
        return (self.public_url or f"http://{self.host}:{self.port}").rstrip("/")

    @classmethod
    def from_env(cls) -> "AgentSettings":
        """Lee HOST/PORT/PUBLIC_URL del entorno (el caller ya cargo .env)."""
        return cls(
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "2024")),
            public_url=os.getenv("PUBLIC_URL"),
        )


class AgentRecipe:
    """Template Method: esqueleto comun para construir un AgentSpec.

    Hook obligatorios (las subclases declaran su "delta"):
        agent_id, name, description, build_skills()
    Hooks opcionales:
        build_system_prompt(), build_security_schemes(),
        build_security_requirements(), build_card_url()
    El metodo ``build()`` esta hecho y no debe sobreescribirse: monta la card,
    ata el adapter (core.py) al backend y devuelve el AgentSpec.
    """

    agent_id: str = ""
    """Identificador estable del agente; define su path y la clave del registry."""

    def __init__(self, settings: AgentSettings, backend: ChatBackend):
        self._settings = settings
        self._backend = backend

    # ------------------------------------------------------------------ hooks
    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError

    def build_skills(self) -> list[AgentSkill]:
        raise NotImplementedError

    def build_system_prompt(self) -> str:
        return f"You are {self.name}. {self.description}"

    def build_security_schemes(self) -> dict[str, SecurityScheme]:
        return {}

    def build_security_requirements(self) -> list[SecurityRequirement]:
        return []

    def build_card_url(self) -> str:
        return f"{self._settings.base_url}/"

    # ------------------------------------------------------------ template
    def build(self) -> AgentSpec:
        """Ensambla card + adapter + handler. No debe sobreescribirse."""
        card_kwargs: dict[str, object] = dict(
            name=self.name,
            description=self.description,
            version=self._settings.card_version,
            default_input_modes=list(self._settings.default_input_modes),
            default_output_modes=list(self._settings.default_output_modes),
            capabilities=AgentCapabilities(
                streaming=self._settings.enable_streaming,
                extended_agent_card=True,
            ),
            supported_interfaces=[
                AgentInterface(
                    protocol_binding="JSONRPC",
                    url=self.build_card_url(),
                    protocol_version=PROTOCOL_VERSION_1_0,
                )
            ],
            skills=self.build_skills(),
        )
        security_schemes = self.build_security_schemes()
        if security_schemes:
            card_kwargs["security_schemes"] = security_schemes
        security_requirements = self.build_security_requirements()
        if security_requirements:
            card_kwargs["security_requirements"] = security_requirements
        card = AgentCard(**card_kwargs)

        executor = SdkChatExecutor(SdkChatAgent(self._backend, self.build_system_prompt()))
        handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
            agent_card=card,
        )
        return AgentSpec(
            agent_id=self.agent_id,
            name=self.name,
            description=self.description,
            card=card,
            handler=handler,
        )