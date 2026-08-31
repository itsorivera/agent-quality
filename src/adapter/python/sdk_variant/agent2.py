"""Segundo agente A2A (``portfolio-qa``): caso de uso de negocio de cartera.

Existe para mostrar el patron enterprise de la industria (ver docs/A2A_CONCEPTS.md):

  1. UN modulo por agente, como "receta pura" (sin FastAPI, sin uvicorn): este
     archivo solo produce ingredientes -> AgentSpec (card + handler).
  2. Card con ``securitySchemes`` / ``securityRequirements`` DISTINTOS por
     agente: este agente declara una API key (solo-lectura pero trazable);
     el de transacciones exigiria OAuth2 y auditoria; el de QA libre, nada.
  3. La auth se aplica en la capa HTTP (composition root app.py / middleware),
     que es donde A2A la define, NO dentro del agente. El agente solo la
     declara en su card para que el cliente sepa que debe autenticarse.
  4. Reutilizacion de infraestructura: el mismo SdkChatAgent/SdkChatExecutor de
     agent.py sirve con cualquier ChatBackend (echo, OpenAI, o este de reglas).
"""

from __future__ import annotations

import os

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    APIKeySecurityScheme,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0  # type: ignore[attr-defined]
from a2a_agent.protocol import parts_to_text

from sdk_variant.agent import SdkChatAgent, SdkChatExecutor
from sdk_variant.assembly import AgentSpec


class PortfolioFactsBackend:
    """Backend determinista de dominio (sin LLM): respuestas de cartera.

    Demuestra que el executor del SDK es agnostico del proveedor: el mismo
    SdkChatAgent/SdkChatExecutor de agent.py funciona con cualquier objeto que
    cumpla la interfaz ChatBackend (a2a_agent/llm.py). Reglas triviales solo
    para que el wire format sea verificable sin gastar tokens.
    """

    def __init__(self, prefix: str = "Portfolio QA"):
        self._prefix = prefix

    @staticmethod
    def _rules() -> tuple[tuple[tuple[str, ...], str], ...]:
        return (
            (
                ("capital", "valor", "portafolio", "cuanto"),
                "El valor actual del portafolio virtual es 125,400 USD. "
                "Dispones de 5 posiciones. Puedo darte el detalle por activo.",
            ),
            (
                ("rentabilidad", "performance", "ganancia", "rendimiento"),
                "La rentabilidad acumulada del portafolio en los ultimos 6 meses es +8.4%.",
            ),
            (
                ("activo", "posicion", "accion", "bond", "cripto"),
                "El desglose actual es: 60% renta variable, 25% renta fija y 15% cripto.",
            ),
            (
                ("riesgo", "volatilidad", "drawdown", "perdida"),
                "La volatilidad anualizada es 11.2% y el maximo drawdown en el ano -3.1%.",
            ),
        )

    async def chat(self, *, system: str, history: list[dict]) -> str:
        text = parts_to_text(history[-1]["parts"] if history else [])
        low = text.lower()
        for keys, answer in self._rules():
            if any(k in low for k in keys):
                return f"{self._prefix}: {answer}"
        return (
            f"{self._prefix}: puedo responderte solo preguntas de solo-lectura sobre "
            "tu portafolio (valor, rentabilidad, activos, riesgo). "
            "Prueba con: 'cuanto vale mi portafolio?'"
        )

    def stream(self, *, system: str, history: list[dict]) -> object:
        return self._stream(system, history)

    async def _stream(self, system: str, history: list[dict]):
        text = await self.chat(system=system, history=history)
        for char in text:
            yield char


def build_portfolio_qa_agent() -> AgentSpec:
    """Receta pura del agente de QA del portafolio (solo-lectura, con API key).

    Diferencia clave vs agent.py: la card declara el esquema de seguridad
    (API key en header ``X-API-Key``) y lo exige via securityRequirements.
    La API key en si NO vive aqui: se configura en el composition root
    (app.py / server.py) y se valida en middleware HTTP.
    """
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "2024"))
    name = os.getenv("QA_AGENT_NAME", "Portfolio QA Agent")
    description = os.getenv(
        "QA_AGENT_DESCRIPTION",
        "Read-only assistant that answers questions about the user's virtual portfolio.",
    )
    public_url = (os.getenv("PUBLIC_URL") or f"http://{host}:{port}").rstrip("/")

    system_prompt = (
        f"You are {name}. You answer READ-ONLY questions about the user's "
        "virtual investment portfolio. You never execute trades."
    )
    executor = SdkChatExecutor(
        SdkChatAgent(PortfolioFactsBackend(prefix=name), system_prompt)
    )

    security_scheme_name = "portfolioKey"
    skill = AgentSkill(
        id="portfolio-qa",
        name="Portfolio Q&A",
        description="Answers read-only questions about the investment portfolio.",
        tags=["portfolio", "qa", "read-only"],
        examples=["How much is my portfolio worth?", "What is my current risk?"],
        security_requirements=[
            SecurityRequirement(
                schemes={security_scheme_name: StringList(list=["X-API-Key"])}
            )
        ],
    )
    agent_card = AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"{public_url}/a2a/portfolio-qa",
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        skills=[skill],
        security_schemes={
            security_scheme_name: SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    description="API key the client must present in the X-API-Key header.",
                    location="header",
                    name="X-API-Key",
                )
            )
        },
        security_requirements=[
            SecurityRequirement(
                schemes={security_scheme_name: StringList(list=["X-API-Key"])}
            )
        ],
    )

    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    return AgentSpec(
        agent_id="portfolio-qa",
        name=name,
        description=description,
        card=agent_card,
        handler=handler,
    )