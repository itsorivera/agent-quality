"""Entrypoint del gateway multi-agente A2A (composition root).

Solo bootstrap: lee env, arma la app con create_app() y la sirve con uvicorn.
Toda la logica (recetas de agentes, politicas de auth, montaje de rutas) vive
en app.py / agents/{sdk,portfolio_qa}_agent.py, no aqui.

Para verificar la auth del portfolio-qa agent (401 sin key):
    $env:PORTFOLIO_QA_API_KEY="dev-key"; python -m server
    curl -X POST http://127.0.0.1:2024/a2a/portfolio-qa -H "A2A-Version: 1.0" ...
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
import uvicorn

from a2a.agents.sdk_agent import build_sdk_agent
from a2a.agents.portfolio_qa_agent import build_portfolio_qa_agent
from app import create_app
from a2a.a2a_recipe import AgentSettings


def main() -> None:
    load_dotenv(override=True)

    # Un unico AgentSettings como unico punto de despliegue (host/port/url).
    settings = AgentSettings.from_env()

    # Politica de auth por path (edge). Sin env key el agente queda abierto
    # para dev; en produccion la key vive en el secret manager, no en .env.
    policies: dict[str, str] = {}
    qa_key = os.getenv("PORTFOLIO_QA_API_KEY")
    if qa_key:
        policies["/a2a/portfolio-qa"] = qa_key

    app = create_app(
        agents=[
            build_sdk_agent(settings=settings),
            build_portfolio_qa_agent(settings=settings),
        ],
        auth_policies=policies,
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()