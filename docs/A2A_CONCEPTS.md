# Conceptos clave de A2A (aprendidos en este proyecto)

Referencia normativa: https://a2a-protocol.org/latest/specification

Este repo tiene **dos variantes** del mismo agente para comparar cara a cara el
wire format y la arquitectura:

| | `sdk_variant/a2a_agent/` (manual) | `sdk_variant/` (SDK `a2a-sdk` 1.1.x) |
|---|---|---|
| Version de protocolo | 0.3.0 | 1.0 (+ compat v0.3 optativa) |
| Wire | kebab-case (`message/send`) | PascalCase (`SendMessage`) + header `A2A-Version` |
| Tipos | dicts tipados a mano | protobuf (`a2a_pb2`) |
| Estado de tasks | mutables (se reusa taskId) | **inmutables** (continuidad por `contextId`) |

---

## 1. Modelo de objetos (spec A2A)

- **Agent Card**: documento de descubrimiento del agente. Contiene `name`,
  `skills[]`, `capabilities[]`, `securitySchemes`, `securityRequirements` y,
  crucial: `supportedInterfaces[].url` (el endpoint JSON-RPC del agente).
- **Message / Part**: un mensaje tiene `role` (user/agent) y `parts[]`
  (`TextPart`, `FilePart`, `DataPart`...). En v1.0 el enum de role es
  `ROLE_USER` (protobuf); en v0.3 era `"user"`.
- **Task**: la unidad de trabajo. Estados: `submitted -> working -> completed`
  (o `failed | canceled | input-required`). Los terminales son `completed`,
  `failed`, `canceled`.
- **contextId**: el "hilo" conversacional. **En v1.0 las tasks son inmutables**:
  reutilizar un `taskId` terminal devuelve error `-32602`. La continuidad de un
  chat se hace enviando el **mismo `contextId`** (equivale a `_threads` del
  server manual).

## 2. Transporte: JSON-RPC 2.0

- Envelope: `{"jsonrpc":"2.0","id":...,"method":...,"params":{...}}`.
- v1.0 metodos PascalCase: `SendMessage`, `GetTask`, `ListTasks`, `CancelTask`,
  `GetExtendedAgentCard`. v0.3: kebab-case (`message/send`, `tasks/get`).
- El resultado de `SendMessage` en v1.0 es `result.task` (la Task envuelta);
  en v0.3 `result` **es** la Task (`result.kind == "task"`).
- Streaming: `message/stream` + SSE (Server-Sent Events, `data: {json}`).
- Errores estandar JSON-RPC: `-32700` parse, `-32600` invalid request,
  `-32601` method not found, `-32602` invalid params, `-32603` internal.

## 3. Versionado del protocolo

- Header **`A2A-Version: 1.0`** (o `0.3`) en cada request. La negociacion es
  parte del protocolo: si el header no coincide con el metodo, el servidor
  responde error (`Expected version '0.3'`).
- `enable_v0_3_compat=True` en `create_jsonrpc_routes()` habilita el wire de
  v0.3 en el mismo endpoint para clientes antiguos (v0.3 no usa header; el
  metodo indica la intencion).
- En v1.0 la version del protocolo NO esta en la raiz de la card: vive en
  `supportedInterfaces[].protocolVersion`.

## 4. Descubrimiento de agentes

- Convencion: la card vive en `/.well-known/agent-card.json` del agente.
- El cliente **nunca hardcodea el path**: lee `supportedInterfaces[0].url` de
  la card y ahi hace POST JSON-RPC.
