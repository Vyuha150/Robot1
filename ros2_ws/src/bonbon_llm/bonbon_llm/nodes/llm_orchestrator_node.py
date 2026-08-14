"""
bonbon_llm.nodes.llm_orchestrator_node
========================================
ROS2 LifecycleNode — LLM + Response Generation pipeline.

Subscriptions
-------------
/perception/intent          UserIntent        (event)
/perception/scene           SemanticScene     (≤10 Hz, cached)
/bonbon/safety/state        SafetyState       (10 Hz, cached)
/speech/command             SpeechCommand     (event, for raw text fallback)
/perception/risks           RiskEvent         (event, cached)

Publications
------------
/llm/response               LLMResponse       (on each intent)
/llm/log                    LLMLog            (on each intent)
/bonbon/tts/request         TTSRequest        (on speech response)
/perception/behavior        BehaviorRecommendation (on behavior dispatch)
/health/llm                 ModuleHealth      (1 Hz)

Pipeline (per UserIntent)
--------------------------
1. Receive UserIntent from /perception/intent
2. Build scene + safety context string
3. ResponseCache check, keyed on (question, scene+safety context) — a hit
   skips RAG retrieval AND the LLM call entirely; a miss retrieves RAG
   documents, builds the full prompt, and calls Ollama via LangChain
   (with timeout + retry); the cache key never includes RAG results, so a
   change to scene/safety always misses correctly
4. Safety-filter raw LLM output (BLOCKED → fallback immediately) — runs on
   every cycle, cached or not
5. Hallucination guard check (flag → use safe_response) — runs on every
   cycle, cached or not
6. Apply personality layer (length cap, TTS format, affirmation)
7. Dispatch TTS
8. Authorize any behavior commands against live SafetyState, then dispatch
9. Publish LLMResponse on /llm/response
10. Log full request/response via ResponseLogger

Lifecycle
---------
unconfigured → on_configure  → inactive   (loads pipeline, opens RAG)
inactive     → on_activate   → active     (starts health timer, subscribes)
active       → on_deactivate → inactive   (cancels timers, clears buffers)
inactive     → on_cleanup    → unconfigured (closes RAG, releases memory)

Safety guarantees
-----------------
* LLM output NEVER reaches cmd_vel, nav2, or GPIO directly.
* Actuation is only requested via BehaviorRecommendation messages that
  are consumed by the Safety Supervisor / Behavior Engine.
* Every LLM failure (timeout, error, hallucination) uses a static
  fallback template so the robot always responds.
* All responses (including blocked ones) are logged.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

logger = logging.getLogger(__name__)

# ── QoS profiles ─────────────────────────────────────────────────────────────
_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_BEST_EFFORT = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

# /bonbon/safety/state publishes at 10 Hz when the Safety Supervisor is
# alive (see module docstring). If no message has been received within
# this window, treat the safety snapshot as stale rather than reusing a
# possibly-outdated one forever -- mirrors
# SafetyStopBridge.watchdog_timeout_sec in bonbon_navigation (GAP-E1 fix,
# see docs/SAFETY_SEPARATION_AUDIT.md Finding 1).
_SAFETY_STALE_SEC = 2.0

# Mirrors bonbon_msgs/TTSRequest.msg's PRIORITY_HIGH = 10 -- a plain
# constant rather than importing the message class for its attribute, so
# this stays correct even where bonbon_msgs isn't a fully compiled ROS2
# package (matches bonbon_perception_ai's own PRIORITY_HIGH convention).
_TTS_PRIORITY_HIGH = 10


class LLMOrchestratorNode(LifecycleNode):
    """Full LLM + Response Generation pipeline as a ROS2 LifecycleNode."""

    _HEALTH_OK = 0
    _HEALTH_WARN = 1
    _HEALTH_ERROR = 2

    def __init__(self, node_name: str = "llm_orchestrator_node") -> None:
        super().__init__(node_name)

        # Pipeline components — wired in on_configure
        self._cfg = None
        self._ollama = None
        self._rag = None
        self._filter = None
        self._authorizer = None
        self._guard = None
        self._personality = None
        self._tool_reg = None
        self._logger_svc = None
        self._lc_chain = None  # LangChain chain (may be None if unavailable)
        self._response_cache = None  # ResponseCache; wired in _init_pipeline
        self._task_router = (
            None  # bonbon_edge_ai_runtime.TaskRouter; wired in _init_pipeline (GAP-E8 fix)
        )

        # Cached incoming state
        self._last_scene = None
        self._last_safety = None
        # Monotonic timestamp of the last /bonbon/safety/state message --
        # without this, a stale (but non-None) _last_safety would be
        # reused forever if the Safety Supervisor died or the network
        # partitioned, silently granting navigation/actuation on
        # outdated safety data (GAP-E1 fix, see
        # docs/SAFETY_SEPARATION_AUDIT.md Finding 1).
        self._last_safety_at: float = 0.0
        self._last_risks: list = []
        self._lock = threading.Lock()

        # Publishers / timers — wired in on_activate
        self._pub_response = None
        self._pub_tts = None
        self._pub_behavior = None
        self._pub_health = None
        self._health_timer = None

        self._pipeline_ok = False
        self._error_msg = ""
        self._start_time = time.monotonic()
        self._request_count = 0
        self._error_count = 0

        self.get_logger().info("LLMOrchestratorNode created")

    # ── Lifecycle: configure ──────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_configure")
        try:
            self._load_config()
            self._init_pipeline()
            self._create_interfaces()
            self._pipeline_ok = True
            self.get_logger().info(f"configured OK — {self._cfg.summary()}")
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f"configure failed: {exc}")
            self._error_msg = str(exc)
            if self._cfg and self._cfg.allow_degraded_startup:
                self.get_logger().warning("degraded startup allowed")
                self._pipeline_ok = True
                return TransitionCallbackReturn.SUCCESS
            return TransitionCallbackReturn.FAILURE

    def _load_config(self) -> None:
        from bonbon_llm.config.llm_config import LLMConfig

        self._cfg = LLMConfig.from_ros_params(self)
        self._cfg.validate()

    def _init_pipeline(self) -> None:
        from bonbon_llm.core.ollama_client import OllamaClient
        from bonbon_llm.core.rag_retriever import RAGRetriever
        from bonbon_llm.core.response_logger import ResponseLogger
        from bonbon_llm.personality.personality_layer import PersonalityLayer
        from bonbon_llm.safety.authorization import CommandAuthorizer
        from bonbon_llm.safety.command_filter import SafetyCommandFilter
        from bonbon_llm.safety.hallucination_guard import HallucinationGuard

        cfg = self._cfg

        self._ollama = OllamaClient(cfg.ollama)
        self._rag = RAGRetriever(cfg.rag)
        self._rag.load()

        self._filter = SafetyCommandFilter(cfg.safety_filter)
        self._authorizer = CommandAuthorizer(cfg.authorization)
        self._guard = HallucinationGuard(cfg.hallucination)
        self._personality = PersonalityLayer(cfg.personality)
        self._logger_svc = ResponseLogger()

        from bonbon_llm.core.response_cache import ResponseCache

        self._response_cache = ResponseCache()

        # GAP-E8 fix: pi_human_ai.yaml's resolution_order: [rule_engine,
        # rag, llm] was declared but read by zero live code -- an
        # utterance always went straight into the cache/RAG/LLM pipeline
        # below, even for phrases task_router.py's deterministic rule
        # engine (e.g. an emergency phrase) should short-circuit before
        # ever reaching the LLM. Wired here as the rule_engine stage;
        # degrades to None (pipeline behaves exactly as before this fix)
        # if bonbon_edge_ai_runtime isn't installed -- never blocks
        # startup over an optional routing enhancement.
        try:
            from bonbon_edge_ai_runtime.task_router import TaskRouter

            self._task_router = TaskRouter()
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- optional dependency, must never break the pipeline
            self.get_logger().warning(
                f"task_router unavailable ({exc}); rule-engine short-circuit disabled"
            )
            self._task_router = None

        # Wire tool registry
        from bonbon_llm.tools.tool_registry import ToolRegistry

        self._tool_reg = ToolRegistry(
            safety_filter=self._filter,
            rag_retriever=self._rag,
            scene_provider=self._get_scene_text,
            safety_provider=self._get_safety_snapshot,
            tts_dispatcher=self._dispatch_tts,
            behavior_dispatcher=self._dispatch_behavior,
        )

        # Try to build LangChain chain
        self._lc_chain = self._try_build_lc_chain()

        if not self._ollama.is_available():
            self.get_logger().warning(
                f"Ollama not reachable at {cfg.ollama.base_url} — will use fallback responses"
            )

    def _try_build_lc_chain(self):
        try:
            from bonbon_llm.core.langchain_bridge import build_rag_chain
            from bonbon_llm.prompts.system_prompt import SYSTEM_PROMPT, TOOL_INSTRUCTIONS

            chain = build_rag_chain(self._cfg, SYSTEM_PROMPT + "\n" + TOOL_INSTRUCTIONS)
            self.get_logger().info("LangChain RAG chain built OK")
            return chain
        except Exception as exc:
            self.get_logger().warning(f"LangChain unavailable ({exc}); using OllamaClient directly")
            return None

    def _create_interfaces(self) -> None:
        from bonbon_msgs.msg import (  # type: ignore
            BehaviorRecommendation,
            LLMLog,
            LLMResponse,
            ModuleHealth,
            RiskEvent,
            SemanticScene,
            SpeechCommand,
            TTSRequest,
            UserIntent,
        )
        from bonbon_msgs.msg import (
            SafetyState as SafetyStateMsg,
        )

        # Subscriptions
        self.create_subscription(UserIntent, "/perception/intent", self._on_intent, _RELIABLE)
        self.create_subscription(SemanticScene, "/perception/scene", self._on_scene, _BEST_EFFORT)
        self.create_subscription(
            SafetyStateMsg, "/bonbon/safety/state", self._on_safety, _TRANSIENT
        )
        self.create_subscription(RiskEvent, "/perception/risks", self._on_risk, _RELIABLE)
        self.create_subscription(SpeechCommand, "/speech/command", self._on_speech, _RELIABLE)

        # Publishers
        self._pub_response = self.create_lifecycle_publisher(
            LLMResponse, "/llm/response", _RELIABLE
        )
        self._pub_log = self.create_lifecycle_publisher(LLMLog, "/llm/log", _RELIABLE)
        self._pub_tts = self.create_lifecycle_publisher(
            TTSRequest, "/bonbon/tts/request", _RELIABLE
        )
        self._pub_behavior = self.create_lifecycle_publisher(
            BehaviorRecommendation, "/perception/behavior", _RELIABLE
        )
        self._pub_health = self.create_lifecycle_publisher(ModuleHealth, "/health/llm", _RELIABLE)

        self._logger_svc.set_ros_publisher(self._pub_log)

    # ── Lifecycle: activate / deactivate / cleanup ────────────────────────────

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_activate")
        hz = max(self._cfg.health_rate_hz, 0.1) if self._cfg else 1.0
        self._health_timer = self.create_timer(1.0 / hz, self._publish_health)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_deactivate")
        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
        with self._lock:
            self._last_scene = None
            self._last_safety = None
            self._last_safety_at = 0.0
            self._last_risks = []
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_cleanup")
        if self._rag:
            self._rag.close()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        if self._rag:
            self._rag.close()
        return TransitionCallbackReturn.SUCCESS

    # ── ROS2 subscription callbacks ───────────────────────────────────────────

    def _on_scene(self, msg) -> None:
        with self._lock:
            self._last_scene = msg

    def _on_safety(self, msg) -> None:
        with self._lock:
            self._last_safety = msg
            self._last_safety_at = time.monotonic()

    def _on_risk(self, msg) -> None:
        with self._lock:
            if len(self._last_risks) > 20:
                self._last_risks = self._last_risks[-20:]
            self._last_risks.append(msg)

    def _on_speech(self, msg) -> None:
        # Raw speech arrives here as a fallback trigger when no intent is classified.
        # Only act on it if confidence is high and it's not silence/timeout.
        if msg.is_silence or msg.is_timeout or msg.is_low_confidence:
            return
        # Speech is already routed via /perception/intent after classification;
        # this callback is a belt-and-suspenders fallback for direct queries.

    def _on_intent(self, msg) -> None:
        """Main entry point: UserIntent → full LLM pipeline."""
        if not self._pipeline_ok:
            return
        # Run in a thread so we don't block the ROS2 executor during Ollama call
        t = threading.Thread(target=self._process_intent, args=(msg,), daemon=True)
        t.start()

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def _process_intent(self, intent_msg) -> None:
        t_total = time.perf_counter()
        response_id = str(uuid.uuid4())

        try:
            self._request_count += 1

            # 1. Silence / timeout → brief idle response
            if intent_msg.is_ambiguous and not intent_msg.raw_text.strip():
                self._handle_silence(intent_msg, response_id)
                return

            # 1b. Genuinely-heard-but-unclassifiable speech. intent_engine's
            # "clarify" ambiguity_policy forces intent_class to "unknown" and
            # computes a per-intent fallback_response specifically so this
            # case can be spoken honestly -- without this branch, "unknown"
            # fell straight into the full RAG/LLM pipeline like any normal
            # query, risking a hallucinated answer to garbled/unintelligible
            # speech and never using the fallback_response the pipeline
            # already computed. Deliberately keyed on intent_class=="unknown"
            # rather than is_ambiguous alone: "best_guess" ambiguity_policy
            # sets is_ambiguous=True too but keeps a usable intent_class, and
            # that case must still proceed through the pipeline as designed.
            if intent_msg.is_ambiguous and intent_msg.intent_class == "unknown":
                self._handle_ambiguous(intent_msg, response_id)
                return

            # 2. Build context
            with self._lock:
                scene = self._last_scene
                list(self._last_risks)

            safety_snap = self._get_safety_snapshot()

            from bonbon_llm.prompts.system_prompt import build_context_string

            context_str = build_context_string(scene, safety_snap)
            prompt = self._build_prompt(intent_msg)

            # 2b. Rule-engine short-circuit (GAP-E8 fix) — task_router's
            # deterministic rule stage, tried BEFORE cache/RAG/LLM, matching
            # pi_human_ai.yaml's resolution_order: [rule_engine, rag, llm].
            # Only the emergency case is currently short-circuited here:
            # it is the one case with zero existing deterministic handling
            # anywhere in this pipeline (confirmed: no "emergency" branch
            # existed before this fix) and the one this brief's Phase 4
            # names explicitly ("no LLM involved"). Every other routing
            # outcome (navigation/appointment/FAQ/small-talk) falls through
            # to the existing, unchanged, already-tested pipeline below —
            # this fix intentionally does not change behavior for those.
            route_decision = self._route_text_intent(intent_msg)
            is_emergency_route = (
                route_decision is not None and route_decision.task_type == "emergency"
            )

            rag_results: list = []
            if is_emergency_route:
                final_text = self._fallback("emergency")
                status = "emergency"
                safety_status = "SAFE"
                safety_reason = ""
                raw_llm_out = None  # no LLM involved -- required for step 10's log call below
                rag_latency = 0.0
                llm_latency = 0.0
                # TTSRequest.PRIORITY_HIGH == 10 (bonbon_msgs/TTSRequest.msg)
                # -- a literal, not the message class attribute, matching
                # this repo's established convention (see
                # bonbon_perception_ai's own PRIORITY_HIGH module constant)
                # so this doesn't depend on a fully compiled bonbon_msgs.
                self._dispatch_tts(final_text, priority=_TTS_PRIORITY_HIGH)
                auth = self._authorizer.authorize(
                    "alert_safety", safety_snap, confidence=float(intent_msg.confidence)
                )
                if auth.granted:
                    self._dispatch_behavior(
                        "alert_safety",
                        {"reason": "emergency_phrase_detected"},
                        float(intent_msg.confidence),
                    )
            else:
                # 3. Cache check — BEFORE RAG retrieval, so a hit skips RAG AND the
                # LLM call, not just the LLM call. Keyed on (question, context_str)
                # — scene+safety only, not RAG results: within the cache's short
                # TTL (30s default) the local knowledge base is static enough that
                # re-retrieving identical RAG results for a repeated question is
                # pure waste. Any scene/safety change still correctly misses the
                # cache. The safety filter and hallucination guard below still run
                # on every cache hit too — a hit only ever skips RAG + inference.
                t_rag = time.perf_counter()
                t_llm = time.perf_counter()
                cached = (
                    self._response_cache.get(intent_msg.raw_text, context_str)
                    if self._response_cache
                    else None
                )
                if cached is not None:
                    raw_llm_out, llm_error = cached.text, None
                    full_context = context_str
                    rag_latency = 0.0
                else:
                    # 3a. RAG retrieval
                    if self._rag:
                        try:
                            rag_results = self._rag.retrieve_with_scores(intent_msg.raw_text)
                            rag_context = self._rag.build_context_string(rag_results)
                            full_context = context_str + "\n\n" + rag_context
                        except Exception as exc:
                            self.get_logger().debug(f"RAG error (non-fatal): {exc}")
                            full_context = context_str
                    else:
                        full_context = context_str
                    rag_latency = (time.perf_counter() - t_rag) * 1000.0

                    # 3b. LLM call
                    raw_llm_out, llm_error = self._call_llm(prompt, full_context)
                    if raw_llm_out and not llm_error and self._response_cache:
                        self._response_cache.put(
                            intent_msg.raw_text, context_str, raw_llm_out, "ok"
                        )
                llm_latency = (time.perf_counter() - t_llm) * 1000.0

                # 4. Safety filter
                filter_result = self._filter.filter_text(raw_llm_out) if raw_llm_out else None
                safety_status = "SAFE"
                safety_reason = ""

                if llm_error or not raw_llm_out:
                    final_text, status = self._fallback("llm_error"), "llm_error"
                    safety_status = "SAFE"
                elif filter_result and filter_result.status.value == "BLOCKED":
                    final_text = self._fallback("safety_block")
                    status = "safety_block"
                    safety_status = "BLOCKED"
                    safety_reason = filter_result.reason
                    self._error_count += 1
                    self.get_logger().warning(
                        f"LLM output blocked [{filter_result.reason}]: {raw_llm_out[:60]}"
                    )
                else:
                    sanitized = filter_result.sanitized_text if filter_result else raw_llm_out

                    # 5. Hallucination guard
                    guard_result = self._guard.check(
                        sanitized,
                        rag_results,
                        llm_confidence=float(intent_msg.confidence),
                    )
                    if not guard_result.is_grounded:
                        self.get_logger().warning(f"Hallucination flagged: {guard_result.reason}")
                        sanitized = guard_result.safe_response or self._fallback("hallucination")
                        status = "hallucination"
                    else:
                        status = "ok"

                    # 6. Personality layer
                    use_aff = intent_msg.intent_class in ("greeting", "order_item")
                    final_text = self._personality.apply(
                        sanitized, user_text=intent_msg.raw_text, use_affirmation=use_aff
                    )

                    # 7. Dispatch TTS
                    self._dispatch_tts(final_text, priority=5)

                    # 8. Behavior dispatch (from tool calls or intent mapping)
                    behavior_class = self._resolve_behavior(intent_msg, safety_snap)
                    if behavior_class:
                        auth = self._authorizer.authorize(
                            behavior_class,
                            safety_snap,
                            confidence=float(intent_msg.confidence),
                        )
                        if auth.granted:
                            slots = dict(zip(intent_msg.slot_names, intent_msg.slot_values))
                            self._dispatch_behavior(
                                behavior_class, slots, float(intent_msg.confidence)
                            )
                        else:
                            self.get_logger().info(
                                f"Behavior {behavior_class!r} {auth.status.value}: {auth.reason}"
                            )
                            if auth.status.value == "DENIED":
                                denial_text = self._fallback(
                                    "navigation_denied"
                                    if "navigat" in behavior_class
                                    else "actuation_denied"
                                )
                                self._dispatch_tts(denial_text, priority=5)

            # 9. Publish LLMResponse
            self._publish_response(
                response_id=response_id,
                intent_msg=intent_msg,
                text=final_text,
                status=status,
                rag_results=rag_results,
                tools_called=(
                    [r.tool_name for r in self._tool_reg.recent_calls(5)] if self._tool_reg else []
                ),
                behavior_class=self._resolve_behavior(intent_msg, safety_snap) or "",
            )

            # 10. Log
            total_latency = (time.perf_counter() - t_total) * 1000.0
            self._logger_svc.record(
                response_id=response_id,
                intent_id=intent_msg.intent_id,
                speaker_id=intent_msg.speaker_id,
                raw_prompt=prompt,
                raw_llm_output=raw_llm_out or "",
                final_response=final_text,
                safety_filter_result=safety_status,
                safety_filter_reason=safety_reason,
                hallucination_flagged=(status == "hallucination"),
                hallucination_reason=(guard_result.reason if status == "hallucination" else ""),
                llm_latency_ms=llm_latency,
                rag_latency_ms=rag_latency,
                total_latency_ms=total_latency,
                rag_doc_ids=[r.document.doc_id for r in rag_results],
                rag_scores=[r.score for r in rag_results],
                safety_state=safety_snap.state_id,
                actuation_permitted=safety_snap.actuation_permitted,
                navigation_permitted=safety_snap.navigation_permitted,
            )

        except Exception as exc:
            self.get_logger().error(f"Pipeline error: {exc}")
            self._error_count += 1
            try:
                fallback = self._fallback("llm_error")
                self._dispatch_tts(fallback, priority=5)
            except Exception:
                pass

    # ── LLM call ──────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, context: str):
        """Returns (raw_text, error_str).  error_str is None on success."""
        # Try LangChain chain first
        if self._lc_chain is not None:
            try:
                from bonbon_llm.core.langchain_bridge import invoke_chain

                text = invoke_chain(self._lc_chain, prompt, context)
                return text, None
            except Exception as exc:
                self.get_logger().debug(f"LangChain failed, falling back to OllamaClient: {exc}")

        # Direct Ollama client fallback
        if self._ollama:
            from bonbon_llm.prompts.system_prompt import SYSTEM_PROMPT

            resp = self._ollama.generate(prompt, system=SYSTEM_PROMPT + "\n\n" + context)
            if resp.is_error:
                return None, resp.error
            return resp.text, None

        return None, "No LLM backend available"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_prompt(self, intent_msg) -> str:
        """Construct the user-facing prompt from the UserIntent."""
        text = intent_msg.raw_text.strip()
        if not text:
            return f"[{intent_msg.intent_class}]"
        if intent_msg.slot_names:
            slots = ", ".join(
                f"{n}={v}" for n, v in zip(intent_msg.slot_names, intent_msg.slot_values)
            )
            return f"{text}  [intent={intent_msg.intent_class}, slots: {slots}]"
        return text

    def _resolve_behavior(self, intent_msg, safety_snap) -> str | None:
        """Map intent_class → behavior_class (None = speech-only)."""
        _MAP = {
            "order_item": "serve_item",
            "navigate_to": "navigate_to_goal",
            "cancel": "stop_navigation",
            "help_request": "alert_safety",
        }
        return _MAP.get(intent_msg.intent_class)

    def _route_text_intent(self, intent_msg):
        """GAP-E8 fix: consult TaskRouter's rule-engine stage before the
        cache/RAG/LLM pipeline runs. Never lets a routing-layer failure
        block the pipeline -- returns None on any error or when
        task_router is unavailable, in which case callers must fall
        through to the pipeline exactly as before this fix."""
        if self._task_router is None:
            return None
        try:
            return self._task_router.route_text_intent(
                intent_msg.raw_text,
                intent_class=intent_msg.intent_class or None,
                source_module="llm_orchestrator",
            )
        except Exception as exc:  # noqa: BLE001 -- routing must degrade, never crash the pipeline
            self.get_logger().debug(f"task_router routing error (non-fatal): {exc}")
            return None

    def _fallback(self, situation: str) -> str:
        from bonbon_llm.prompts.response_templates import get_fallback

        name = self._cfg.personality.name if self._cfg else "BonBon"
        return get_fallback(situation, prefer_short=True, name=name)

    def _handle_silence(self, intent_msg, response_id: str) -> None:
        text = self._fallback("silent")
        self._dispatch_tts(text, priority=1)

    def _handle_ambiguous(self, intent_msg, response_id: str) -> None:
        text = intent_msg.fallback_response or self._fallback("low_confidence")
        self._dispatch_tts(text, priority=1)

    def _get_scene_text(self) -> str:
        with self._lock:
            scene = self._last_scene
        if scene is None:
            return "No scene data available"
        from bonbon_llm.prompts.system_prompt import build_context_string

        return build_context_string(scene, None)

    def _get_safety_snapshot(self):
        from bonbon_llm.safety.authorization import SafetySnapshot

        with self._lock:
            msg = self._last_safety
            age_sec = time.monotonic() - self._last_safety_at
        if msg is None or age_sec > _SAFETY_STALE_SEC:
            # No SafetyState received yet, or the Safety Supervisor has
            # gone quiet (crashed, network partition) -- never authorize
            # navigation/actuation against a stale or absent heartbeat.
            return SafetySnapshot.safe_default()
        return SafetySnapshot.from_ros_msg(msg)

    # ── Dispatch helpers ──────────────────────────────────────────────────────

    def _dispatch_tts(self, text: str, priority: int = 5) -> None:
        if not self._pub_tts or not text:
            return
        try:
            from bonbon_msgs.msg import TTSRequest  # type: ignore

            msg = TTSRequest()
            msg.text = text
            msg.priority = priority
            msg.language = "en-US"
            msg.request_id = str(uuid.uuid4())
            msg.speed_factor = 1.0
            self._pub_tts.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"TTS dispatch error: {exc}")

    def _dispatch_behavior(
        self,
        behavior_class: str,
        params: dict[str, str],
        confidence: float,
    ) -> None:
        if not self._pub_behavior:
            return
        try:
            from bonbon_msgs.msg import BehaviorRecommendation  # type: ignore

            msg = BehaviorRecommendation()
            msg.recommendation_id = str(uuid.uuid4())
            msg.behavior_class = behavior_class
            msg.confidence = float(confidence)
            msg.priority = 1  # PRIORITY_NORMAL
            msg.trigger_type = "user_intent"
            msg.trigger_id = str(uuid.uuid4())
            msg.param_names = list(params.keys())
            msg.param_values = list(params.values())
            msg.timeout_sec = 30.0
            self._pub_behavior.publish(msg)
            self.get_logger().debug(f"Dispatched behavior: {behavior_class} {params}")
        except Exception as exc:
            self.get_logger().debug(f"Behavior dispatch error: {exc}")

    # ── Publisher helpers ─────────────────────────────────────────────────────

    def _publish_response(
        self,
        response_id: str,
        intent_msg,
        text: str,
        status: str,
        rag_results: list,
        tools_called: list[str],
        behavior_class: str,
    ) -> None:
        if not self._pub_response:
            return
        try:
            from bonbon_msgs.msg import LLMResponse  # type: ignore

            _STATUS_MAP = {
                "ok": 0,
                "low_conf": 1,
                "safety_block": 2,
                "hallucination": 3,
                "llm_error": 4,
                "fallback": 5,
            }
            msg = LLMResponse()
            msg.response_id = response_id
            msg.request_intent_id = intent_msg.intent_id
            msg.text = text
            msg.status = _STATUS_MAP.get(status, 0)
            msg.confidence = float(intent_msg.confidence)
            msg.model_name = self._cfg.ollama.model if self._cfg else ""
            msg.used_rag = len(rag_results) > 0
            msg.rag_docs_retrieved = len(rag_results)
            msg.used_tools = len(tools_called) > 0
            msg.tools_called = tools_called
            msg.behavior_class = behavior_class
            msg.tts_dispatched = True
            self._pub_response.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"Response publish error: {exc}")

    def _publish_health(self) -> None:
        if not self._pub_health:
            return
        try:
            from bonbon_msgs.msg import ModuleHealth  # type: ignore

            uptime = time.monotonic() - self._start_time
            msg = ModuleHealth()
            msg.module_name = "bonbon_llm.llm_orchestrator_node"
            msg.status = self._HEALTH_OK if self._pipeline_ok else self._HEALTH_ERROR
            msg.status_text = self._cfg.summary() if self._pipeline_ok else self._error_msg
            msg.uptime_sec = float(uptime)
            msg.processed_count = self._request_count
            msg.error_count = self._error_count
            msg.latency_ms = 0.0
            self._pub_health.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"Health publish error: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LLMOrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
