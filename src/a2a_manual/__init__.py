"""Implementacion propia del protocolo A2A v0.3 (JSON-RPC 2.0) sobre FastAPI.

Sin caja negra: aqui no se usa la libreria oficial `a2a-sdk` de Google ni el
endpoint /a2a de LangGraph. Este paquete implementa el wire format del A2A a
mano para que quede claro que es lo que ocurre por debajo.
"""