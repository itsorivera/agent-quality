"""Entrypoint del gateway multi-agente A2A (composition root).

Solo bootstrap: lee env, arma la app con create_app() y la sirve con uvicorn.
Toda la logica (recetas de agentes, politicas de auth, montaje de rutas) vive
en app.py / assembly.py / agent.py / agent2.py, no aqui.

Uso (desde python/):
    python -m sdk_variant.server                          # CHAT_PROVIDER=echo
    CHAT_PROVIDER=openai python -m sdk_variant.server     # LLM real (OPENAI_API_KEY)

Para verificar la auth del portfolio-qa agent (401 sin key):
    $env:PORTFOLIO_QA_API_KEY="dev-key"; python -m sdk_variant.server
    curl -X POST http://127.0.0.1:2024/a2a/portfolio-qa -H "A2A-Version: 1.0" ...
"""

from __future__ import annotations

import os
import sys

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from dotenv import load_dotenv  # noqa: E402
import uvicorn  # noqa: E402

from sdk_variant.agent import build_sdk_agent  # noqa: E402
from sdk_variant.agent2 import build_portfolio_qa_agent  # noqa: E402
from sdk_variant.app import create_app  # noqa: E402


def main() -> None:
    load_dotenv(override=True)

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "2024"))

    # Politica de auth por path (edge). Sin env key el agente queda abierto
    # para dev; en produccion la key vive en el secret manager, no en .env.
    policies: dict[str, str] = {}
    qa_key = os.getenv("PORTFOLIO_QA_API_KEY")
    if qa_key:
        policies["/a2a/portfolio-qa"] = qa_key

    app = create_app(
        agents=[build_sdk_agent(), build_portfolio_qa_agent()],
        auth_policies=policies,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()