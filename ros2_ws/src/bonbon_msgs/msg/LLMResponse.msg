# LLMResponse.msg
# Published by llm_orchestrator_node on /llm/response after each LLM cycle.

# ── Status constants ──────────────────────────────────────────────────────────
uint8 STATUS_OK            = 0   # normal, grounded response
uint8 STATUS_LOW_CONF      = 1   # below confidence threshold, using fallback
uint8 STATUS_SAFETY_BLOCK  = 2   # command filtered by safety layer
uint8 STATUS_HALLUCINATION = 3   # grounding check flagged the response
uint8 STATUS_LLM_ERROR     = 4   # Ollama unavailable or timeout
uint8 STATUS_FALLBACK      = 5   # static fallback template used

std_msgs/Header header

string  response_id          # UUID for correlation with LLMLog
string  request_intent_id    # UserIntent.intent_id that triggered this

# ── Content ───────────────────────────────────────────────────────────────────
string  text                 # final response text after personality + grounding
uint8   status               # one of STATUS_* constants
float32 confidence           # 0.0 – 1.0

# ── Provenance ────────────────────────────────────────────────────────────────
string  model_name           # e.g. "llama3.2:3b"
bool    used_rag             # true = RAG context was injected
uint32  rag_docs_retrieved   # number of RAG documents used
bool    used_tools           # true = at least one tool was called
string[] tools_called        # names of tools invoked

# ── Actions produced ──────────────────────────────────────────────────────────
string  behavior_class       # behavior dispatched (empty = speech only)
bool    tts_dispatched       # true = TTSRequest was published
