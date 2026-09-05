"""Composition root (arquitectura hexagonal): ensambla N agentes en una FastAPI.

Reune lo que antes eran dos modulos (``assembly.py`` y la propia ``app.py``):
aqui viven tanto el montaje de rutas A2A (mount_a2a_endpoints) como la
construccion del gateway (create_app) y las politicas de auth. El esqueleto
de un agente (AgentSpec) vive en spec.py para que las recetas (recipe.py) no
dependan de FastAPI.

Dependencias del grafo (sin ciclos):

    a2a_agent/ (llm.py, protocol.py)   # adapters del puerto LLM (OpenAI/echo) + wire v0.3
      -> ports/ (llm.py, spec.py)      # PUERTOS puros: ChatBackend + AgentSpec (sin impl)
      -> core.py                       # adapter del a2a-sdk (SdkChatAgent/Executor) [sin HTTP]
      -> recipe.py                     # receta base (Template Method) + AgentSettings
      -> agents/{sdk,portfolio_qa}_agent.py  # UN modulo por agente (receta + factory)
      -> app.py                        # create_app()                     <-- composition root (este archivo)
      -> server.py                     # main()                           entrypoint (uvicorn)

Responsabilidades exclusivas de app.py:
  - decidir el binding de cada agente (path /a2a/<agent_id> + card).
  - registrar los handlers en un registry (app.state.a2a) para operacion.
  - aplicar politicas transversales: AUTH (per-path), audit, rate-limit, OTel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)

from a2a_interface.agents.portfolio_qa_agent import build_portfolio_qa_agent
from a2a_interface.agents.sdk_agent import build_sdk_agent
from ports.spec import AGENT_CARD_WELL_KNOWN, AgentSpec
from a2a_interface.a2a_recipe import AgentSettings

_PUBLIC_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/health")
_CARD_SUFFIX = "/.well-known/agent-card.json"


def mount_a2a_endpoints(app: Any, spec: AgentSpec, *, root: bool = False) -> None:
    """Monta card + JSON-RPC de un agente en la app y alinea la url de la card.

    ``root=True`` reproduce el despliegue clasico de un unico agente:
        - rpc      : POST "/"
        - card     : GET "/.well-known/agent-card.json"

    ``root=False`` (default) despliega un agente dentro del gateway multi-agente:
        - rpc      : POST "/a2a/<agent_id>"
        - card     : GET "/a2a/<agent_id>/.well-known/agent-card.json"

    El composition root reescribe ``supportedInterfaces[0].url`` con el path
    real montado: los clientes descubren la url via la card y nunca hardcodean
    rutas (Spec A2A, seccion Agent Discovery).
    """
    rpc_path = "/" if root else spec.rpc_path
    card_path = AGENT_CARD_WELL_KNOWN if root else spec.card_path

    base_url = spec.card.supported_interfaces[0].url
    if base_url:
        spec.card.supported_interfaces[0].url = f"{base_url.rstrip('/')}{rpc_path}"

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(spec.card, card_url=card_path),
        jsonrpc_routes=create_jsonrpc_routes(
            spec.handler, rpc_path, enable_v0_3_compat=True
        ),
    )


def api_key_gate(policies: dict[str, str]) -> Callable:
    """Factory de middleware HTTP que enforce API keys por prefijo de path.

    Por que aqui y no en el agente: A2A deja la autenticacion al transporte
    HTTP (la card solo la DECLARA via securitySchemes/securityRequirements).
    El enforcement es responsabilidad del edge (composition root / gateway),
    igual que en Azure APIM, Kong o los guard del SDK de Microsoft.

    Politica de ejemplo que regula la industria: los cards y /docs son
    PUBLICOS (el descubrimiento no lleva credenciales); el JSON-RPC de un
    agente sensible (transacciones) exige credencial; un agente QA de
    solo-lectura puede quedar abierto o con identidad optativa.
    """

    async def _gate(request: Request, call_next: Callable) -> object:
        path = request.url.path

        if path.endswith(_CARD_SUFFIX) or path.startswith(_PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        for prefix, expected in policies.items():
            if path.startswith(prefix):
                supplied = request.headers.get("X-API-Key")
                if not supplied or supplied != expected:
                    return JSONResponse(
                        {"error": f"missing or invalid X-API-Key for {prefix}"},
                        status_code=401,
                    )
        return await call_next(request)

    return _gate


def create_app(
    agents: list[AgentSpec] | None = None,
    *,
    auth_policies: dict[str, str] | None = None,
) -> FastAPI:
    """Ensambla el gateway multi-agente A2A.

    Args:
        agents: lista de recetas (AgentSpec). Por defecto monta los dos agentes
            de ejemplo: conversational (publico) y portfolio-qa (con API key).
        auth_policies: mapping path-prefix -> API key esperada. El cliente la
            envia en el header ``X-API-Key``. Si es vacio, no se enforce auth.
    """
    load_dotenv(override=True)

    if agents is None:
        # Un solo AgentSettings compartido (unico punto para host/port/card):
        # ambos agentes comparten el mismo despliegue, no cada uno su lectura.
        settings = AgentSettings.from_env()
        agents = [
            build_sdk_agent(settings=settings),
            build_portfolio_qa_agent(settings=settings),
        ]
    policies = auth_policies or {}

    app = FastAPI(title="A2A multi-agent gateway", version="0.1.0")

    # Registry de handlers: util para tests, health, prometheus y operacion.
    app.state.a2a: dict[str, object] = {}
    for spec in agents:
        # card en /a2a/<id>/.well-known..., rpc POST /a2a/<id>
        mount_a2a_endpoints(app, spec)
        app.state.a2a[spec.agent_id] = spec.handler

    gate = api_key_gate(policies)

    @app.middleware("http")
    async def _enforce_auth(request: Request, call_next: Callable) -> object:
        return await gate(request, call_next)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "agents": [a.agent_id for a in agents]}

    return app