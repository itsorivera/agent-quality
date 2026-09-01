"""Adaptador del a2a-sdk (patron Adapter), generico y sin transporte.

Core del paquete: traduce el ciclo de vida de una Task del SDK
(Message/Part protobuf) al contrato ChatBackend (dicts) que habla con el
proveedor de LLM. Las recetas de agents/ lo reutilizan como "cableado" comun;
esta es la pieza que LangGraph resuelve con su adaptador A2A.

No lee env, no importa FastAPI, no construye cards: solo ejecucion.
"""

from __future__ import annotations

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Role, TaskState

from sdk_variant.ports.llm import ChatBackend


class SdkChatAgent:
    """Delega en un ChatBackend (echo | openai | reglas) siguiendo el contrato.

    Es el adaptador de entrada del protocolo -> backend: traduce historial
    protobuf a la forma que ChatBackend entiende.
    """

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


class SdkChatExecutor(AgentExecutor):
    """Traduce el ciclo de vida de una Task A2A a llamadas al backend.

    Aqui el SDK encola los estados via TaskUpdater y el DefaultRequestHandler
    se encarga de persistir y serializar. La continuidad de una conversacion
    se hace por contextId (en v1.0 las tasks son inmutables).
    """

    def __init__(self, agent: SdkChatAgent):
        self._agent = agent
        # Multiturn por contexto en memoria. En v1.0 las Tasks son inmutables:
        # una task "completed" no admite mas mensajes. La continuidad de un
        # chat se hace enviando el MISMO contextId (thread).
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