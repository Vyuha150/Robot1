"""bonbon_distributed_network_monitor.core.quality_evaluator -- combines a
ProbeResult for one peer with NetworkQualityThresholds into a metrics
snapshot plus any triggered TelemetryTrigger. Mirrors offset_evaluator.py's
shape exactly (pure function, metrics dataclass + trigger list, no rclpy).

Two-tier severity, same convention as offset_evaluator.py: *_warn is the
"designed-for" ceiling, *_alert is the harder breach worth an ERROR-level
HalFault. RTT and packet loss are evaluated independently -- a link can
legitimately be lossy-but-fast (WARN on loss only) or slow-but-reliable
(WARN on RTT only), and conflating them into one score would hide which
dimension actually degraded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .network_thresholds import NetworkQualityThresholds
from .rtt_probe import ProbeResult
from .trigger import Severity, TelemetryTrigger

_DEVICE = "network_quality"


@dataclass(frozen=True)
class QualityMetrics:
    pi_role: str
    peer_role: str
    peer_host: str
    reachable: bool
    avg_rtt_ms: float | None
    max_rtt_ms: float | None
    packet_loss_pct: float
    rtt_warn_exceeded: bool
    rtt_alert_exceeded: bool
    loss_warn_exceeded: bool
    loss_alert_exceeded: bool


def compute_quality_metrics(
    pi_role: str, peer_role: str, result: ProbeResult, thresholds: NetworkQualityThresholds
) -> QualityMetrics:
    avg_rtt = result.avg_rtt_ms
    reachable = result.successes > 0
    return QualityMetrics(
        pi_role=pi_role,
        peer_role=peer_role,
        peer_host=result.host,
        reachable=reachable,
        avg_rtt_ms=avg_rtt,
        max_rtt_ms=result.max_rtt_ms,
        packet_loss_pct=result.packet_loss_pct,
        rtt_warn_exceeded=avg_rtt is not None and avg_rtt > thresholds.rtt_warn_ms,
        rtt_alert_exceeded=avg_rtt is not None and avg_rtt > thresholds.rtt_alert_ms,
        loss_warn_exceeded=result.packet_loss_pct > thresholds.packet_loss_warn_pct,
        loss_alert_exceeded=result.packet_loss_pct > thresholds.packet_loss_alert_pct,
    )


def quality_triggers(metrics: QualityMetrics) -> list[TelemetryTrigger]:
    triggers: list[TelemetryTrigger] = []
    device = f"{_DEVICE}_{metrics.peer_role}"

    if not metrics.reachable:
        return [
            TelemetryTrigger(
                device=device,
                severity=Severity.ERROR,
                code="PEER_UNREACHABLE",
                message=(
                    f"{metrics.pi_role}: {metrics.peer_role} ({metrics.peer_host}) "
                    "unreachable on every probe attempt"
                ),
            )
        ]

    if metrics.loss_alert_exceeded:
        triggers.append(
            TelemetryTrigger(
                device=device,
                severity=Severity.ERROR,
                code="PACKET_LOSS_ALERT",
                message=(
                    f"{metrics.pi_role}: link to {metrics.peer_role} "
                    f"{metrics.packet_loss_pct:.0f}% loss exceeds alert threshold"
                ),
            )
        )
    elif metrics.loss_warn_exceeded:
        triggers.append(
            TelemetryTrigger(
                device=device,
                severity=Severity.WARN,
                code="PACKET_LOSS_ELEVATED",
                message=(
                    f"{metrics.pi_role}: link to {metrics.peer_role} "
                    f"{metrics.packet_loss_pct:.0f}% loss exceeds designed-for threshold"
                ),
            )
        )

    if metrics.rtt_alert_exceeded:
        triggers.append(
            TelemetryTrigger(
                device=device,
                severity=Severity.ERROR,
                code="RTT_ALERT",
                message=(
                    f"{metrics.pi_role}: link to {metrics.peer_role} "
                    f"avg RTT {metrics.avg_rtt_ms:.1f}ms exceeds alert threshold"
                ),
            )
        )
    elif metrics.rtt_warn_exceeded:
        triggers.append(
            TelemetryTrigger(
                device=device,
                severity=Severity.WARN,
                code="RTT_ELEVATED",
                message=(
                    f"{metrics.pi_role}: link to {metrics.peer_role} "
                    f"avg RTT {metrics.avg_rtt_ms:.1f}ms exceeds designed-for threshold"
                ),
            )
        )

    return triggers
