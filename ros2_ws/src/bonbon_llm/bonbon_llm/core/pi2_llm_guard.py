"""Pi2LLMGuard — enforces the Pi-2 hardware constraints for the local
Qwen2.5 0.5B deployment (see config/distributed/pi_human_ai.yaml's `llm:`
section and docs/PI2_QWEN25_05B_DOWNLOAD_REPORT.md).

Exact rules from the three-Pi brief:
  - max 1 concurrent request
  - max 64 tokens of output
  - 1.0s initial timeout (first-token latency budget, not total generation time)
  - disabled during high CPU/temp/safety fault
  - resolution order is rule-engine -> RAG -> LLM (LLM is last resort)

Pure Python, no rclpy dependency -- fully unit-testable. The node wrapper
(llm_orchestrator_node.py) owns the actual CPU/temp/safety-state sampling
and calls should_disable() with the latest values before invoking Ollama.

Disabled by default (Pi2LLMGuardConfig.enabled = False): this package
serves both the monolithic/single-machine deployment (config/
pi_efficiency_profile.yaml already governs load-shedding there) and the
Pi-2-scoped three-Pi deployment. Enabling this guard is a Pi-2 runtime
profile decision, not a change to the package's own default behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_llm.config.llm_config import Pi2LLMGuardConfig

__all__ = ["Pi2LLMGuardConfig", "DisableDecision", "Pi2LLMGuard"]


@dataclass(frozen=True)
class DisableDecision:
    disabled: bool
    reason: str


class Pi2LLMGuard:
    def __init__(self, config: Pi2LLMGuardConfig | None = None) -> None:
        self._cfg = config or Pi2LLMGuardConfig()
        self._cfg.validate()
        self._in_flight = 0

    @property
    def config(self) -> Pi2LLMGuardConfig:
        return self._cfg

    # ── Concurrency gate ─────────────────────────────────────────────────────

    def try_acquire(self) -> bool:
        """Returns True and reserves a slot if under the concurrency limit;
        False (reserving nothing) if at capacity. Caller MUST call release()
        exactly once for every successful try_acquire()."""
        if not self._cfg.enabled:
            return True
        if self._in_flight >= self._cfg.max_concurrent_requests:
            return False
        self._in_flight += 1
        return True

    def release(self) -> None:
        if self._in_flight > 0:
            self._in_flight -= 1

    @property
    def in_flight(self) -> int:
        return self._in_flight

    # ── Output clamping ──────────────────────────────────────────────────────

    def clamp_max_tokens(self, requested: int) -> int:
        if not self._cfg.enabled:
            return requested
        return min(requested, self._cfg.max_output_tokens)

    # ── Load-based disable ───────────────────────────────────────────────────

    def should_disable(
        self, cpu_percent: float, temp_c: float, safety_state_name: str
    ) -> DisableDecision:
        if not self._cfg.enabled:
            return DisableDecision(disabled=False, reason="guard disabled")
        if safety_state_name in self._cfg.disable_safety_states:
            return DisableDecision(
                disabled=True, reason=f"safety state {safety_state_name} disables LLM"
            )
        if cpu_percent >= self._cfg.cpu_disable_threshold_percent:
            return DisableDecision(
                disabled=True,
                reason=f"CPU {cpu_percent:.0f}% >= threshold {self._cfg.cpu_disable_threshold_percent:.0f}%",
            )
        if temp_c >= self._cfg.temp_disable_threshold_c:
            return DisableDecision(
                disabled=True,
                reason=f"temp {temp_c:.0f}C >= threshold {self._cfg.temp_disable_threshold_c:.0f}C",
            )
        return DisableDecision(disabled=False, reason="within limits")
