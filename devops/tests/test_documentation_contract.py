from __future__ import annotations

import re

from conftest import ROOT

REQUIRED_DOCS = {
    "README.md": ["overview", "architecture", "setup", "configuration", "testing", "deployment"],
    "architecture.md": ["runtime topology", "safety deployment flow"],
    "configuration.md": ["required runtime variables", "validation"],
    "ros2_interfaces.md": ["required sensor topics", "safety interfaces", "navigation interfaces"],
    "examples.md": ["validate config", "robot deployment dry run"],
    "failure_modes.md": ["pre-deployment", "post-deployment", "rollback"],
    "troubleshooting.md": ["docker build fails", "deployment fails"],
    "tests.md": ["unit", "integration", "failure", "stress", "latency"],
    "deployment_notes.md": ["environment materialization", "release integrity", "audit trail"],
    "performance_tuning.md": ["docker", "ci", "ros2", "monitoring"],
    "security_concerns.md": ["secrets", "release", "volumes", "dashboard"],
}


def test_required_documentation_files_and_sections_exist():
    docs_dir = ROOT / "deployment" / "docs"
    for filename, fragments in REQUIRED_DOCS.items():
        path = docs_dir / filename
        assert path.exists(), filename
        text = path.read_text(encoding="utf-8").lower()
        for fragment in fragments:
            assert fragment in text, f"{filename} missing {fragment}"


def test_documentation_index_links_exist():
    docs_dir = ROOT / "deployment" / "docs"
    readme = (docs_dir / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+\.md)\)", readme):
        assert (docs_dir / target).exists(), target


def test_docs_do_not_include_runtime_secret_values():
    pattern = re.compile(r"BONBON_(JWT_SECRET|ADMIN_PASSWORD)=\S+")
    for path in (ROOT / "deployment" / "docs").glob("*.md"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path
