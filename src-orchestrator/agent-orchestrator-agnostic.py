"""
OrchestratorAgent (LangGraph Edition)
Agnostic multi-agent orchestration replacing Google ADK and Cloud Registry.

Workflow:
  User Query -> extract_topic -> find_in_registry -> dispatch_a2a -> Output
"""

import asyncio
import os
import sys
from typing import Dict, Any, Optional
from typing_extensions import TypedDict
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
# Puedes cambiar de proveedor sin tocar el flujo:
# from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END


# ===========================================================================
# 1. Simulación Agnóstica del Agent Registry (Agent Cards Catalog)
# ===========================================================================
# En producción, esto se consulta desde PostgreSQL (pgvector), DynamoDB o un servidor MCP.
LOCAL_AGENT_REGISTRY = [
    {
        "resource_name": "projects/my-enterprise/locations/global/agents/pet-care-agent",
        "name": "Dog Walking & Pet Care Specialist",
        "description": "Handles scheduling, availability, and requests for dog walking, pet sitting, and animal care.",
        "skills": ["dog walk", "pet sitting", "veterinary appointment", "dog walker"],
        "endpoint": "http://localhost:8001/a2a",
    },
    {
        "resource_name": "projects/my-enterprise/locations/global/agents/trip-planner-agent",
        "name": "Global Travel & Itinerary Specialist",
        "description": "Assists with flight booking, hotel reservations, vacation scheduling, and travel guides.",
        "skills": ["trip planning", "vacation", "flight booking", "hotel reservation"],
        "endpoint": "http://localhost:8002/a2a",
    },
    {
        "resource_name": "projects/my-enterprise/locations/global/agents/weather-agent",
        "name": "Meteorological Services Agent",
        "description": "Provides weather forecasts, alerts, and climatological reports.",
        "skills": ["weather report", "temperature forecast", "rain check"],
        "endpoint": "http://localhost:8003/a2a",
    }
]

def search_registry(search_query: str) -> Optional[Dict[str, Any]]:
    """
    Simula la búsqueda semántica / léxica del Agent Registry.
    Retorna la primera Agent Card coincidente.
    """
    normalized_query = search_query.lower()
    for agent in LOCAL_AGENT_REGISTRY:
        # Match por keywords o substrings en skills / descripción
        if any(skill in normalized_query or normalized_query in skill for skill in agent["skills"]):
            return agent
        if normalized_query in agent["description"].lower():
            return agent
    # Fallback: primer agente si no hay match directo (como definía tu instrucción previa)
    return LOCAL_AGENT_REGISTRY[0] if LOCAL_AGENT_REGISTRY else None


# ===========================================================================
# 2. Mock del Cliente A2A (Agnóstico a HTTP / gRPC / MCP)
# ===========================================================================
async def call_remote_a2a_agent(agent_card: Dict[str, Any], message: str) -> str:
    """
    Simula el handshake y despacho hacia el endpoint A2A remoto.
    """
    endpoint = agent_card.get("endpoint")
    resource_name = agent_card.get("name")
    
    # Aquí iría el cliente httpx/aiohttp enviando el JSON envelope según el protocolo A2A
    await asyncio.sleep(0.5) # Simulación de latencia de red
    return (
        f"[A2A Response from {resource_name} ({endpoint})]: "
        f"Successfully processed request: '{message}'. Task scheduled successfully."
    )


# ===========================================================================
# 3. Definición del Estado de LangGraph
# ===========================================================================
class OrchestratorState(TypedDict):
    original_message: str
    primary_topic: Optional[str]
    agent_card: Optional[Dict[str, Any]]
    final_response: Optional[str]


# ===========================================================================
# 4. Definición de Nodos de la Arquitectura
# ===========================================================================
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

TOPIC_INSTRUCTION = """You extract the SINGLE primary topic from the user's message.

Rules:
- Output ONLY the topic phrase on one line — no preamble, no punctuation, no quotes.
- If the user mentions multiple topics, pick ONE: usually the first concrete request,
  or the bigger task. Side requests and afterthoughts are NOT the primary topic.
- Valid examples: "dog walk", "trip planning", "weather report", "code review".
"""

async def topic_extractor_node(state: OrchestratorState) -> Dict[str, Any]:
    prompt = ChatPromptTemplate.from_messages([
        ("system", TOPIC_INSTRUCTION),
        ("user", "{input}")
    ])
    chain = prompt | llm
    response = await chain.ainvoke({"input": state["original_message"]})
    topic = response.content.strip().strip('"').strip("'")
    print(f"  [topic_extractor] → Extracted topic: '{topic}'")
    return {"primary_topic": topic}


async def registry_finder_node(state: OrchestratorState) -> Dict[str, Any]:
    topic = state.get("primary_topic", "")
    # Ejecuta el discovery agnóstico
    agent_card = search_registry(topic)
    print(f"  [registry_finder] → Found agent: {agent_card['name']} ({agent_card['resource_name']})")
    return {"agent_card": agent_card}


async def a2a_dispatcher_node(state: OrchestratorState) -> Dict[str, Any]:
    agent_card = state["agent_card"]
    original_message = state["original_message"]
    
    if not agent_card:
        return {"final_response": "Error: No suitable agent was found in the registry."}
    
    print(f"  [a2a_dispatcher] → Calling remote A2A endpoint: {agent_card['endpoint']}")
    # Enviar caracter por caracter el mensaje original (regla estricta)
    response = await call_remote_a2a_agent(agent_card, original_message)
    return {"final_response": response}


# ===========================================================================
# 5. Compilación del Grafo (LangGraph Workflow)
# ===========================================================================
workflow = StateGraph(OrchestratorState)

workflow.add_node("topic_extractor", topic_extractor_node)
workflow.add_node("registry_finder", registry_finder_node)
workflow.add_node("a2a_dispatcher", a2a_dispatcher_node)

# Flujo Secuencial
workflow.set_entry_point("topic_extractor")
workflow.add_edge("topic_extractor", "registry_finder")
workflow.add_edge("registry_finder", "a2a_dispatcher")
workflow.add_edge("a2a_dispatcher", END)

orchestrator_graph = workflow.compile()


# ===========================================================================
# 6. Runtime Execution
# ===========================================================================
async def main():
    query = (
        sys.argv[1] 
        if len(sys.argv) > 1 
        else "Walk Buddy this afternoon, we live near 24th and Mission SF."
    )
    
    print("=" * 60)
    print(f"Orchestrator request: {query}")
    print("=" * 60)

    initial_state: OrchestratorState = {
        "original_message": query,
        "primary_topic": None,
        "agent_card": None,
        "final_response": None,
    }

    result = await orchestrator_graph.ainvoke(initial_state)

    print("\n" + "=" * 60)
    print("FINAL RESPONSE:")
    print("=" * 60)
    print(result.get("final_response"))
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
