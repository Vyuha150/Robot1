"""PerceptionEfficiencyNode — central perception coordination LifecycleNode.

This node does not detect anything. It observes existing perception
modules' own outputs and publishes ADVISORY policy/budget recommendations —
it never commands another node, never bypasses the Safety Supervisor, never
touches actuation/navigation.

Consumes (does not redetect/re-sample anything):
    /bonbon/system/resource_usage     (bonbon_msgs/ResourceUsage)   — bonbon_safety
    /bonbon/safety/state               (bonbon_msgs/SafetyState)     — bonbon_safety
    /bonbon/temperature/readings        (bonbon_msgs/ThermalReadings) — bonbon_hal
    /bonbon/persons/tracks              (bonbon_msgs/PersonTrack)     — bonbon_multi_person_tracker
    /bonbon/human/state                 (bonbon_msgs/HumanState)      — bonbon_human_state_fusion
    /bonbon/vision/vision_node/health   (bonbon_msgs/ModuleHealth)
    /bonbon/persons/multi_person_tracker_node/health
    /bonbon/objects/object_intelligence_node/health
    /bonbon/speaker/speaker_intelligence_node/health
    /bonbon/human/human_state_fusion_node/health
    /health/speech                      (bonbon_msgs/ModuleHealth)    — bonbon_speech

Thermal: reuses bonbon_hal's existing ThermalReadings publication rather
than sampling temperature a second time. The 75C threshold mirrors
bonbon_safety's SafetyStateMachine cpu_temp_caution_c default exactly, so
load shedding acts preventively, strictly before the Safety Supervisor's
own cpu_temp_fault_c (90C) threshold would force a SAFE_STOP.

Publishes:
    /bonbon/perception_efficiency/policy          (bonbon_msgs/PerceptionPolicy)
    /bonbon/perception_efficiency/budget          (bonbon_msgs/PerceptionBudget)
    /bonbon/perception_efficiency/degraded_mode   (bonbon_msgs/DegradedModeStatus)
    /bonbon/perception_efficiency/metrics         (bonbon_msgs/PerceptionEfficiencyMetrics)
    /bonbon/diagnostics/events                    (std_msgs/String, JSON)

Active-person focus reuses bonbon_behavior_engine's existing
select_focus_person() (same priority rule: speaking > active_interaction >
highest urgency > most recent) rather than re-deriving who the focus person
is a second time.
"""

from __future__ import annotations

import json
import time

import rclpy
from bonbon_behavior_engine.core.multi_person_behavior_selector import select_focus_person
from bonbon_msgs.msg import (
    DegradedModeStatus,
    HumanState,
    ModuleHealth,
    PerceptionEfficiencyMetrics,
    PerceptionPolicy,
    PersonTrack,
    ResourceUsage,
    SafetyState,
    ThermalReadings,
)
from bonbon_msgs.msg import (
    PerceptionBudget as PerceptionBudgetMsg,
)
from bonbon_srvs.srv import HealthCheck
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header, String

from bonbon_perception_efficiency.core.perception_budget_manager import (
    BudgetInputs,
    PerceptionBudgetManager,
)
from bonbon_perception_efficiency.core.perception_metrics_aggregator import (
    ModuleMetricSample,
    PerceptionMetricsAggregator,
)

_SOURCE_MODULE = "bonbon_perception_efficiency"
_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3

_SAFETY_CAUTION = 2  # SafetyState.CAUTION
_SAFETY_FAULT = 6  # SafetyState.FAULT

# Mirrors bonbon_safety's SafetyStateMachine cpu_temp_caution_c default
# exactly (ros2_ws/src/bonbon_safety/bonbon_safety/core/safety_state_machine.py)
# so this acts strictly before the Safety Supervisor's own cpu_temp_fault_c
# (90C) threshold would force a SAFE_STOP.
_CPU_TEMP_CAUTION_C = 75.0

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)

_HEALTH_TOPICS = {
    "vision": "/bonbon/vision/vision_node/health",
    "multi_person_tracker": "/bonbon/persons/multi_person_tracker_node/health",
    "object_intelligence": "/bonbon/objects/object_intelligence_node/health",
    "speaker_intelligence": "/bonbon/speaker/speaker_intelligence_node/health",
    "human_state_fusion": "/bonbon/human/human_state_fusion_node/health",
    "speech": "/health/speech",
}


