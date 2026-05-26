# bonbon_llm — LLM + Response Generation Module

LLM-powered conversation and response generation for the **BonBon** café service
robot. Wraps a local **Ollama** model with a full safety stack, RAG knowledge
grounding, tool/function calling, hallucination prevention, and a spoken-output
personality layer — all as a ROS2 LifecycleNode.

---

## Architecture

```
 /perception/intent ──────────────────────────────────────────────────────────┐
 /perception/scene  ──────┐                                                   │
 /bonbon/safety/state ────┤                                                   │
 /perception/risks  ──────┘                                                   │
                           ┌────────────────────────────────────────────────┐ │
                           │           LLMOrchestratorNode                  │ │
                           │                                                │ │
                           │  ┌─────────────┐    ┌──────────────────────┐  │ │
                           │  │ RAGRetriever│───►│   OllamaClient        │  │ │
                           │  │  (ChromaDB/ │    │   (llama3.2:3b)      │  │ │
                           │  │  FAISS/     │    │                      │  │ │
                           │  │  NumPy)     │    │  LangChainBridge     │  │ │
                           │  └─────────────┘    └──────────┬───────────┘  │ │
                           │                                │               │ │
                           │  ┌─────────────────────────────▼─────────────┐│ │
                           │  │              SafetyCommandFilter           ││ │
                           │  │  BLOCKED → hard deny  RISKY → authorize   ││ │
                           │  └──────────────────────────┬────────────────┘│ │
                           │                             │                  │ │
                           │  ┌──────────────────────────▼────────────────┐│ │
                           │  │              CommandAuthorizer             ││ │
                           │  │  checks live SafetyState before dispatch   ││ │
                           │  └──────────────────────────┬────────────────┘│ │
                           │                             │                  │ │
                           │  ┌──────────────────────────▼────────────────┐│ │
                           │  │             HallucinationGuard             ││ │
                           │  │  impossible claims · fabricated prices     ││ │
                           │  │  velocity bounds · grounding score         ││ │
                           │  └──────────────────────────┬────────────────┘│ │
                           │                             │                  │ │
                           │  ┌──────────────────────────▼────────────────┐│ │
                           │  │              PersonalityLayer              ││ │
                           │  │  markdown strip · word-limit · TTS format  ││ │
                           │  └──────────────────────────┬────────────────┘│ │
                           │                             │                  │ │
                           │  ┌──────────────────────────▼────────────────┐│ │
                           │  │               ResponseLogger               ││ │
                           │  │  bounded deque · ROS2 /llm/log publisher   ││ │
                           │  └────────────────────────────────────────────┘│ │
                           └────────────────────────────────────────────────┘ │
                                                                              │
 /llm/response ◄──────────────────────────────────────────────────────────────┘
 /bonbon/tts/request ◄─────────────────────────────────────────────────────────
 /perception/behavior ◄────────────────────────────────────────────────────────
 /llm/log ◄────────────────────────────────────────────────────────────────────
 /health/llm ◄─────────────────────────────────────────────────────────────────
```

### Core constraint

> **The LLM never directly controls actuators or navigation.**
> All motion requests are emitted as `BehaviorRecommendation` messages and
> validated by the Safety Supervisor + Behavior Engine before execution.

---

## Topics

### Subscribed

| Topic | Type | Description |
|---|---|---|
| `/perception/intent` | `bonbon_msgs/IntentResult` | Main trigger — starts the LLM pipeline |
| `/perception/scene` | `bonbon_msgs/SceneSummary` | Live scene context snapshot |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | Current robot safety state |
| `/perception/risks` | `bonbon_msgs/RiskAssessment` | Risk assessment from the perception stack |
| `/speech/command` | `std_msgs/String` | Raw speech input (fallback trigger) |

### Published

| Topic | Type | Description |
|---|---|---|
| `/llm/response` | `bonbon_msgs/LLMResponse` | Final grounded, filtered response |
| `/llm/log` | `bonbon_msgs/LLMLog` | Full audit log entry (prompt, output, latencies) |
| `/bonbon/tts/request` | `bonbon_msgs/TTSRequest` | Text dispatched to TTS engine |
| `/perception/behavior` | `bonbon_msgs/BehaviorRecommendation` | Requested robot behaviour (post-filter) |
| `/health/llm` | `std_msgs/String` | Node health status at 1 Hz |

### Services

| Service | Type | Description |
|---|---|---|
| `/llm/query` | `bonbon_srvs/LLMQuery` | Synchronous LLM query for other nodes |

---

## Parameters

All parameters can be passed as launch arguments to `llm.launch.py`.

### Ollama / LLM

