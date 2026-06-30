"""Tests for the boot-topology classifier (devops/scripts/boot_topology.py).

These are the Phase 2 deliverable tests 1-8: they exercise the pure
classifier directly (no systemd/ROS2 needed), so they run anywhere and
prove the duplicate-safety-supervisor guard works.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the classifier as a proper module (registered in sys.modules) so its
# dataclasses' annotation processing works — the generic load_script helper
# execs without registering, which trips dataclass field handling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import boot_topology as bt  # noqa: E402


# 1. monolithic mode validation passes
def test_monolithic_mode_valid():
    r = bt.classify_topology({"bonbon-core", "bonbon-dashboard", "bonbon-monitoring"})
    assert r.mode == bt.TopologyMode.MONOLITHIC
    assert r.valid is True
    assert r.expected_safety_supervisors == 1
    assert r.duplicate_safety_detected is False


# 2. modular Pi mode validation passes
def test_modular_pi_mode_valid():
    r = bt.classify_topology(
        {
            "bonbon-safety",
            "bonbon-hal",
            "bonbon-perception",
            "bonbon-speech",
            "bonbon-behavior",
            "bonbon-navigation",
            "bonbon-actuation",
            "bonbon-dashboard",
            "bonbon-monitoring",
        }
    )
    assert r.mode == bt.TopologyMode.MODULAR_PI
    assert r.valid is True
    assert r.expected_safety_supervisors == 1


# 3. mixed mode fails
def test_mixed_mode_invalid():
    r = bt.classify_topology({"bonbon-core", "bonbon-perception"})
    assert r.mode == bt.TopologyMode.INVALID
    assert r.valid is False
    assert "bonbon-perception" in r.duplicate_pipelines


# 4. duplicate safety service fails (the headline bug)
def test_duplicate_safety_service_fails():
    r = bt.classify_topology({"bonbon-core", "bonbon-safety"})
    assert r.valid is False
    assert r.duplicate_safety_detected is True
    assert r.expected_safety_supervisors == 2
    assert "safety" in " ".join(r.reasons).lower()


# 5. duplicate perception pipeline warning/flag appears
def test_duplicate_perception_pipeline_flagged():
    r = bt.classify_topology({"bonbon-core", "bonbon-perception", "bonbon-speech"})
    assert r.valid is False
    assert "bonbon-perception" in r.duplicate_pipelines
    assert "bonbon-speech" in r.duplicate_pipelines


# 6. dashboard readiness shows boot-topology blocker (result is serialisable
#    for the dashboard and carries the blocker fields it needs)
def test_result_serialises_for_dashboard():
    r = bt.classify_topology({"bonbon-core", "bonbon-safety"})
    d = r.to_dict()
    assert d["valid"] is False
    assert d["duplicate_safety_detected"] is True
    assert d["mode"] == "invalid"
    assert isinstance(d["reasons"], list) and d["reasons"]
    assert d["remediation"]  # non-empty


# 7. known_issues / remediation updates correctly — every invalid verdict
#    carries a concrete remediation command
def test_invalid_verdicts_carry_remediation():
    for enabled in (
        {"bonbon-core", "bonbon-safety"},  # duplicate
        {"bonbon-dashboard"},  # no safety at all
    ):
        r = bt.classify_topology(enabled)
        assert r.valid is False
        assert r.remediation.strip(), f"no remediation for {enabled}"
        assert "scripts/" in r.remediation  # points at a real script


# 8. remediation command is generated and references the mode scripts
def test_remediation_references_mode_scripts():
    r = bt.classify_topology({"bonbon-core", "bonbon-safety"})
    assert "enable_modular_pi_mode.sh" in r.remediation
    assert "enable_monolithic_mode.sh" in r.remediation


# Extra: runtime duplicate detection via observed node count
def test_runtime_observed_two_safety_supervisors_is_invalid():
    r = bt.classify_topology({"bonbon-core"}, observed_safety_supervisors=2)
    assert r.valid is False
    assert r.duplicate_safety_detected is True
    assert any("RUNTIME" in reason for reason in r.reasons)


def test_runtime_observed_zero_when_one_expected_is_invalid():
    r = bt.classify_topology({"bonbon-safety"}, observed_safety_supervisors=0)
    assert r.valid is False


def test_no_safety_supervisor_anywhere_is_invalid():
    r = bt.classify_topology({"bonbon-dashboard", "bonbon-monitoring"})
    assert r.valid is False
    assert r.expected_safety_supervisors == 0


def test_service_suffix_is_normalised():
    r = bt.classify_topology({"bonbon-core.service", "bonbon-safety.service"})
    assert r.duplicate_safety_detected is True
