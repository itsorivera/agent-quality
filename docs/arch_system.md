# Agentic system with a2a and registry
A2A System detailed breakdown of each component and the agnostic runtime lifecycle.

````artifact
id: a2a-registry-architecture-en
name: Multi-Agent A2A and Registry Architecture
type: mermaid
content: |-
  flowchart TB
    %% Styling and Classes
    classDef client fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0f172a;
    classDef orchestrator fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#0f172a;
    classDef registry fill:#f3e8ff,stroke:#9333ea,stroke-width:2px,color:#0f172a;
    classDef specialist fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#0f172a;
    classDef protocol fill:#fee2e2,stroke:#dc2626,stroke-width:2px,stroke-dasharray: 5 5,color:#0f172a;

    subgraph ClientLayer ["1. User / Ingress Layer"]
      User([User / External Application]):::client
    end

    subgraph OrchestrationLayer ["2. Orchestration Layer (Manager Agent)"]
      PlannerAgent["Travel Planner Agent (Orchestrator)\n• LLM + Task Decomposition"]:::orchestrator
      ClientMCP["MCP Client\n• Dynamic tool resolution"]:::orchestrator
      PlannerAgent <--> ClientMCP
    end

    subgraph GovernanceRegistry ["3. Governance & Discovery Layer (Agent Registry)"]
      Registry["Agent Registry\n(Centralized Catalog)"]:::registry
      
      subgraph Manifests ["Agent Cards (Metadata Repository)"]
        AC1["Agent Card: Dog Walker\n- Skills: Booking, Rates\n- Schema: PetType, Hours\n- Auth: mTLS / Bearer\n- Endpoint: a2a://..."]:::registry
        AC2["Agent Card: Flight Booker\n- Skills: Flights, Seat Selection"]:::registry
      end
      
      Registry --- Manifests
    end

    subgraph ExecutionLayer ["4. Downstream Specialist Execution Layer"]
      SpecialistAgent["Dog Walking Agent (Specialist)\n• Domain-specific / Local LLM"]:::specialist
      A2AServer["A2A Server Interface\n(Adapter / Endpoint)"]:::specialist
      ToolMCP["Tools / Databases / APIs\n(Calendar, Payment Gateway, etc.)"]:::specialist

      A2AServer <--> SpecialistAgent
      SpecialistAgent <--> ToolMCP
    end

    %% Execution Flows and Interactions
    User -->|1. Prompt: 'Trip to Madrid, need a dog walker'| PlannerAgent
    ClientMCP -->|2. Semantic query: 'Find dog walking agent'| Registry
    Registry -->|3. Resolves Agent Card + Auth + URL| ClientMCP
    
    %% A2A Protocol Handshake
    ClientMCP ==>|4. A2A Handshake / Intent Negotiation| A2AServer
    A2AServer -->|5. Delegated task with context/payload| SpecialistAgent
    SpecialistAgent -->|6. Task execution result| A2AServer
    A2AServer ==>|7. Structured A2A response| ClientMCP
    PlannerAgent -->|8. Final consolidated response| User

    %% Protocol Annotation
    class ClientMCP,A2AServer protocol;
````

---

### Architecture & Component Breakdown

This architecture resolves the brittleness of traditional multi-agent systems by moving away from hard-coded integrations toward a model of **late binding** and **dynamic discovery**.

---

#### 1. Orchestrator / Manager Agent (e.g., Travel Planner Agent)
* **Role:** The primary driver that decomposes a broad user intent into discrete, executable sub-tasks.
* **Mechanism:** It does not host domain-specific business logic (such as walking dogs or booking airline seats). Instead, it identifies unresolved dependencies and issues abstract semantic lookup queries to identify candidate specialist agents.

---

#### 2. Agent Registry (Centralized Capability Catalog)
* **Role:** Operates as the **Semantic Service Discovery / Enterprise DNS** for agentic systems.
* **Core Responsibilities:**
  * **Search Index:** Enables semantic lookup of agents by their operational capabilities (*"Who can handle pet services in Madrid?"*) rather than rigid canonical identifiers.
  * **Policy & Governance Boundary:** Enforces enterprise guardrails (which agents are authorized for discovery, RBAC/ABAC access controls, audit trails, and telemetry).
  * **Single Source of Truth:** Changes to specialist endpoints, model versions, or required schemas are updated centrally without breaking consuming client agents.

---

#### 3. Agent Card (Interface Contract & Metadata Manifest)
* **Role:** A machine-readable service contract (the agentic equivalent of an OpenAPI/Swagger spec or a SOAP WSDL), tailored for consumption by LLMs.
* **Key Attributes:**
  * **Skills / Capabilities:** Structured natural language descriptions defining boundaries (what the agent can and cannot do).
  * **Input / Output JSON Schema:** Strict data models required to invoke downstream tools.
  * **Authentication & Policies:** Security expectations (OAuth2 flows, cloud IAM roles, Bearer tokens).
  * **Target Endpoint:** The network transport and protocol routing target (e.g., an A2A or MCP URI).

---

#### 4. A2A Protocol (Agent-to-Agent Communication)
* **Role:** A standardized transport and negotiation protocol designed to facilitate autonomous interaction between heterogeneous agents (regardless of whether they are built with LangGraph, CrewAI, AutoGen, or Vertex AI).
* **Core Responsibilities:**
  * **Context & Intent Handshake:** Manages bi-directional conversation state, correlation IDs, and context propagation.
  * **Asynchronous Lifecycle Support:** Accommodates long-running agent workflows (e.g., operations requiring human-in-the-loop approvals or multi-step batch executions).

---

#### 5. Specialist Agent (e.g., Dog Walking Agent)
* **Role:** An isolated, specialized compute unit optimized for a bounded business domain.
* **Components:**
  * **A2A Server / Adapter:** An ingress facade that surfaces internal capabilities using the standard A2A specification.
  * **Domain Logic / LLM:** A tailored model (fine-tuned or constrained by strict system boundaries) execution loop.
  * **Execution Tools (MCP / Function Calls):** Connectors that interact with external state stores, internal APIs, or databases (calendars, payment gateways, booking systems).

---

### Runtime Execution Lifecycle

1. **Ingress:** The user supplies a composite, high-level prompt to the Orchestrator/Planner Agent.
2. **Gap Analysis:** The orchestrator determines it lacks intrinsic tools or domain capabilities to execute the pet-care requirement.
3. **Registry Discovery:** Utilizing its MCP/Registry client, the orchestrator issues a semantic query to the **Agent Registry**.
4. **Agent Card Resolution:** The registry evaluates permissions and returns the matching Specialist Agent Card containing the contract schema, security parameters, and endpoint.
5. **Late Binding & Handshake (A2A Dispatch):** The orchestrator synthesizes the parameter payload and opens an A2A session with the specialist agent endpoint.
6. **Execution & Return:** The specialist agent acts against its downstream tools/APIs and returns a structured response payload over A2A.
7. **Synthesis:** The orchestrator incorporates the specialist output into the overall itinerary plan and presents the final unified response to the user.