| Parameter | Default | Description |
|---|---|---|
| `ollama.base_url` | `http://localhost:11434` | Ollama server URL |
| `ollama.model` | `llama3.2:3b` | Model name (must be pulled) |
| `ollama.timeout_sec` | `30.0` | Request timeout in seconds |
| `ollama.temperature` | `0.4` | Sampling temperature (0=deterministic) |
| `ollama.max_tokens` | `256` | Maximum response tokens |
| `ollama.num_ctx` | `4096` | Context window size |

### RAG / Knowledge Base

| Parameter | Default | Description |
|---|---|---|
| `rag.backend` | `chroma` | Vector store: `chroma` \| `faiss` \| `numpy` |
| `rag.persist_dir` | `""` | ChromaDB persistence directory (empty = in-memory) |
| `rag.collection_name` | `bonbon_knowledge` | ChromaDB collection name |
| `rag.embedding_model` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `rag.top_k` | `5` | Documents retrieved per query |
| `rag.similarity_threshold` | `0.35` | Minimum cosine similarity (0–1) |
| `rag.max_context_tokens` | `800` | Hard cap on injected RAG text |

### Hallucination Guard

| Parameter | Default | Description |
|---|---|---|
| `hallucination.enabled` | `true` | Enable/disable the guard |
| `hallucination.min_grounding_score` | `0.30` | Min keyword-overlap score |
| `hallucination.ungrounded_fallback_threshold` | `0.50` | Min confidence to use ungrounded output |

### Safety Filter

| Parameter | Default | Description |
|---|---|---|
| `safety_filter.min_risky_confidence` | `0.80` | Min LLM confidence for risky commands |

### Personality

| Parameter | Default | Description |
|---|---|---|
| `personality.name` | `BonBon` | Robot's spoken name |
| `personality.max_response_words` | `40` | Maximum words per TTS response |
| `personality.language_adapt` | `true` | Mirror user's language (EN/ZH/MS) |

### Pipeline

| Parameter | Default | Description |
|---|---|---|
| `min_confidence_threshold` | `0.45` | Below this → use `low_confidence` fallback |
| `use_langchain` | `true` | Use LangChain chain; falls back to direct Ollama |
| `use_tools` | `true` | Enable OpenAI-compatible tool calling |
| `use_rag` | `true` | Enable RAG retrieval |
| `simulation` | `false` | Disable real Ollama calls (CI/testing) |
| `health_rate_hz` | `1.0` | Health topic publish rate |

---

## Launch

```bash
# Default — local Ollama, ChromaDB in-memory
ros2 launch bonbon_llm llm.launch.py

# Different model, FAISS backend
ros2 launch bonbon_llm llm.launch.py \
  ollama_model:=mistral:7b \
  rag_backend:=faiss

# Debug logging
ros2 launch bonbon_llm llm.launch.py log_level:=debug

# Persistent ChromaDB knowledge base
ros2 launch bonbon_llm llm.launch.py \
  rag_backend:=chroma \
  rag_persist_dir:=/var/bonbon/knowledge

# CI / headless tests (no Ollama needed)
ros2 launch bonbon_llm llm.launch.py simulation:=true
```

### Lifecycle management

```bash
# Configure + activate manually
ros2 lifecycle set /llm_orchestrator configure
ros2 lifecycle set /llm_orchestrator activate

# Inspect state
ros2 lifecycle get /llm_orchestrator
```

---

## Dependencies

### Required

| Package | Notes |
|---|---|
| `rclpy` | ROS2 Python client library |
| `bonbon_msgs` | `LLMResponse`, `LLMLog`, `BehaviorRecommendation`, etc. |
| `bonbon_srvs` | `LLMQuery` service |
| `numpy` | Always available; used as RAG fallback backend |

### Optional (graceful degradation)

| Package | Install | Effect when absent |
|---|---|---|
| `ollama` | `pip install ollama` | Falls back to urllib HTTP client |
| `langchain` + `langchain-ollama` | `pip install langchain langchain-ollama` | Direct Ollama client used |
| `chromadb` + `langchain-chroma` | `pip install chromadb langchain-chroma` | Falls back to FAISS or NumPy |
| `faiss-cpu` | `pip install faiss-cpu` | Falls back to NumPy cosine |
| `sentence-transformers` | `pip install sentence-transformers` | Falls back to TF-IDF hash embedding |

> **No external API keys required.** Everything runs locally via Ollama.
> Pull the default model: `ollama pull llama3.2:3b`

---

## Tool / Function Calling

The orchestrator exposes 6 OpenAI-compatible tools to the LLM:

