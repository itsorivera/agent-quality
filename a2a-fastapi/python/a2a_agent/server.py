"""Servidor A2A v0.3 sobre FastAPI - protocolo implementado a mano.

Qué hace este módulo (y qué haría la "caja negra" de LangGraph por ti):
  1. Expone `/ .well-known/agent-card.json`  -> descubrimiento (Agent Card)
  2. Recibe JSON-RPC 2.0 en `POST /` y `POST /a2a`
  3. Implementa operaciones A2A:
       - agent/getCard  : devuelve el Agent Card (metodo JSON-RPC de v0.3)
       - message/send   : conversacion sincrona (envelope JSON-RPC)
       - message/stream : misma conversacion via SSE (eventos status/artifact)
       - tasks/get      : consulta una Task por id (o lista todas)
       - tasks/cancel   : cancela una Task en un estado no terminal
  4. Mantiene el estado conversacional (threads) y las tareas en memoria.

La logica de negocio (el LLM) vive detras de la interfaz `ChatBackend`
(llm.py). Este servidor solo traduce A2A <-> backend.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .llm import ChatBackend
from .protocol import (
    AGENT_GET_CARD,
    CANCELED,
    COMPLETED,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MESSAGE_SEND,
    MESSAGE_STREAM,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    SUBMITTED,
    TASKS_CANCEL,
    TASKS_GET,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    TERMINAL_STATES,
    WORKING,
    RpcError,
    new_id,
    now_iso,
    parts_to_text,
    rpc_error,
    rpc_result,
    sse_event,
    text_part,
    wrap_error,
)

LOGGER = logging.getLogger(__name__)


class A2AServer:
    """Un agente A2A individual: estado conversacional + dispatch JSON-RPC.

    La aparicion de "asistente id" (como /a2a/{assistant_id} de LangGraph) es
    una convencion del ecosistema: el endpoint del agente aqui es simplemente la
    URL que publica su Agent Card. Los threads se identifican mediante
    contextId/taskId en el propio mensaje.
    """

    def __init__(
        self,
        backend: ChatBackend,
        *,
        name: str,
        description: str,
        public_url: str,
        system_prompt: str | None = None,
        version: str = "0.1.0",
    ):
        self._backend = backend
        self.name = name
        self.description = description
        self._public_url = public_url.rstrip("/")
        self._version = version
        self._system = system_prompt or f"You are {name}. {description}"

        # Estado en memoria (un solo proceso; para produccion usa un store persistente)
        self._threads: Dict[str, List[Dict[str, Any]]] = {}  # contextId -> history
        self._tasks: Dict[str, Dict[str, Any]] = {}  # taskId -> Task
        self._task_by_thread: Dict[str, str] = {}  # contextId -> taskId

    # ------------------------------------------------------------------
    # Descubrimiento: el Agent Card describe que puede hacer el agente.
    # ------------------------------------------------------------------
    def agent_card(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": f"{self._public_url}/",
            "provider": {"organization": "agent-quality"},
            "version": self._version,
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"streaming": True, "pushNotifications": False},
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "skills": [
                {
                    "id": "conversation",
                    "name": "Conversational Chat",
                    "description": "Participates in text conversations via the A2A protocol.",
                    "tags": ["chat", "conversation"],
                    "examples": ["Hello", "What can you help me with?"],
                    "inputModes": ["text"],
                    "outputModes": ["text"],
                }
            ],
            "securitySchemes": [],
        }

    # ------------------------------------------------------------------
    # Dispatch JSON-RPC: inspecciona `method` y delega en un handler.
    # Los handlers lanzan RpcError; aqui se traduce a envelope de error.
    # ------------------------------------------------------------------
    async def dispatch(self, body: Any) -> Any:
        request_id = body.get("id") if isinstance(body, dict) else None
        try:
            if not isinstance(body, dict):
                raise RpcError(INVALID_REQUEST, "Invalid Request")
            if body.get("jsonrpc") != "2.0":
                raise RpcError(INVALID_REQUEST, 'jsonrpc field must be "2.0"')
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")

            method = body.get("method")
            handlers = {
                MESSAGE_SEND: self._send,
                MESSAGE_STREAM: self._stream,
                TASKS_GET: self._get,
                TASKS_CANCEL: self._cancel,
                AGENT_GET_CARD: self._get_card,
            }
            handler = handlers.get(method)
            if handler is None:
                raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
            return await handler(request_id, params)
        except RpcError as exc:
            return rpc_error(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - nunca dejar que el framework responda HTML/500
            LOGGER.exception("A2A dispatch error")
            return rpc_error(request_id, -32603, f"Internal error: {exc}")

    async def _get_card(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        return rpc_result(request_id, self.agent_card())

    # ------------------------------------------------------------------
    # Validacion comun de un mensaje entrante.
    # ------------------------------------------------------------------
    def _validate_message(self, params: Dict[str, Any]):
        msg = params.get("message")
        if not isinstance(msg, dict):
            raise RpcError(INVALID_PARAMS, "A 'message' object is required in params")
        parts = msg.get("parts")
        if not isinstance(parts, list) or not parts:
            raise RpcError(INVALID_PARAMS, "params.message.parts must be a non-empty array")
        if not parts_to_text(parts).strip():
            raise RpcError(INVALID_PARAMS, "The message must contain at least one text part")
        return msg, parts

    @staticmethod
    def _context_id(msg: Dict[str, Any]) -> str | None:
        """Lee contextId del mensaje, con soporte de `contexts` (v0.3)."""
        cid = msg.get("contextId")
        if not cid:
            contexts = msg.get("contexts")
            if isinstance(contexts, list) and contexts and isinstance(contexts[0], dict):
                cid = contexts[0].get("id")
        return cid or None

    def _resolve_thread(self, msg: Dict[str, Any]):
        """Resuelve taskId + contextId + historial para un mensaje entrante.

        Regla de continuidad (3 casos):
        1. Llega taskId de una task existente  -> reanuda esa task.
        2. Llega contextId de un thread conocido -> reanuda ese hilo.
        3. Nada conocido -> nueva task/hilo.
        """
        provided_task = msg.get("taskId")
        context_id = self._context_id(msg)

        if provided_task and provided_task in self._tasks:
            task_id = provided_task
            context_id = context_id or provided_task
            thread = self._threads.setdefault(
                context_id, list(self._tasks[task_id].get("history") or [])
            )
        else:
            key = context_id or provided_task or new_id()
            thread = self._threads.get(key)
            if thread is not None:
                task_id = self._task_by_thread.get(key) or provided_task or new_id()
            else:
                task_id = provided_task or new_id()
                thread = self._threads[key] = []
                self._task_by_thread[key] = task_id
            context_id = key

        self._task_by_thread[context_id] = task_id
        return task_id, context_id, thread

    def _store_artifact(self, task_id: str, reply: str) -> List[Dict[str, Any]]:
        """Acumula un artifact nuevo en la task y devuelve la lista completa."""
        artifact = {"artifactId": new_id(), "name": "response", "parts": [text_part(reply)]}
        existing = self._tasks.get(task_id)
        artifacts = list(existing.get("artifacts") or []) if existing else []
        artifacts.append(artifact)
        return artifacts

    # ------------------------------------------------------------------
    # message/send: respuesta sincrona con una Task "completed".
    # ------------------------------------------------------------------
    async def _send(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        msg, parts = self._validate_message(params)
        task_id, context_id, thread = self._resolve_thread(msg)

        thread.append(
            {
                "role": "user",
                "parts": parts,
                "messageId": msg.get("messageId") or new_id(),
                "taskId": task_id,
                "contextId": context_id,
            }
        )
        reply = await self._backend.chat(system=self._system, history=[dict(m) for m in thread])
        thread.append(
            {
                "role": "agent",
                "parts": [text_part(reply)],
                "messageId": new_id(),
                "taskId": task_id,
                "contextId": context_id,
            }
        )
        task = self._build_task(task_id, context_id, thread, reply)
        return rpc_result(request_id, task)

    # ------------------------------------------------------------------
    # message/stream: la misma conversacion, pero por SSE (eventos).
    # ------------------------------------------------------------------
    async def _stream(self, request_id: Any, params: Dict[str, Any]) -> StreamingResponse:
        msg, parts = self._validate_message(params)
        task_id, context_id, thread = self._resolve_thread(msg)
        thread.append(
            {
                "role": "user",
                "parts": parts,
                "messageId": msg.get("messageId") or new_id(),
                "taskId": task_id,
                "contextId": context_id,
            }
        )

        async def event_stream() -> AsyncIterator[str]:
            yield sse_event(
                rpc_result(
                    request_id,
                    {
                        "kind": "task",
                        "id": task_id,
                        "contextId": context_id,
                        "status": {"state": SUBMITTED, "timestamp": now_iso()},
                        "history": [dict(m) for m in thread],
                        "metadata": {},
                    },
                )
            )
            yield sse_event(
                rpc_result(
                    request_id,
                    {
                        "kind": "status-update",
                        "taskId": task_id,
                        "contextId": context_id,
                        "status": {"state": WORKING, "timestamp": now_iso()},
                        "final": False,
                    },
                )
            )

            artifact_id = new_id()
            # Buffer de un chunk para poder marcar lastChunk=True al final.
            reply_chunks: List[str] = []
            async for chunk in self._backend.stream(system=self._system, history=[dict(m) for m in thread]):
                reply_chunks.append(chunk)
                yield sse_event(
                    rpc_result(
                        request_id,
                        {
                            "kind": "artifact-update",
                            "taskId": task_id,
                            "contextId": context_id,
                            "artifact": {"artifactId": artifact_id, "parts": [text_part(chunk)]},
                            "append": True,
                            "lastChunk": False,
                        },
                    )
                )

            # El ultimo chunk ya fue emitido con lastChunk=False; advertimos en
            # el README que la senal de fin es el status-update con final:true.
            thread.append(
                {
                    "role": "agent",
                    "parts": [text_part("".join(reply_chunks))],
                    "messageId": new_id(),
                    "taskId": task_id,
                    "contextId": context_id,
                }
            )
            self._build_task(task_id, context_id, thread, "".join(reply_chunks))
            yield sse_event(
                rpc_result(
                    request_id,
                    {
                        "kind": "status-update",
                        "taskId": task_id,
                        "contextId": context_id,
                        "status": {"state": COMPLETED, "timestamp": now_iso()},
                        "final": True,
                    },
                )
            )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # tasks/get y tasks/cancel
    # ------------------------------------------------------------------
    async def _get(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        task_id = params.get("id")
        if task_id:
            task = self._tasks.get(task_id)
            if task is None:
                raise RpcError(TASK_NOT_FOUND, f"Task not found: {task_id}", {"id": task_id})
            return rpc_result(request_id, task)
        # v0.3 permite listar todas las tasks con tasks/get sin id.
        return rpc_result(request_id, {"kind": "task-list", "tasks": list(self._tasks.values())})

    async def _cancel(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        task_id = params.get("id")
        task = self._tasks.get(task_id)
        if task is None:
            raise RpcError(TASK_NOT_FOUND, f"Task not found: {task_id}", {"id": task_id})
        state = task["status"]["state"]
        if state in TERMINAL_STATES:
            raise RpcError(TASK_NOT_CANCELABLE, f"Task {task_id} is already {state}")
        task["status"] = {"state": CANCELED, "timestamp": now_iso()}
        return rpc_result(request_id, task)

    # ------------------------------------------------------------------
    # Builder de la Task que viaja dentro de result.
    # ------------------------------------------------------------------
    def _build_task(self, task_id: str, context_id: str, thread: List[Dict[str, Any]], reply: str) -> Dict[str, Any]:
        artifacts = self._store_artifact(task_id, reply)
        task = {
            "kind": "task",
            "id": task_id,
            "contextId": context_id,
            "status": {"state": COMPLETED, "timestamp": now_iso()},
            "artifacts": artifacts,
            "history": thread,
            "metadata": {},
        }
        self._tasks[task_id] = task
        return task


# -----------------------------------------------------------------------------
# Fabrica de la aplicacion FastAPI.
# -----------------------------------------------------------------------------
def create_app(server: A2AServer) -> FastAPI:
    app = FastAPI(title=server.name, version=server._version)
    # Exponemos el server internamente (util para tests e introspect labor).
    app.state.a2a = server  # type: ignore[attr-defined]

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": server.name, "status": "running", "a2a_version": PROTOCOL_VERSION}

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        return JSONResponse(server.agent_card(), media_type="application/json")

    async def _rpc(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                rpc_error(None, PARSE_ERROR, "Parse error"),
                media_type="application/json",
            )
        return await server.dispatch(body)

    @app.post("/")
    async def jsonrpc_endpoint(request: Request):
        return await _rpc(request)

    # Alias para compatibilidad con clientes que usan /a2a (convencion del ecosistema).
    @app.post("/a2a")
    async def jsonrpc_alias(request: Request):
        return await _rpc(request)

    return app