"""Entrypoint del agente A2A implementado con el SDK oficial.

Uso (desde python/):
    python -m sdk_variant.server                        # CHAT_PROVIDER=echo por defecto
    CHAT_PROVIDER=openai python -m sdk_variant.server   # LLM real (requiere OPENAI_API_KEY)

Para conversacion A2A multiagente:
    # Terminal 1  (agente manual v0.3)
    $env:PORT=2024; $env:AGENT_NAME="Agent A"; python agent.py
    # Terminal 2  (agente SDK v1.0)
    $env:PORT=2026; $env:AGENT_NAME="SDK Agent B"; python -m sdk_variant.server
    # Terminal 3  (cliente v1.0 contra el SDK)
    python -m sdk_variant.client --url http://127.0.0.1:2026
"""

from __future__ import annotations
import os
import uvicorn
from dotenv import load_dotenv
from agent import build_sdk_agent_app

load_dotenv()


if __name__ == "__main__":
    host = os.getenv("HOST")
    port = int(os.getenv("PORT"))
    uvicorn.run(build_sdk_agent_app(), host=host, port=port, log_level="info")