| Tool | Side-effects | Safety-checked |
|---|---|---|
| `speak_to_user(text, priority)` | Dispatches to TTS | Yes — text safety filter |
| `request_behavior(behavior_class, params, confidence)` | Emits BehaviorRecommendation | Yes — filter + authorizer |
| `get_menu_info(item)` | RAG lookup | None (read-only) |
| `get_scene_context()` | Reads sensor snapshot | None (read-only) |
| `get_safety_state()` | Reads SafetyState | None (read-only) |
| `query_memory(query, k)` | Reads episodic memory | None (read-only) |

Valid `behavior_class` values: `idle`, `approach_person`, `serve_item`,
`navigate_to_goal`, `stop_navigation`, `wait_for_input`.

---

## Safety Stack

### Layer 1 — SafetyCommandFilter

Hard-blocks any text or behavior containing direct hardware references:

```
cmd_vel  geometry_msgs  Twist  NavigateToPose  nav2  move_base
GPIO  servo.*angle  direct.*motor  PWM
os.system  subprocess  eval(  exec(
```

Result: **BLOCKED** (hard deny) | **RISKY** (needs authorization) | **SAFE**

### Layer 2 — CommandAuthorizer

Gates against live `SafetyState` before any motion is dispatched:

| Behavior class | Required safety state | Required flag |
|---|---|---|
| `navigate_to_goal` | `NORMAL` or `DOCKING` | `navigation_permitted = True` |
| `approach_person` | `NORMAL` or `DOCKING` | `navigation_permitted = True` |
| `serve_item` | `NORMAL` | `actuation_permitted = True` |
| `idle`, `wait_for_input`, `stop_navigation` | Any | — |
| Speech (`speak_to_user`) | Any | — |

### Layer 3 — HallucinationGuard

Detects and removes impossible claims before TTS dispatch:

- **Capability claims**: "I can fly", "I have arms", "I am a human", "I can access the internet", etc.
- **Fabricated prices**: SGD prices not found in any RAG document
- **Implausible speeds**: velocity claims > 1.5 m/s (BonBon max = 0.8 m/s)
- **Grounding score**: keyword-overlap between response and retrieved documents

---

## RAG Backends

| Backend | Install | Performance | Production use |
|---|---|---|---|
| **ChromaDB** | `pip install chromadb langchain-chroma` | Fast, persistent | Recommended |
| **FAISS** | `pip install faiss-cpu` | Fast, in-memory | Good for single-machine |
| **NumPy** | Built-in | Adequate (< 50 ms p99 at 8 docs) | Tests / fallback |

The backend is selected automatically at startup in priority order
(ChromaDB → FAISS → NumPy). Override with `rag_backend:=numpy`.

### Default knowledge base

Eight documents are seeded at startup:

| Category | Content |
|---|---|
| `robot_capabilities` | Speed limits, payload, speech, navigation |
| `safety_rules` | Stop conditions, navigation gates, hardware constraints |
| `menu` | All 10 items with SGD prices |
| `locations` | Tables 1–10, counter, kitchen, entrance |
| `conversation_rules` | Response style, language, honesty |
| `robot_limitations` | Cannot fly, lift heavy, access internet, etc. |
| `emergency` | Staff escalation, dial 995 |
| `operations` | Opening hours, maintenance windows |

Add custom documents at runtime:

```python
from bonbon_llm.core.rag_retriever import RAGRetriever
rag.add_document("Today's special: Pandan Latte at S$6.00.", metadata={"category": "daily_special"})
```

---

## Fallback Templates

When the LLM fails, confidence is low, or safety blocks a response, a static
template is used (never leaves the customer without a next step):

| Key | Short variant |
|---|---|
| `llm_error` | "Sorry, I'm having a moment. Could you repeat that?" |
| `low_confidence` | "I'm not quite sure I understood. Could you say that again?" |
| `safety_block` | "I can't do that right now for safety reasons." |
| `hallucination` | "I'm not sure about that — let me get a staff member to help." |
| `unknown_request` | "I didn't catch that. What would you like?" |
| `navigation_denied` | "I can't navigate right now. Please ask a staff member." |
| `actuation_denied` | "I can't serve items right now. Please ask a staff member." |
| `emergency` | "Please speak to staff immediately. Help is on the way." |
| `greeting` | "Hello! Welcome to the café. What can I get you today?" |
| `timeout` | "I'm still thinking — just a moment!" |
| `ambiguous` | "Could you be a little more specific? What would you like?" |
| `out_of_scope` | "I can't help with that, but I can take orders and answer café questions." |
| `silent` | "I'm here if you need anything!" |

---

## Latency Budgets

