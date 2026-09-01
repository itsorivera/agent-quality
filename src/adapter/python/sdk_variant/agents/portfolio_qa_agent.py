"""Agente de QA del portafolio (``agent_id="portfolio-qa"``): receta + factory.

Cada agente vive en su propio modulo ("un agente = un archivo"). Este agrega
su delta:
  - un backend determinista de reglas (``PortfolioFactsBackend``, sin LLM),
  - security de la card: una API key (``portfolioKey``) declarada en
    securitySchemes (header ``X-API-Key``) y exigida via securityRequirements.

La API key en si NO vive aqui: se configura en el composition root
(app.py / server.py) y se valida en middleware HTTP; la card solo la declara.
"""

from __future__ import annotations

import os

from a2a.types import (
    APIKeySecurityScheme,
    AgentSkill,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

from sdk_variant.a2a_agent.protocol import parts_to_text
from sdk_variant.ports.llm import ChatBackend, ChatBackendBase
from sdk_variant.ports.spec import AgentSpec
from sdk_variant.recipe import AgentRecipe, AgentSettings


class PortfolioFactsBackend(ChatBackendBase):
    """Backend determinista de dominio (sin LLM): respuestas de cartera.

    Demuestra que el executor del SDK es agnostico del proveedor: el mismo
    SdkChatAgent/SdkChatExecutor de core.py funciona con cualquier objeto
    que cumpla la interfaz ChatBackend. Reglas triviales solo para que el
    wire format sea verificable sin gastar tokens.

    El streaming (``stream``/``_stream``) no requiere codigo aqui: es el
    Template Method de ``ChatBackendBase`` que trocea la salida de ``chat``.
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


class PortfolioQaAgent(AgentRecipe):
    """Receta del agente portfolio-qa: identidad, backend y security de la card.

    Su delta respecto de AgentRecipe.build():
        - una API key (``portfolioKey``) declarada en securitySchemes (header
          ``X-API-Key``) y exigida via securityRequirements en card y skill.
        - un backend determinista de reglas (sin LLM) para QA de solo-lectura.
    """

    agent_id = "portfolio-qa"

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
        return (
            f"You are {self.name}. You answer READ-ONLY questions about the user's "
            "virtual investment portfolio. You never execute trades."
        )

    def build_skills(self) -> list[AgentSkill]:
        return [
            AgentSkill(
                id="portfolio-qa",
                name="Portfolio Q&A",
                description="Answers read-only questions about the investment portfolio.",
                tags=["portfolio", "qa", "read-only"],
                examples=["How much is my portfolio worth?", "What is my current risk?"],
                security_requirements=[
                    SecurityRequirement(
                        schemes={"portfolioKey": StringList(list=["X-API-Key"])}
                    )
                ],
            )
        ]

    def build_security_schemes(self) -> dict[str, SecurityScheme]:
        return {
            "portfolioKey": SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    description="API key the client must present in the X-API-Key header.",
                    location="header",
                    name="X-API-Key",
                )
            )
        }

    def build_security_requirements(self) -> list[SecurityRequirement]:
        return [
            SecurityRequirement(
                schemes={"portfolioKey": StringList(list=["X-API-Key"])}
            )
        ]


def build_portfolio_qa_agent(
    settings: AgentSettings | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> AgentSpec:
    """Factory inyectable del agente de QA del portafolio (solo-lectura, con API key).

    Diferencia clave vs build_sdk_agent: la card declara el esquema de
    seguridad (API key en header ``X-API-Key``) y lo exige via
    securityRequirements. La API key en si NO vive aqui: se configura en el
    composition root (app.py / server.py) y se valida en middleware HTTP.
    """
    settings = settings or AgentSettings.from_env()
    name = name or os.getenv("QA_AGENT_NAME", "Portfolio QA Agent")
    description = description or os.getenv(
        "QA_AGENT_DESCRIPTION",
        "Read-only assistant that answers questions about the user's virtual portfolio.",
    )
    return PortfolioQaAgent(
        settings=settings,
        backend=PortfolioFactsBackend(prefix=name),
        name=name,
        description=description,
    ).build()