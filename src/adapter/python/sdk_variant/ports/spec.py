"""``AgentSpec``: puerto de salida — la receta lista para montar.

Es el contrato entre las recetas (sdk_variant/agents/*) y el transporte
(app.py, composition root). Un agente no deberia saber si se expone por
FastAPI, gRPC o por que path: lo unico que el transporte necesita para
montarlo es este objeto. Es un puerto puro: datos + derivados, sin
comportamiento de construccion (eso vive en recipe.py) ni de transporte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types.a2a_pb2 import AgentCard

AGENT_CARD_WELL_KNOWN = "/.well-known/agent-card.json"


@dataclass
class AgentSpec:
    """Receta de un agente: lo unico que el transporte necesita para montarlo.

    Atributos:
        agent_id: identificador estable del agente; define su path
            (/a2a/<agent_id>) y el path de su card, y es la clave del
            registro ``app.state.a2a``.
        name: nombre de negocio del agente (el de su AgentCard).
        description: descripcion humana (aparece en la card).
        card: AgentCard ya construida (incluye supportedInterfaces, la url
            base la corrige el composition root al arrancar).
        handler: DefaultRequestHandler del SDK, listo para ser servido.
        extras: campos de despliegue (logs, tags) sin rigidez de schema.
    """

    agent_id: str
    name: str
    description: str
    card: AgentCard
    handler: DefaultRequestHandler
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def rpc_path(self) -> str:
        """Prefijo JSON-RPC de este agente (convencion LangGraph/ADK)."""
        return f"/a2a/{self.agent_id}"

    @property
    def card_path(self) -> str:
        """Path de descubrimiento (card) de este agente."""
        return f"{self.rpc_path}{AGENT_CARD_WELL_KNOWN}"