Measured on a mid-range laptop (Intel i7, no GPU), NumPy RAG backend, p99:

| Component | Budget | Typical p99 |
|---|---|---|
| `SafetyCommandFilter.filter_text` | < 1 ms | ~0.05 ms |
| `HallucinationGuard.check` | < 1 ms | ~0.08 ms |
| `PersonalityLayer.apply` | < 2 ms | ~0.15 ms |
| `RAGRetriever.retrieve` (NumPy, 8 docs) | < 50 ms | ~2 ms |
| `ToolRegistry.dispatch` (read-only) | < 5 ms | ~0.3 ms |
| Full pipeline (no LLM) | < 75 ms | ~5 ms |
| Ollama inference (llama3.2:3b, CPU) | — | 5–30 s |

Run the benchmarks:
```bash
python -m tests.benchmarks.bench_llm
# or with strict budget enforcement:
STRICT=1 python -m tests.benchmarks.bench_llm
```

---

## Tests

```bash
# All unit tests
pytest tests/ -v --tb=short

# Safety filter tests (unsafe command scenarios)
pytest tests/test_command_filter.py -v

# Hallucination tests
pytest tests/test_hallucination_guard.py -v

# Low-confidence + integration scenarios
pytest tests/integration/ -v

# Benchmarks
pytest tests/benchmarks/ -v -s

# Specific test class
pytest tests/test_tool_registry.py::TestUnsafeCommandsBlocked -v
```

---

## Package Layout

```
bonbon_llm/
├── bonbon_llm/
│   ├── __init__.py              # Full public API
│   ├── config/
│   │   └── llm_config.py        # OllamaConfig, RAGConfig, LLMConfig, etc.
│   ├── core/
│   │   ├── ollama_client.py     # Ollama HTTP client (SDK + urllib fallback)
│   │   ├── rag_retriever.py     # ChromaDB/FAISS/NumPy RAG retriever
│   │   ├── langchain_bridge.py  # LangChain chain builders (lazy import)
│   │   └── response_logger.py   # Bounded audit log + ROS2 publisher
│   ├── safety/
│   │   ├── command_filter.py    # Three-tier text + behavior filter
│   │   ├── authorization.py     # SafetyState-gated command authorization
│   │   └── hallucination_guard.py # Grounding + impossible claim detection
│   ├── personality/
│   │   └── personality_layer.py # Markdown strip, TTS format, word limit
│   ├── prompts/
│   │   ├── system_prompt.py     # SYSTEM_PROMPT + context injection template
│   │   └── response_templates.py# 13 static fallback templates
│   ├── tools/
│   │   └── tool_registry.py     # 6 OpenAI-compatible tools + dispatcher
│   └── nodes/
│       └── llm_orchestrator_node.py  # ROS2 LifecycleNode
├── launch/
│   └── llm.launch.py            # Launch file with all parameters exposed
├── tests/
│   ├── test_command_filter.py
│   ├── test_authorization.py
│   ├── test_hallucination_guard.py
│   ├── test_rag_retriever.py
│   ├── test_response_logger.py
│   ├── test_personality_layer.py
│   ├── test_tool_registry.py
│   ├── test_llm_orchestrator.py
│   ├── integration/
│   │   └── test_llm_integration.py
│   └── benchmarks/
│       └── bench_llm.py
└── README.md
```

---

## Extension Guide

### Add a new tool

1. Add the JSON schema to `TOOL_SCHEMAS` in `tools/tool_registry.py`
2. Add a `_handle_<name>` method to `ToolRegistry`
3. Register it in `_get_handler()`
4. Add unit tests in `tests/test_tool_registry.py`

### Add a new fallback template

```python
# prompts/response_templates.py
_reg("my_situation",
     "Short version (≤15 words).",
     "Long version with more context for the customer.")
```

### Add knowledge documents at runtime

```python
node.rag_retriever.add_document(
    "Seasonal special: Pandan Latte at S$6.00. Available until Sunday.",
    metadata={"category": "daily_special", "valid_until": "2026-01-31"},
)
```

### Replace the LLM backend

Implement an object with:
```python
def generate(self, prompt: str, **kwargs) -> OllamaResponse: ...
def is_available(self) -> bool: ...
```
Then inject it via `LLMOrchestratorNode._ollama` before activation.

---

## Security Notes

- **No API keys required or stored.** Ollama runs entirely locally.
- **No audio stored** by default (see `bonbon_speech` privacy settings).
- **No cross-session memory** — each ROS2 session starts fresh.
- All LLM outputs pass through three independent safety checks before any
  side-effect is produced.
- Blocked commands are logged with the full prompt and reason for audit.