def _now_header(node: LifecycleNode, frame_id: str = "map") -> Header:
    h = Header()
    h.stamp = node.get_clock().now().to_msg()
    h.frame_id = frame_id
    return h


class PerceptionEfficiencyNode(LifecycleNode):
    def __init__(self, node_name: str = "perception_efficiency_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("publish_rate_hz", 2.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("hysteresis_cycles", 3)
        self.declare_parameter("degraded_sustained_threshold_sec", 10.0)
        self.declare_parameter("cpu_temp_caution_c", _CPU_TEMP_CAUTION_C)

        self._budget_manager: PerceptionBudgetManager | None = None
        self._metrics = PerceptionMetricsAggregator()

        self._latest_resource: ResourceUsage | None = None
        self._latest_thermal: ThermalReadings | None = None
        self._safety_level: int = 0
        self._human_states: dict[str, HumanState] = {}
        self._new_candidate_ids: set[str] = set()
        self._person_track_ids: list[str] = []

        self._subs: list = []
        self._pub_policy: LifecyclePublisher | None = None
        self._pub_budget: LifecyclePublisher | None = None
        self._pub_degraded: LifecyclePublisher | None = None
        self._pub_metrics: LifecyclePublisher | None = None
        self._pub_diag: LifecyclePublisher | None = None
        self._pub_health: LifecyclePublisher | None = None
        self._srv_health = None
        self._timer = None
        self._health_timer = None

        self._node_start = time.monotonic()
        self._cycle_count = 0
        self._error_count = 0
        self._last_cycle_t = 0.0
        self._last_degraded_state = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("PerceptionEfficiencyNode: configuring …")
        try:
            from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
            from bonbon_perception_efficiency.core.load_shedding_controller import (
                LoadSheddingController,
            )

            hysteresis = int(
                self.get_parameter("hysteresis_cycles").get_parameter_value().integer_value
            )
            sustained = float(
                self.get_parameter("degraded_sustained_threshold_sec")
                .get_parameter_value()
                .double_value
            )
            self._budget_manager = PerceptionBudgetManager(
                load_shedding=LoadSheddingController(hysteresis_cycles=hysteresis),
                degraded_mode=DegradedModeManager(sustained_threshold_sec=sustained),
            )
            self.get_logger().info("PerceptionEfficiencyNode: configured")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("PerceptionEfficiencyNode: activating …")
        try:
            rate_hz = self.get_parameter("publish_rate_hz").get_parameter_value().double_value
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value

            def sub(msg_type, topic, cb):
                s = self.create_subscription(msg_type, topic, cb, _QOS_RELIABLE)
                self._subs.append(s)

            sub(ResourceUsage, "/bonbon/system/resource_usage", self._cb_resource_usage)
            sub(ThermalReadings, "/bonbon/temperature/readings", self._cb_thermal_readings)
            sub(SafetyState, "/bonbon/safety/state", self._cb_safety_state)
            sub(PersonTrack, "/bonbon/persons/tracks", self._cb_person_track)
            sub(HumanState, "/bonbon/human/state", self._cb_human_state)
            for topic in _HEALTH_TOPICS.values():
                sub(ModuleHealth, topic, self._cb_module_health)

            self._pub_policy = self.create_lifecycle_publisher(
                PerceptionPolicy,
                "/bonbon/perception_efficiency/policy",
                _QOS_RELIABLE,
            )
            self._pub_budget = self.create_lifecycle_publisher(
                PerceptionBudgetMsg,
                "/bonbon/perception_efficiency/budget",
                _QOS_RELIABLE,
            )
            self._pub_degraded = self.create_lifecycle_publisher(
                DegradedModeStatus,
                "/bonbon/perception_efficiency/degraded_mode",
                _QOS_TRANSIENT,
            )
            self._pub_metrics = self.create_lifecycle_publisher(
                PerceptionEfficiencyMetrics,
                "/bonbon/perception_efficiency/metrics",
                _QOS_RELIABLE,
            )
            self._pub_diag = self.create_lifecycle_publisher(
                String,
                "/bonbon/diagnostics/events",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/perception_efficiency/perception_efficiency_node/health",
                _QOS_RELIABLE,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )

            self._timer = self.create_timer(1.0 / max(rate_hz, 0.1), self._cb_publish_timer)
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("PerceptionEfficiencyNode: active")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_activate failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("PerceptionEfficiencyNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("PerceptionEfficiencyNode: cleaning up …")
        self._budget_manager = None
        self._human_states.clear()
        self._new_candidate_ids.clear()
        self._person_track_ids.clear()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("PerceptionEfficiencyNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_resource_usage(self, msg: ResourceUsage) -> None:
        self._latest_resource = msg

    def _cb_thermal_readings(self, msg: ThermalReadings) -> None:
        self._latest_thermal = msg

    def _cb_safety_state(self, msg: SafetyState) -> None:
        self._safety_level = msg.state

    def _cb_person_track(self, msg: PersonTrack) -> None:
        if msg.lifecycle_state == "left_scene":
            self._new_candidate_ids.discard(msg.person_track_id)
            if msg.person_track_id in self._person_track_ids:
                self._person_track_ids.remove(msg.person_track_id)
            self._human_states.pop(msg.person_track_id, None)
            return
        if msg.person_track_id not in self._person_track_ids:
            self._person_track_ids.append(msg.person_track_id)
        if msg.lifecycle_state == "new_candidate":
            self._new_candidate_ids.add(msg.person_track_id)
        else:
            self._new_candidate_ids.discard(msg.person_track_id)

    def _cb_human_state(self, msg: HumanState) -> None:
        self._human_states[msg.person_track_id] = msg

    def _cb_module_health(self, msg: ModuleHealth) -> None:
        self._metrics.record(
            ModuleMetricSample(
                module_name=msg.module_name,
                status=msg.status,
                latency_ms=msg.latency_ms,
                error_count=msg.error_count,
                processed_count=msg.processed_count,
            )
        )

    # ── Publish cycle ────────────────────────────────────────────────────────

    def _cb_publish_timer(self) -> None:
        if self._budget_manager is None:
            return
        try:
            self._run_cycle()
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error(f"Perception efficiency cycle failed: {exc}")

    def _run_cycle(self) -> None:
        res = self._latest_resource
        thermal = self._latest_thermal
        temp_caution_c = self.get_parameter("cpu_temp_caution_c").get_parameter_value().double_value
        inputs = BudgetInputs(
            cpu_overloaded=bool(res.cpu_overloaded) if res else False,
            memory_pressure=bool(res.memory_pressure) if res else False,
            resource_unavailable=(res is None) or (not res.available),
            safety_caution_or_above=self._safety_level >= _SAFETY_CAUTION,
            safety_fault_or_above=self._safety_level >= _SAFETY_FAULT,
            thermal_overloaded=(thermal is not None) and (thermal.cpu_temp_c >= temp_caution_c),
            focus_person_track_id=self._compute_focus_person(),
            person_track_ids=list(self._person_track_ids),
            new_candidate_ids=set(self._new_candidate_ids),
        )
        budget = self._budget_manager.update(inputs)

        stamp = self.get_clock().now().to_msg()
        self._publish_policy(budget, stamp)
        self._publish_budget(budget, stamp)
        self._publish_degraded(budget, stamp)
        self._publish_metrics(budget, stamp)

        if budget.degraded.is_degraded != self._last_degraded_state:
            self._publish_diag(
                "degraded_mode_changed",
                {"is_degraded": budget.degraded.is_degraded, "reason": budget.degraded.reason},
            )
            self._last_degraded_state = budget.degraded.is_degraded

    def _compute_focus_person(self) -> str:
        states = list(self._human_states.values())
        if not states:
            return ""
        return select_focus_person(states)

    # ── Message construction ─────────────────────────────────────────────────

    def _publish_policy(self, budget, stamp) -> None:
        if self._pub_policy is None or not self._pub_policy.is_activated:
            return
        msg = PerceptionPolicy()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.signal_names = [p.signal for p in budget.confidence_policy]
        msg.recommended_thresholds = [
            float(p.recommended_threshold) for p in budget.confidence_policy
        ]
        msg.reasons = [p.reason for p in budget.confidence_policy]
        msg.degraded_mode_active = budget.degraded.is_degraded
        msg.safety_elevated = self._safety_level >= _SAFETY_CAUTION
        self._pub_policy.publish(msg)

    def _publish_budget(self, budget, stamp) -> None:
        if self._pub_budget is None or not self._pub_budget.is_activated:
            return
        msg = PerceptionBudgetMsg()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.load_level = budget.load.level.value
        msg.load_scale = float(budget.load.scale)
        msg.load_reason = budget.load.reason
        msg.sample_consumers = [r.consumer for r in budget.sample_rates]
        msg.sample_every_n_frames = [int(r.sample_every_n_frames) for r in budget.sample_rates]
        msg.sample_reasons = [r.reason for r in budget.sample_rates]
        msg.focus_person_track_ids = [w.person_track_id for w in budget.person_focus]
        msg.focus_weights = [float(w.weight) for w in budget.person_focus]
        msg.focus_reasons = [w.reason for w in budget.person_focus]
        msg.current_focus_person_track_id = self._compute_focus_person()
        self._pub_budget.publish(msg)

    def _publish_degraded(self, budget, stamp) -> None:
        if self._pub_degraded is None or not self._pub_degraded.is_activated:
            return
        msg = DegradedModeStatus()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.is_degraded = budget.degraded.is_degraded
        msg.reason = budget.degraded.reason
        msg.duration_sec = float(budget.degraded.duration_sec)
        self._pub_degraded.publish(msg)

    def _publish_metrics(self, budget, stamp) -> None:
        if self._pub_metrics is None or not self._pub_metrics.is_activated:
            return
        snap = self._metrics.snapshot()
        res = self._latest_resource

        msg = PerceptionEfficiencyMetrics()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.module_count = snap.module_count
        msg.worst_status = snap.worst_status
        msg.worst_status_module = snap.worst_status_module
        msg.avg_latency_ms = float(snap.avg_latency_ms)
        msg.max_latency_ms = float(snap.max_latency_ms)
        msg.total_errors = snap.total_errors
        msg.total_processed = snap.total_processed
        msg.cpu_percent = float(res.cpu_percent) if res else 0.0
        msg.memory_percent = float(res.memory_percent) if res else 0.0
        msg.recommended_load_shed = float(budget.load.scale)
        msg.load_level = budget.load.level.value
        msg.degraded_mode_active = budget.degraded.is_degraded
        self._pub_metrics.publish(msg)

    def _publish_diag(self, event: str, data: dict) -> None:
        if self._pub_diag is None or not self._pub_diag.is_activated:
            return
        payload = {"event": event, "source": _SOURCE_MODULE, **data}
        self._pub_diag.publish(String(data=json.dumps(payload)))

    # ── Health ───────────────────────────────────────────────────────────────

    def _health_status(self) -> tuple:
        now = time.monotonic()
        if self._last_cycle_t and (now - self._last_cycle_t) > 5.0:
            return _HEALTH_STALE, "publish cycle stalled"
        if self._error_count > 0 and self._cycle_count == 0:
            return _HEALTH_ERROR, "all cycles failing"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} cycle error(s)"
        if self._budget_manager is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_perception_efficiency.perception_efficiency_node"
        msg.status = status
        msg.status_text = text
        msg.uptime_sec = float(time.monotonic() - self._node_start)
        msg.last_successful_cycle_sec = float(
            (time.monotonic() - self._last_cycle_t) if self._last_cycle_t else -1.0
        )
        msg.cpu_percent = 0.0
        msg.memory_mb = 0.0
        msg.latency_ms = 0.0
        msg.error_count = int(self._error_count)
        msg.warning_count = 0
        msg.processed_count = int(self._cycle_count)
        self._pub_health.publish(msg)

    def _handle_health_check(self, request, response):
        status, text = self._health_status()
        response.healthy = status in (_HEALTH_OK, _HEALTH_WARN)
        response.status = text
        response.warnings = [text] if status == _HEALTH_WARN else []
        response.errors = [text] if status in (_HEALTH_ERROR, _HEALTH_STALE) else []
        response.uptime_sec = float(time.monotonic() - self._node_start)
        return response

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _destroy_active_resources(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None
        for sub in self._subs:
            try:
                self.destroy_subscription(sub)
            except Exception:  # noqa: BLE001
                pass
        self._subs.clear()
        for attr in (
            "_pub_policy",
            "_pub_budget",
            "_pub_degraded",
            "_pub_metrics",
            "_pub_diag",
            "_pub_health",
            "_srv_health",
        ):
            resource = getattr(self, attr, None)
            if resource is not None:
                for destroy in (self.destroy_publisher, self.destroy_service):
                    try:
                        destroy(resource)  # type: ignore[arg-type]
                        break
                    except Exception:  # noqa: BLE001
                        continue
                setattr(self, attr, None)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PerceptionEfficiencyNode("perception_efficiency_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
