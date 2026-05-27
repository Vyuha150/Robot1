from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class ScenarioReport:
    scenario: str
    passed: bool
    reasons: list[str]
    metrics: dict[str, float | int]
    artifact_dir: str


class ScenarioReportGenerator:
    def __init__(self, report_dir: str | Path, artifact_dir: str | Path) -> None:
        self.report_dir = Path(report_dir)
        self.artifact_dir = Path(artifact_dir)

    def write(self, report: ScenarioReport) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.report_dir / f"{report.scenario}_{timestamp}.json"
        payload = {
            "scenario": report.scenario,
            "passed": report.passed,
            "reasons": report.reasons,
            "metrics": report.metrics,
            "artifact_dir": report.artifact_dir,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if not report.passed:
            artifact_path = (
                self.artifact_dir / f"{report.scenario}_{timestamp}_failure_snapshot.json"
            )
            artifact_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        return path
