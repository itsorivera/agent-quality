"""A2A protocol v0.3.0 - wire format JSON-RPC 2.0.

Helpers de protocolo "puros" (sin I/O): estructuras, numeros de error,
serializacion de eventos SSE.

Referencia: https://a2a-protocol.org/latest/specification

Nota de arquitectura:
- JSON-RPC 2.0 es el transporte canonico del A2A (tambien hay bindings
  gRPC y REST, pero JSON-RPC es el mas usado y el que implementa LangGraph).
- El discriminador `kind` (task / task-list / artifact-update / status-update)
  es la forma de distinguir respuestas en la version v0.3.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

# --------------------------------------------------------------------------
# Version e identificadores de metodo (operaciones A2A del JSON-RPC transport)
# --------------------------------------------------------------------------
PROTOCOL_VERSION = "0.3.0"

MESSAGE_SEND = "message/send"
MESSAGE_STREAM = "message/stream"
TASKS_GET = "tasks/get"
TASKS_CANCEL = "tasks/cancel"
AGENT_GET_CARD = "agent/getCard"

# --------------------------------------------------------------------------
# JSON-RPC error codes. Los negativos estandar pertenecen a la spec 2.0;
# los -32xxx son definidos por A2A.
# --------------------------------------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002

# Estados de Task (maquina de estados de la spec).
SUBMITTED = "submitted"
WORKING = "working"
COMPLETED = "completed"
CANCELED = "canceled"
FAILED = "failed"
INPUT_REQUIRED = "input-required"
TERMINAL_STATES = frozenset({COMPLETED, CANCELED, FAILED})


def new_id() -> str:
    """Genera un id globalmente unico (messageId, taskId, artifactId...)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Timestamp ISO-8601 UTC (formato usado por la spec)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def text_part(text: str) -> Dict[str, Any]:
    """Construye un TextPart A2A."""
    return {"kind": "text", "text": text}


def parts_to_text(parts: List[Dict[str, Any]] | None) -> str:
    """Extrae todo el texto de una lista de Parts."""
    if not parts:
        return ""
    return "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("kind") == "text" and p.get("text")
    )


def rpc_result(request_id: Any, payload: Any) -> Dict[str, Any]:
    """Envelope JSON-RPC de exito."""
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def rpc_error(request_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    """Envelope JSON-RPC de error."""
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class RpcError(Exception):
    """Excepcion propia del protocolo, traducible a envelope JSON-RPC."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def wrap_error(request_id: Any, err: Exception) -> Dict[str, Any]:
    """Convierte cualquier excepcion en envelope de error (sin filtrar leaks)."""
    if isinstance(err, RpcError):
        return rpc_error(request_id, err.code, err.message, err.data)
    return rpc_error(request_id, INTERNAL_ERROR, f"Internal error: {err}")


# --------------------------------------------------------------------------
# SSE (Server-Sent Events) - usado por message/stream
# --------------------------------------------------------------------------
def sse_event(payload: Any) -> str:
    """Serializa un envelope JSON-RPC como event de SSE.

    Formato de la spec A2A: cada evento es una linea `data: {json}` seguida
    de una linea en blanco. El HTTP response tiene Content-Type text/event-stream.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def chunk_text(text: str, size: int = 24) -> AsyncIterator[str]:
    """Divide texto en trozos de `size` caracteres (util para simular token streaming)."""
    for i in range(0, len(text), size):
        yield text[i : i + size]