- **Multi-tentana / multi-agente** (Spec, "Multi-Tenancy and Multi-Agent
  Routing"): varios agentes detras de un host. Mecanismos: (a) URL-based
  routing (sub-path) — el patron usado por LangGraph (`/a2a/{assistant_id}`)
  y por este repo (`/a2a/{agent_id}`); (b) header-based; (c) campo `tenant`.
  Regla: **un agente = una card + una URL**, sin importar cuantos agentes
  comparten proceso. El SDK lo soporta con `create_jsonrpc_routes(handler,
  rpc_url="/a2a/<id>")` y `create_agent_card_routes(card, card_url=...)`.

## 5. Seguridad: la capa correcta es HTTP

A2A **no** define autenticacion en el mensaje: es transporte. La card
**declara** el esquema; el enforcement vive en el edge (gateway/middleware):

- `securitySchemes`: mapa nombre → esquema OpenAPI (`apiKeySecurityScheme`,
  `httpAuthSecurityScheme`, `oauth2SecurityScheme`, `openIdConnectSecurityScheme`,
  `mtlsSecurityScheme`).
- `securityRequirements`: cuales esquemas aplicar (tambien por skill).
- Politica que recomendamos por dominio de negocio:

| Agente / dominio | securitySchemes | Enforcement en el edge |
|---|---|---|
| Conversacional publico | (ninguno) | ninguna |
| QA de solo-lectura | API key optativa/identidad | header `X-API-Key`, rate-limit suave |
| Transacciones / pagos | `OAuth2` (client-credentials) o API key estricta | token en el gate + **auditoria** (log trazable de cada llamada + payload) + mTLS si aplica |
| Admin / exfil | OAuth2 + mTLS | acceso restringido por red y por rol |

Principios:
1. Las cards (`/.well-known/...`) y `/docs` quedan **siempre publicos**.
2. Cada agente sensible expone **credenciales distintas** (segregacion).
3. La API key nunca vive en el modulo del agente: se configura en el
   composition root/secret-manager y se valida en middleware HTTP.
4. Auditoria: registrar llamada (agente, caller, ts, resultado) es del gateway;
   no inyectar logica de negocio en el executor por culpa de la auditoria.

## 6. FastAPI como capa web del SDK

- FastAPI es una capa sobre Starlette (`class FastAPI(Starlette)`), no es
  excluyente. La industria usa FastAPI para agentes A2A enterprise (OpenAPI
  `/docs`, auth/OTel/rate-limit vía middleware, inyeccion de dependencias).
- `add_a2a_routes_to_fastapi()` re-registra las rutas A2A (card + JSON-RPC)
  como `APIRoute` para que aparezcan en `/docs`/`/openapi.json` con schema.

## 7. Arquitectura: donde vive cada bloque (hexagonal / composition root)

El bloque

```python
app = FastAPI(...)
add_a2a_routes_to_fastapi(app, agent_card_routes=..., jsonrpc_routes=...)
app.state.a2a = handler
```

es **wiring de composicion**, NO logica de agente. Por eso vive en el
composition root (`sdk_variant/app.py`), no en los modulos de receta
(`sdk_variant/agents/*.py`, framework compartido en `recipe.py`/`spec.py`)
ni en `server.py` (bootstrap de 5 lineas):

```
sdk_variant/a2a_agent/{llm,protocol}.py  # adapters del puerto LLM (OpenAI/echo) + wire v0.3
  -> ports/{llm,spec}.py                 # PUERTOS puros: ChatBackend + AgentSpec [sin impl]
  -> core.py                             # adapter del a2a-sdk (SdkChatAgent/Executor) [sin HTTP]
  -> recipe.py                           # receta base (Template Method) + AgentSettings
  -> agents/{sdk,portfolio_qa}_agent.py  # UN archivo por agente (receta + factory)
  -> app.py                              # create_app(): N agentes + auth + rutas [composition root]
  -> server.py                           # uvicorn.run(create_app())       [entrypoint]
```

Beneficio: el mismo executor se puede exponer por FastAPI, Starlette, gRPC, o
por otro path sin tocar el agente; y los tests (ASGITransport) no necesitan
red.

## 8. Multi-agente en una app (de este repo)

- Verificado en `tests/test_gateway.py` (pytest): cada agente se sirve en
  `/a2a/{agent_id}` con su **propia card**, JSON-RPC con auth por path (401 sin
  `X-API-Key`), registry `app.state.a2a`, y todo aparece en `/openapi.json`.
- Regla de la industria para decidir agrupar o separar a microservicios:
  agrupar si mismo dominio/equipo/runtime (modular monolith); separar si hay
  boundary real — otro equipo, escala independiente, compliance/auditoria
  distinta (transacciones vs QA vs reportes), blast radius diferente.
  A2A no dicta "un agente = un servicio"; dicta "un agente = una card + URL".
  Por eso el split posterior es NO invasivo para los clientes.

## 9. Testing (como lo verificamos)

- `pytest src/adapter/python/sdk_variant/tests/test_wire.py` — wire v1.0 real
  del SDK + compat v0.3 + negociacion de version + inmutabilidad de tasks
  (**14 tests en pytest**).
- `pytest src/adapter/python/sdk_variant/tests/test_gateway.py` — gateway
  multi-agente, cards/securitySchemes/auth por path/OpenAPI (**idem**).
- Patron: `httpx.ASGITransport(app=app)` sin levantar red; respuestas
  validadas contra el wire format real. El `conftest.py` centraliza el env
  determinista (CHAT_PROVIDER=echo) y los helpers de cliente.

## 10. Referencias

- Spec A2A 1.0: https://a2a-protocol.org/latest/specification
- Multi-Tenancy / Multi-Agent Routing: https://a2a-protocol.org/latest/topics/multi-tenancy/
- Agent Discovery: https://a2a-protocol.org/latest/topics/agent-discovery/
- Docking/guia de hospedaje (Microsoft, "Host agents with A2A", `MapA2A`):
  https://learn.microsoft.com/en-us/agent-framework/hosting/self-hosting/a2a/server
- SDK Python: `add_a2a_routes_to_fastapi`, `create_jsonrpc_routes(handler, rpc_url)`,
  `create_agent_card_routes(card, card_url)` — https://a2a-protocol.org/latest/sdk/python/
- a2a-samples: https://github.com/a2aproject/a2a-samples