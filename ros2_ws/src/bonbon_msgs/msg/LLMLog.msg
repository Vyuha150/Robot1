# LLMLog.msg
# Published by llm_orchestrator_node on /llm/log for every request/response pair.
# Full audit trail: prompt, response, latency, safety decisions, RAG context.

std_msgs/Header header

string  log_id               # UUID
string  response_id          # matches LLMResponse.response_id
string  intent_id            # triggering UserIntent.intent_id
string  speaker_id           # who spoke (empty if unknown)

# ── Timing ────────────────────────────────────────────────────────────────────
float32 llm_latency_ms       # wall-clock Ollama inference latency
float32 rag_latency_ms       # retrieval latency
float32 total_latency_ms     # end-to-end pipeline latency

# ── Content (truncated to 2048 chars each for storage efficiency) ─────────────
string  raw_prompt           # full prompt sent to LLM (truncated)
string  raw_llm_output       # raw LLM output before safety filter (truncated)
string  final_response       # response after all filters (truncated)

# ── Safety decisions ──────────────────────────────────────────────────────────
string  safety_filter_result # "SAFE" | "RISKY" | "BLOCKED"
string  safety_filter_reason # why a command was blocked or flagged
bool    hallucination_flagged
string  hallucination_reason

# ── RAG context ───────────────────────────────────────────────────────────────
string[] rag_doc_ids         # IDs of retrieved documents
float32[] rag_scores         # similarity scores

# ── Safety state snapshot ─────────────────────────────────────────────────────
uint8   safety_state         # SafetyState.state at time of request
bool    actuation_permitted
bool    navigation_permitted
