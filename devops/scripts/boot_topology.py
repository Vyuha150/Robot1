"""Boot-topology classifier — the single source of truth for which systemd
deployment mode BonBon is in, and whether that mode is valid.

Pure Python, zero dependencies, no systemd/ROS2 calls of its own — it takes
the set of enabled unit names (and optionally a live safety-node count) and
classifies. This keeps it directly unit-testable without a Pi, and lets both
the CLI (scripts/validate_boot_topology.py, which queries real systemctl)
and the dashboard read the same logic / its written result.

The defect this guards against: enabling bonbon-core (which runs the FULL
bringup.launch.py, including a safety supervisor) at the same time as the
standalone bonbon-safety (and other per-subsystem) services starts TWO
safety_supervisor_node processes — two publishers on the transient-local
/bonbon/safety/state, i.e. nondeterministic safety state. See
docs/DUPLICATE_PIPELINE_RISK_REPORT.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# The monolithic service: runs the entire stack via bringup.launch.py,
# including its own safety supervisor.
MONOLITHIC_UNIT = "bonbon-core"

# The standalone safety supervisor service (modular mode).
SAFETY_UNIT = "bonbon-safety"

# Per-subsystem services that DUPLICATE something already inside bonbon-core.
# Enabling any of these alongside bonbon-core is the duplicate-topology bug.
MODULAR_SUBSYSTEM_UNITS = frozenset(
    {
        "bonbon-safety",
        "bonbon-hal",
        "bonbon-perception",
        "bonbon-speech",
        "bonbon-behavior",
        "bonbon-navigation",
        "bonbon-actuation",
        "bonbon-tts",
    }
)

# Services that are fine in EITHER mode and so don't discriminate between
# them (they aren't part of the duplicated stack).
SHARED_UNITS = frozenset({"bonbon-dashboard", "bonbon-monitoring"})

# The full modular-Pi service set the spec defines (for completeness checks).
MODULAR_PI_UNITS = frozenset(MODULAR_SUBSYSTEM_UNITS | SHARED_UNITS)


class TopologyMode(StrEnum):
    MONOLITHIC = "monolithic"
    MODULAR_PI = "modular_pi"
    INVALID = "invalid"


@dataclass
class TopologyResult:
    mode: TopologyMode
    valid: bool
    reasons: list[str] = field(default_factory=list)
    remediation: str = ""
    expected_safety_supervisors: int = 1
    duplicate_safety_detected: bool = False
    duplicate_pipelines: list[str] = field(default_factory=list)
    enabled_units: list[str] = field(default_factory=list)
    # Populated only when a live ros2 safety-node count was supplied.
    observed_safety_supervisors: int | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "valid": self.valid,
            "reasons": list(self.reasons),
            "remediation": self.remediation,
            "expected_safety_supervisors": self.expected_safety_supervisors,
            "duplicate_safety_detected": self.duplicate_safety_detected,
            "duplicate_pipelines": list(self.duplicate_pipelines),
            "enabled_units": sorted(self.enabled_units),
            "observed_safety_supervisors": self.observed_safety_supervisors,
        }


def classify_topology(
    enabled_units: set[str] | frozenset[str],
    observed_safety_supervisors: int | None = None,
) -> TopologyResult:
    """Classify the deployment mode from the set of *enabled* systemd units.

    Args:
        enabled_units: unit names reported `enabled` by systemctl (with or
            without the ``.service`` suffix — both are normalised).
        observed_safety_supervisors: optional live count of
            ``safety_supervisor_node`` processes from ``ros2 node list``;
            when provided, a count != the expected 1 forces INVALID.
    """
    enabled = {_normalise(u) for u in enabled_units}
    core_enabled = MONOLITHIC_UNIT in enabled
    duplicated = sorted(MODULAR_SUBSYSTEM_UNITS & enabled)

    result = TopologyResult(
        mode=TopologyMode.INVALID,
        valid=False,
        enabled_units=sorted(enabled),
        observed_safety_supervisors=observed_safety_supervisors,
    )

    if core_enabled and duplicated:
        # The duplicate-topology bug: monolith + per-subsystem services.
        result.mode = TopologyMode.INVALID
        result.valid = False
        result.duplicate_safety_detected = SAFETY_UNIT in enabled
        result.duplicate_pipelines = duplicated
        result.expected_safety_supervisors = 2 if SAFETY_UNIT in enabled else 1
        result.reasons.append(
            f"{MONOLITHIC_UNIT} (full bringup) is enabled together with "
            f"per-subsystem service(s) it already contains: {', '.join(duplicated)}. "
            "This starts duplicate pipelines"
            + (
                " — including TWO safety supervisors (nondeterministic " "/bonbon/safety/state)."
                if SAFETY_UNIT in enabled
                else "."
            )
        )
        result.remediation = (
            "Choose ONE mode. For modular Pi production:\n"
            f"  sudo systemctl disable --now {MONOLITHIC_UNIT}\n"
            "  bash scripts/enable_modular_pi_mode.sh\n"
            "For monolithic (sim/lab/dev):\n"
            f"  sudo systemctl disable --now {' '.join(duplicated)}\n"
            "  bash scripts/enable_monolithic_mode.sh"
        )
        return _apply_observed(result)

    if core_enabled:
        result.mode = TopologyMode.MONOLITHIC
        result.valid = True
        result.expected_safety_supervisors = 1
        result.reasons.append(
            f"{MONOLITHIC_UNIT} enabled, no conflicting per-subsystem services — "
            "single full stack with exactly one safety supervisor."
        )
        return _apply_observed(result)

    if SAFETY_UNIT in enabled:
        result.mode = TopologyMode.MODULAR_PI
        result.valid = True
        result.expected_safety_supervisors = 1
        missing = sorted(MODULAR_SUBSYSTEM_UNITS - enabled - {SAFETY_UNIT})
        result.reasons.append(
            f"Modular mode: {MONOLITHIC_UNIT} disabled, {SAFETY_UNIT} provides the "
            "single safety supervisor."
        )
        if missing:
            result.reasons.append(
                "Note: some modular subsystem services are not enabled "
                f"({', '.join(missing)}); the robot will run with reduced "
                "capability but safety is intact."
            )
        return _apply_observed(result)

    # Neither monolith nor standalone safety: NO safety supervisor at all.
    result.mode = TopologyMode.INVALID
    result.valid = False
    result.expected_safety_supervisors = 0
    result.reasons.append(
        f"Neither {MONOLITHIC_UNIT} nor {SAFETY_UNIT} is enabled — there is NO "
        "safety supervisor in this configuration. The robot must never run "
        "without one."
    )
    result.remediation = (
        "Enable a safety supervisor by selecting a mode:\n"
        "  bash scripts/enable_modular_pi_mode.sh   # Pi production\n"
        "  bash scripts/enable_monolithic_mode.sh   # sim / lab / dev"
    )
    return _apply_observed(result)


def _apply_observed(result: TopologyResult) -> TopologyResult:
    """Fold a live ros2 safety-node count into the verdict. More than one
    running safety supervisor is always INVALID, whatever the unit set said."""
    n = result.observed_safety_supervisors
    if n is None:
        return result
    if n > 1:
        result.duplicate_safety_detected = True
        result.valid = False
        result.mode = TopologyMode.INVALID
        result.reasons.append(
            f"RUNTIME: {n} safety_supervisor_node processes observed via "
            "`ros2 node list` — exactly one is required."
        )
        if not result.remediation:
            result.remediation = (
                "Stop the duplicate stack: `bash scripts/check_duplicate_ros_nodes.sh` "
                "shows which, then disable the extra service."
            )
    elif n == 0 and result.expected_safety_supervisors >= 1:
        result.valid = False
        result.reasons.append(
            "RUNTIME: no safety_supervisor_node is running, but this mode "
            "expects one — the safety supervisor failed to start."
        )
    return result


def _normalise(unit: str) -> str:
    u = unit.strip()
    return u[: -len(".service")] if u.endswith(".service") else u
