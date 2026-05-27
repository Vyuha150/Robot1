from __future__ import annotations

import re

from conftest import ROOT

REQUIRED_PLATFORM_DOCS = {
    "README.md": ["overview", "architecture", "setup", "configuration", "ros2 interfaces"],
    "overview.md": ["package families", "safety principle"],
    "architecture.md": ["runtime layers", "safety-critical flow", "deployment flow"],
    "setup.md": ["prerequisites", "build ros2 workspace", "run simulation smoke"],
    "configuration.md": ["ros2 package configs", "runtime secrets", "simulation config"],
    "modules.md": [
        "bonbon_safety",
        "bonbon_navigation",
        "bonbon_operator_api",
        "bonbon_simulation",
    ],
    "api.md": ["command api", "robot status api", "memory and rag api", "websocket api"],
    "ros2_interfaces.md": ["core sensor topics", "safety topics and services", "navigation topics"],
    "examples.md": ["launch safety stack", "send navigation goal", "deployment dry run"],
    "tests.md": [
        "unit tests",
        "integration tests",
        "failure injection tests",
        "latency benchmarks",
    ],
    "troubleshooting.md": [
        "safety state does not publish",
        "robot will not move",
        "deployment fails",
    ],
    "deployment.md": ["pre-deployment checks", "post-deployment checks", "rollback"],
    "performance_tuning.md": ["ros2", "navigation", "deployment"],
    "security.md": ["secrets", "operator api", "data privacy"],
    "future_improvements.md": ["platform", "safety", "simulation", "deployment"],
}


def test_platform_docs_have_required_sections():
    docs_dir = ROOT / "docs"
    for filename, fragments in REQUIRED_PLATFORM_DOCS.items():
        path = docs_dir / filename
        assert path.exists(), filename
        text = path.read_text(encoding="utf-8").lower()
        for fragment in fragments:
            assert fragment in text, f"{filename} missing {fragment}"


def test_platform_docs_index_links_exist():
    docs_dir = ROOT / "docs"
    readme = (docs_dir / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+\.md)\)", readme):
        assert (docs_dir / target).exists(), target


def test_platform_docs_do_not_contain_runtime_secret_values():
    pattern = re.compile(r"BONBON_(JWT_SECRET|ADMIN_PASSWORD)=\S+")
    for path in (ROOT / "docs").glob("*.md"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path
