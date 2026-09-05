"""Agente A2A implementado con el SDK oficial `a2a-sdk` (protocolo v1.0).

Variante "caja negra" del mismo agente que `a2a_agent` (manual v0.3, sub-paquete
del SDK): aqui el wire format y la maquina de estados los resuelve la libreria;
nosotros escribimos la logica (recetas en los modulos de agente) y la
configuracion.

API publica (facade):
    - ``create_app()``                 : gateway multi-agente (FastAPI).
    - ``build_sdk_agent()`` / ``build_portfolio_qa_agent()``:
                                        recetas puras que producen un AgentSpec.
    - ``AgentSpec``                    : receta lista para montar.

Internamente (no uses estos imports desde fuera):
    - ``ports/``: puertos (contratos) puros: ``llm.py`` (ChatBackend) y
      ``spec.py`` (AgentSpec). Sin implementacion.
    - ``core``: adaptador del SDK `a2a-sdk` (SdkChatAgent/SdkChatExecutor).
    - ``recipe``: receta base (Template Method) + AgentSettings (aplication/domain).
    - ``agents/``: repertorio de agentes. UN modulo por agente (sdk_agent.py,
      portfolio_qa_agent.py); su facade re-exporta solo las factories.
    - ``app``: composition root (FastAPI + rutas A2A + auth).
    - ``a2a_agent``: variante manual del protocolo (v0.3). Aqui viven los
      adapters concretos del puerto LLM (OpenAI/echo) y sirve de referencia.
"""
