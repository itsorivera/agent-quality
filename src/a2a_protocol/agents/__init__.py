"""Repertorio de agentes del variante SDK: UN modulo por agente, una facade aqui.

Este paquete es el *catagalo* del feature "agentes": su facade re-exporta
solo las factories publicas (``build_sdk_agent`` / ``build_portfolio_qa_agent``)
y nada mas. La infraestructura compartida NO vive aqui (src/ports,
src/a2a_manual, a2a_protocol.a2a_recipe): el limite es "lo propio de cada
agente dentro; el framework del variante fuera".

Reglas vigentes para anadir un agente aqui:
  1. un agente = un modulo ``<agent_id>.py`` con su receta (subclase de
     AgentRecipe) + factory ``build_<x>`` env-aware e inyectable.
  2. sin transporte: la receta no importa FastAPI/uvicorn.
  3. imports SIEMPRE cualificados: ``from ports.llm import ...``
     (nunca relativos hacia fuera). El composition root (app.py / server.py)
     importa los agentes desde esta facade.
  4. anade la nueva factory al __all__ de este paquete y al de a2a_protocol.
"""

__all__ = ["build_portfolio_qa_agent", "build_sdk_agent"]

from a2a_protocol.agents.portfolio_qa_agent import build_portfolio_qa_agent
from a2a_protocol.agents.sdk_agent import build_sdk_agent

