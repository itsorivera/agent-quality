"""Puertos (contratos) del hexagono: solos y sin implementacion.

Este paquete es el unico lugar del variante con interfazes/contratos puros:
  - ``llm.py``  : ``ChatBackend``/``ChatBackendBase`` — puerto *driven* hacia
                  el proveedor de IA (OpenAI, echo, reglas...). Tiene 2+ impls
                  reales, por eso es un port legitimo (ver adapters en
                  a2a_agent/llm.py).
  - ``spec.py`` : ``AgentSpec`` — puerto *de salida*: lo unico que el
                  transporte (app.py) necesita para montar un agente. Es el
                  seam que hace "recetas sin transporte" posibles.

Reglas del paquete (no las rompas):
  1. SOLO contratos: aqui no vive implementacion (nada de FastAPI, uvicorn,
     proveedores de IA, SDK execution). Los adapters que los cumplen estan en
     a2a_agent/ (llm concretos) y core.py (executor del SDK).
  2. no importes desde fuera del paquete (salvo tipos puros): si necesitas
     algo de infra para definir un contrato, el contrato está mal ubicado.
  3. los consumidores (agents/, recipe, core, app) importan los contratos
     desde aqui; los concretos concretos nunca deben importar los ports al reves.

Sin puerto = sin abstraccion: cuando un contrato tenga UN solo consumidor e
implementacion, no lo subas aqui (la regla es "con 2+ impls o 2+ consumidores
reales").
"""
