from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import ast
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is absent in CI
    yaml = None


Point = Tuple[float, float]


@dataclass(frozen=True)
class RobotDimensions:
    length_m: float = 0.72
    width_m: float = 0.48
    height_m: float = 1.15
    footprint_radius_m: float = 0.36
    wheel_radius_m: float = 0.075
    wheel_separation_m: float = 0.42


@dataclass(frozen=True)
class SensorConfig:
    lidar_topic: str = "/scan"
    imu_topic: str = "/imu/data"
    rgb_topic: str = "/camera/color/image_raw"
    depth_topic: str = "/camera/depth/image_raw"
    mic_event_topic: str = "/bonbon/speech/mic_event"
    battery_topic: str = "/bonbon/battery/state"
    estop_topic: str = "/bonbon/estop/state"
    servo_topic: str = "/bonbon/servo/state"
    publish_timeout_sec: float = 1.0


@dataclass(frozen=True)
class ValidationTargets:
    max_collisions: int = 0
    max_estop_reaction_ms: float = 300.0
    max_lidar_failure_detection_ms: float = 1000.0
    max_replanning_latency_ms: float = 1000.0
    max_blocked_path_recovery_sec: float = 10.0
    min_docking_success_rate: float = 0.95
    min_navigation_success_rate: float = 0.95
    min_repeatability: float = 0.99


@dataclass(frozen=True)
class ScenarioEvent:
    time_sec: float
    type: str
    target: str = "robot"
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    world: str
    seed: int
    start: Point
    goal: Point
    environment: str
    duration_sec: float = 120.0
    headless: bool = True
    entities: List[Dict[str, Any]] = field(default_factory=list)
    events: List[ScenarioEvent] = field(default_factory=list)
    criteria: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationConfig:
    robot: RobotDimensions = field(default_factory=RobotDimensions)
    sensors: SensorConfig = field(default_factory=SensorConfig)
    targets: ValidationTargets = field(default_factory=ValidationTargets)
    report_dir: Path = Path("simulation_reports")
    artifact_dir: Path = Path("simulation_artifacts")
    random_seed: int = 4242
    time_step_sec: float = 0.1
    accelerated_endurance: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> "SimulationConfig":
        data = _load_yaml(path)
        robot = RobotDimensions(**data.get("robot", {}))
        sensors = SensorConfig(**data.get("sensors", {}))
        targets = ValidationTargets(**data.get("targets", {}))
        return cls(
            robot=robot,
            sensors=sensors,
            targets=targets,
            report_dir=Path(data.get("report_dir", "simulation_reports")),
            artifact_dir=Path(data.get("artifact_dir", "simulation_artifacts")),
            random_seed=int(data.get("random_seed", 4242)),
            time_step_sec=float(data.get("time_step_sec", 0.1)),
            accelerated_endurance=bool(data.get("accelerated_endurance", True)),
        )


def load_scenario(path: str | Path) -> ScenarioConfig:
    data = _load_yaml(path)
    raw_events = data.get("events", [])
    events = [
        ScenarioEvent(
            time_sec=float(item["time_sec"]),
            type=str(item["type"]),
            target=str(item.get("target", "robot")),
            params=dict(item.get("params", {})),
        )
        for item in raw_events
    ]
    return ScenarioConfig(
        name=str(data["name"]),
        world=str(data["world"]),
        seed=int(data.get("seed", 4242)),
        start=_point(data.get("start", [0.0, 0.0])),
        goal=_point(data.get("goal", [5.0, 0.0])),
        environment=str(data.get("environment", data["world"])),
        duration_sec=float(data.get("duration_sec", 120.0)),
        headless=bool(data.get("headless", True)),
        entities=list(data.get("entities", [])),
        events=events,
        criteria=dict(data.get("criteria", {})),
    )


def _load_yaml(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        text = handle.read()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _parse_minimal_yaml(text)


def _point(value: Any) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError(f"Expected [x, y] point, got {value!r}")
    return (float(value[0]), float(value[1]))


def _parse_minimal_yaml(text: str) -> Dict[str, Any]:
    """Parse the small YAML subset used by simulation configs.

    This fallback keeps the headless test suite dependency-light. It supports
    nested dictionaries, lists, inline maps, inline lists, booleans, numbers,
    and strings.
    """
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    parsed, _ = _parse_yaml_block(lines, 0, 0)
    return parsed if isinstance(parsed, dict) else {}


def _parse_yaml_block(lines: List[Tuple[int, str]], index: int, indent: int) -> Tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index][1].startswith("- "):
        result = []
        while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            item_text = lines[index][1][2:].strip()
            index += 1
            if not item_text:
                item, index = _parse_yaml_block(lines, index, indent + 2)
            elif ":" in item_text and not item_text.startswith("{"):
                key, value = item_text.split(":", 1)
                item = {key.strip(): _parse_scalar(value.strip())}
                while index < len(lines) and lines[index][0] > indent:
                    child_indent, child_text = lines[index]
                    if child_indent < indent + 2 or child_text.startswith("- "):
                        break
                    child_key, child_value = child_text.split(":", 1)
                    if child_value.strip():
                        item[child_key.strip()] = _parse_scalar(child_value.strip())
                        index += 1
                    else:
                        nested, index = _parse_yaml_block(lines, index + 1, child_indent + 2)
                        item[child_key.strip()] = nested
            else:
                item = _parse_scalar(item_text)
            result.append(item)
        return result, index

    result: Dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent:
        text = lines[index][1]
        key, value = text.split(":", 1)
        key = key.strip()
        value = value.strip()
        index += 1
        if value:
            result[key] = _parse_scalar(value)
        else:
            nested, index = _parse_yaml_block(lines, index, indent + 2)
            result[key] = nested
    return result, index


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(part.strip()) for part in value[1:-1].split(",") if part.strip()]
    if value.startswith("{") and value.endswith("}"):
        return _parse_inline_map(value[1:-1])
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        pass
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _parse_inline_map(value: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for part in _split_top_level(value):
        if not part.strip():
            continue
        key, raw = part.split(":", 1)
        result[key.strip().strip("'\"")] = _parse_scalar(raw.strip())
    return result


def _split_top_level(value: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    start = 0
    for idx, char in enumerate(value):
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:idx])
            start = idx + 1
    parts.append(value[start:])
    return parts
