"""Agente A2A implementado con el SDK oficial `a2a-sdk` (v1.1.x, protocol v1.0).

Comparalo cara a cara con `a2a_agent/server.py` (implementacion manual v0.3):
misma logica de negocio (el backend de `a2a_agent/llm.py`), pero el wire format
y la maquina de estados los resuelve la libreria. Esta es la "caja negra": nos
otros escribimos el executor (logica) y la configuracion (AgentCard/AgentSkill),
y NO tocamos JSON-RPC, SSE, validacion pydantic/protobuf ni el versionado.

Diferencias que vas a ver en el cable (dispatcher oficial, ver
`a2a/server/routes/jsonrpc_dispatcher.py`):
  - Metodos JSON-RPC PascalCase: SendMessage, GetTask, ListTasks, CancelTask...
    vs. los kebab-case de v0.3 (message/send, tasks/get, ...).
  - El header `A2A-Version: 1.0`: la negociacion de version es parte del
    protocolo (en v0.3 no existia el header; el metodo decia la intencion).
  - En el SDK 1.1.x los tipos de mensaje (Message, Task, Part...) son protobuf
    (`a2a_pb2`). Solo el Agent Card de descubrimiento es pydantic.
  - El resultado de SendMessage en el firewall es la Task (maquina de estados
    submitted -> working -> completed) y se acumula en el InMemoryTaskStore.
"""

from __future__ import annotations

import os
import sys

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from dotenv import load_dotenv
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_rest_routes  # solo documentacion: binding REST opcional
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
    TaskState,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0  # type: ignore[attr-defined]
from fastapi import FastAPI

from sdk_variant.assembly import AgentSpec, mount_a2a_endpoints

from a2a_agent.llm import ChatBackend, build_backend

# ---------------------------------------------------------------------------
# Logica de negocio: igual que en la variante manual, detras de ChatBackend.
# ---------------------------------------------------------------------------


class SdkChatAgent:
    """Delega en el mismo ChatBackend que usa el server manual (echo | openai)."""

    def __init__(self, backend: ChatBackend, system_prompt: str):
        self._backend = backend
        self._system = system_prompt

    @staticmethod
    def _to_backend_history(messages: list) -> list[dict]:
        """Traduce mensajes protobuf del SDK al formato dict de ChatBackend.

        Los Part del SDK 1.1.x son protobuf sin discriminador `kind`; nuestro
        backend espera {"kind": "text", "text": ...} (mismo formato que el
        server manual). Esta traduccion es el mismo "puente" que hace LangGraph.
        """
        out: list[dict] = []
        for m in messages:
            parts = []
            for p in m.parts:
                if p.HasField("text") and p.text:
                    parts.append({"kind": "text", "text": p.text})
            if not parts:
                continue
            out.append({"role": "user" if m.role == Role.ROLE_USER else "agent", "parts": parts})
        return out

    async def invoke(self, *, query: str, history_messages: list) -> str:
        return await self._backend.chat(
            system=self._system, history=self._to_backend_history(history_messages)
        )


# ---------------------------------------------------------------------------
# Executor: la unica pieza que el SDK nos pide implementar.
# ---------------------------------------------------------------------------


class SdkChatExecutor(AgentExecutor):
    """Traduce el ciclo de vida de una Task A2A a llamadas al backend.

    Compara con `A2AServer._send` del server manual: alli escribiamos a mano
    la maquina de estados (task -> status working/completed + artifacts) y el
    historial; aqui el SDK encola los estados via TaskUpdater y el
    DefaultRequestHandler se encarga de persistir y serializar.
    """

    def __init__(self, agent: SdkChatAgent):
        self._agent = agent
        # Multiturn por contexto en memoria. En v1.0 las Tasks son inmutables:
        # una task "completed" no admite mas mensajes. La continuidad de un
        # chat se hace enviando el MISMO contextId (thread); aqui guardamos el
        # historial igual que _threads del server manual (pero con context_id).
        self._threads: dict[str, list] = {}

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # 1. La task del contexto (si el cliente mando un taskId vigente) o una nueva.
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        # 2. Registra el turno del usuario en el hilo conversacional (por context).
        thread_key = task.context_id or task.id
        thread = self._threads.setdefault(thread_key, [])
        thread.append(context.message)

        # 3. Estado working (el SDK serializa el status-update al cliente).
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task.id, context_id=task.context_id
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Processing request..."),
        )

        # 4. Invoca al backend (echo/openai) igual que el server manual.
        query = get_message_text(context.message)
        result = (
            await self._agent.invoke(query=query, history_messages=thread)
            if query.strip()
            else "No text input is provided!"
        )

        # 5. Publica el artifact con la respuesta y cierra con estado completed.
        await updater.add_artifact(parts=[new_text_part(text=result, media_type="text/plain")])
        self._threads[thread_key] = thread
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Request is completed!"),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


# ---------------------------------------------------------------------------
# Receta del agente: TRANSPORTE-FREE. La placa web (FastAPI + rutas A2A) se
# ensambla en sdk_variant/assembly.py (montaje) y sdk_variant/app.py (la
# aplicacion del gateway). agent.py solo produce los "ingredientes": el
# executor, la card y el handler que el composition root montara.
# ---------------------------------------------------------------------------


def build_sdk_agent() -> AgentSpec:
    """Construye la receta del agente conversacional (sin I/O, sin transporte).

    Lee las mismas env vars que la variante manual: CHAT_PROVIDER,
    OPENAI_API_KEY, OPENAI_MODEL, AGENT_NAME, AGENT_DESCRIPTION, PORT.

    Devuelve un AgentSpec (agent_id, card, handler); NO construye FastAPI ni
    monta rutas. De eso se encarga el composition root (app.py) o el wrapper
    de compat build_sdk_agent_app().
    """
    load_dotenv(override=True)

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "2024"))
    name = os.getenv("AGENT_NAME", "SDK Conversational Agent")
    description = os.getenv(
        "AGENT_DESCRIPTION", "A conversational agent exposed over A2A via the official SDK."
    )
    public_url = (os.getenv("PUBLIC_URL") or f"http://{host}:{port}").rstrip("/")
    system_prompt = os.getenv("SYSTEM_PROMPT") or f"You are {name}. {description}"

    backend = build_backend(
        os.getenv("CHAT_PROVIDER", "echo"),
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        agent_name=name,
    )

    skill = AgentSkill(
        id="conversation",
        name="Conversational Chat",
        description="Participates in text conversations via the A2A protocol (SDK implementation).",
        tags=["chat", "conversation", "sdk"],
        examples=["Hello", "What can you help me with?"],
    )
    agent_card = AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"{public_url}/",  # la corrige mount_a2a_endpoints si es multi-agente
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=SdkChatExecutor(SdkChatAgent(backend, system_prompt)),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    return AgentSpec(
        agent_id="conversational",
        name=name,
        description=description,
        card=agent_card,
        handler=request_handler,
    )


def build_sdk_agent_app():
    """Compat de un solo agente montado en la raiz (card en /.well-known).

    Se mantiene para los tests y para el modo single-agent. Es el UNICO modulo
    de tipo agente que ensambla transporte: la ruta enterprise de la industria
    para N agentes es sdk_variant.app.create_app() (composition root).
    """
    spec = build_sdk_agent()
    app = FastAPI(title=spec.name, version="0.1.0")
    mount_a2a_endpoints(app, spec, root=True)
    app.state.a2a = spec.handler  # util para tests
    return app