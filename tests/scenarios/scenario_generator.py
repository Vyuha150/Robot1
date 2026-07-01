"""Expands tests/scenarios/scenario_catalog.yaml into concrete, IDed
Scenario objects and writes them to tests/scenarios/generated_scenarios/.

Each family declares the axes it varies (others stay at
scenario_schema.DEFAULT_AXIS_VALUE). The generator takes the cartesian
product of just those axes, then deterministically stride-samples down to
the family's `max_scenarios` cap so the catalog stays a few hundred
scenarios instead of exploding into millions -- coverage grows by widening
declared axes/values in the YAML, not by hand-writing more test functions.

Usage:
    python tests/scenarios/scenario_generator.py
    python tests/scenarios/scenario_generator.py --family gesture_understanding
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scenario_schema import (  # noqa: E402
    HardwareRequirement,
    InputConditions,
    MockStrategy,
    RiskLevel,
    Scenario,
)

_KNOWN_INPUT_FIELDS = {
    "environment",
    "lighting",
    "people",
    "gesture",
    "speech",
    "robot_state",
    "sensor",
}

_DEFAULT_CATALOG = Path(__file__).parent / "scenario_catalog.yaml"
_DEFAULT_OUT_DIR = Path(__file__).parent / "generated_scenarios"

# Short, readable tokens for scenario IDs. Anything not listed here falls
# back to a generic slug (see _abbreviate). Values that mean "more than one
# person" collapse to the multi-person "MP" token used in the brief's
# example ID (BB-HRI-MP-LOWLIGHT-STOPPALM-001).
_ABBREVIATIONS: dict[str, str] = {
    # environment
    "hospital_corridor": "HOSP",
    "hotel_lobby": "HOTEL",
    "office_reception": "OFFICE",
    "university_corridor": "UNI",
    "home_room": "HOME",
    "crowded_mall": "MALL",
    "narrow_passage": "NARROW",
    "low_light_area": "LOWLIGHTAREA",
    "noisy_area": "NOISYAREA",
    # lighting
    "bright": "BRIGHT",
    "low": "LOWLIGHT",
    "backlit": "BACKLIT",
    "flickering": "FLICKER",
    "night_mode": "NIGHT",
    # people (multi-person collapse)
    "one_person": "1P",
    "two_people": "MP",
    "five_people": "MP",
    "crowd": "MP",
    "child_nearby": "CHILD",
    "elderly_user": "ELDERLY",
    "wheelchair_user": "WHEELCHAIR",
    "unknown_person": "UNKNOWN",
    "known_person": "KNOWN",
    "off_camera_speaker": "OFFCAM",
    # gesture
    "none": "NONE",
    "wave": "WAVE",
    "raised_hand": "RAISEDHAND",
    "stop_palm": "STOPPALM",
    "pointing": "POINT",
    "thumbs_up": "THUMBSUP",
    "thumbs_down": "THUMBSDOWN",
    "come_here": "COMEHERE",
    "go_away": "GOAWAY",
    "conflicting_gestures": "CONFLICT",
    # speech
    "silent": "SILENT",
    "clear_speech": "CLEAR",
    "noisy_speech": "NOISYSPEECH",
    "overlapping_speech": "OVERLAP",
    "different_accent": "ACCENT",
    "telugu_hindi_english": "MULTILANG",
    "emergency_phrase": "EMERGENCY",
    "angry_tone": "ANGRY",
    "confused_question": "CONFUSED",
    # robot_state
    "idle": "IDLE",
    "navigating": "NAV",
    "speaking": "SPEAK",
    "turning": "TURN",
    "docking": "DOCK",
    "low_battery": "LOWBATT",
    "degraded_mode": "DEGRADED",
    "dashboard_disconnected": "DASHDISC",
    # sensor
    "normal": "NORMAL",
    "camera_lost": "NOCAM",
    "lidar_lost": "NOLIDAR",
    "mic_lost": "NOMIC",
    "imu_drift": "IMUDRIFT",
    "ai_hat_unavailable": "NOHAT",
    "high_temperature": "HOT",
    "cpu_overload": "CPUOVER",
    # family-specific axes
    "fresh_install": "FRESH",
    "upgrade_in_place": "UPGRADE",
    "power_loss_mid_boot": "PWRLOSS",
    "monolithic": "MONO",
    "modular_pi": "MODPI",
    "mixed_invalid": "MIXED",
    "present": "PRESENT",
    "absent": "ABSENT",
    "installed": "INSTALLED",
    "missing": "MISSING",
    "hef_valid": "HEFOK",
    "hef_missing": "HEFMISS",
    "hef_wrong_format": "HEFBAD",
    "onnx_only": "ONNXONLY",
    "normal_load": "NORMLOAD",
    "full_ai_load": "FULLLOAD",
    "connected": "CONN",
    "disconnected": "DISC",
    "slow_network": "SLOWNET",
    "authorized": "AUTH",
    "unauthorized": "UNAUTH",
    "enabled": "DEBUGON",
    "disabled": "DEBUGOFF",
    "wrong_object": "WRONGOBJ",
    "missed_object": "MISSOBJ",
    "wrong_gesture": "WRONGGEST",
    "missed_gesture": "MISSGEST",
    "wrong_speaker": "WRONGSPK",
    "wrong_person_identity": "WRONGID",
    "wrong_emotion": "WRONGEMO",
    "wrong_response": "WRONGRESP",
    "unsafe_proposal_blocked": "UNSAFEBLOCK",
    "navigation_failure": "NAVFAIL",
    "dashboard_mismatch": "DASHMISMATCH",
    "degraded_mode_failure": "DEGFAIL",
}


def _abbreviate(value: str) -> str:
    if value in _ABBREVIATIONS:
        return _ABBREVIATIONS[value]
    return re.sub(r"[^A-Z0-9]", "", value.upper())[:12] or "X"


def load_catalog(path: Path = _DEFAULT_CATALOG) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stride_sample(combos: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    if len(combos) <= max_n or max_n <= 0:
        return combos
    if max_n == 1:
        return [combos[0]]
    indices: list[int] = []
    seen: set[int] = set()
    for i in range(max_n):
        idx = round(i * (len(combos) - 1) / (max_n - 1))
        if idx not in seen:
            seen.add(idx)
            indices.append(idx)
    return [combos[i] for i in indices]


def _build_scenario(family: dict[str, Any], combo: dict[str, str], index: int) -> Scenario:
    code = family["code"]
    tokens = [_abbreviate(combo[axis]) for axis in family["axes"]]
    scenario_id = f"BB-{code}-{'-'.join(tokens)}-{index:03d}"

    field_kwargs: dict[str, str] = {}
    extra: dict[str, str] = {}
    for axis, value in combo.items():
        if axis in _KNOWN_INPUT_FIELDS:
            field_kwargs[axis] = value
        else:
            extra[axis] = value
    input_conditions = InputConditions(**field_kwargs, extra=extra)

    fmt = dict(combo)
    return Scenario(
        scenario_id=scenario_id,
        family=family["name"],
        category=family["category"],
        risk_level=RiskLevel(family["risk_level"]),
        input_conditions=input_conditions,
        expected_behavior=family["expected_behavior"].format(**fmt),
        required_safety_response=family["required_safety_response"].format(**fmt),
        dashboard_update=family["dashboard_update"].format(**fmt),
        pass_criteria=family["pass_criteria"].format(**fmt),
        fail_criteria=family["fail_criteria"].format(**fmt),
        mock_strategy=MockStrategy(family["mock_strategy"]),
        hardware_requirement=HardwareRequirement(family["hardware_requirement"]),
        metrics_to_capture=tuple(family.get("metrics", [])),
    )


def generate_family(family: dict[str, Any]) -> list[Scenario]:
    axes: dict[str, list[str]] = family["axes"]
    axis_names = list(axes.keys())
    all_combos = [
        dict(zip(axis_names, values, strict=True))
        for values in itertools.product(*[axes[a] for a in axis_names])
    ]
    sampled = _stride_sample(all_combos, family.get("max_scenarios", len(all_combos)))
    return [_build_scenario(family, combo, i + 1) for i, combo in enumerate(sampled)]


def generate_all(catalog: dict[str, Any]) -> dict[str, list[Scenario]]:
    return {family["name"]: generate_family(family) for family in catalog["families"]}


def write_generated(
    by_family: dict[str, list[Scenario]], out_dir: Path = _DEFAULT_OUT_DIR
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for family_name, scenarios in by_family.items():
        path = out_dir / f"{family_name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"family": family_name, "scenarios": [s.to_dict() for s in scenarios]},
                f,
                sort_keys=False,
            )
        counts[family_name] = len(scenarios)

    manifest_path = out_dir / "MANIFEST.yaml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"total_scenarios": sum(counts.values()), "scenarios_per_family": counts},
            f,
            sort_keys=False,
        )
    return counts


def load_generated(family_name: str, out_dir: Path = _DEFAULT_OUT_DIR) -> list[Scenario]:
    """Used by tests/production/test_*_scenarios.py to load a family's
    generated scenarios. Regenerates on the fly if the file is missing so a
    fresh checkout never needs a manual generation step before `pytest`."""
    path = out_dir / f"{family_name}.yaml"
    if not path.exists():
        catalog = load_catalog()
        family = next(f for f in catalog["families"] if f["name"] == family_name)
        write_generated({family_name: generate_family(family)}, out_dir)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [Scenario.from_dict(d) for d in data["scenarios"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=_DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--family", help="Generate only this family (by `name`)")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    families = catalog["families"]
    if args.family:
        families = [f for f in families if f["name"] == args.family]
        if not families:
            raise SystemExit(f"unknown family: {args.family}")

    by_family = {f["name"]: generate_family(f) for f in families}
    counts = write_generated(by_family, args.out)
    total = sum(counts.values())
    print(f"Generated {total} scenarios across {len(counts)} families -> {args.out}")
    for name, count in counts.items():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
