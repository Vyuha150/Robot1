from app.agents.orchestrator import FounderCommandOrchestrator
from app.agents.specs import AGENT_SPECS


def test_all_required_agents_are_defined() -> None:
    assert len(AGENT_SPECS) == 14
    assert {agent.key for agent in AGENT_SPECS} >= {"chief_of_staff", "data_compliance"}


def test_daily_cycle_recommendations_have_required_fields() -> None:
    result = FounderCommandOrchestrator().run_daily_cycle(
        {"delayed_tasks": 2, "followups_due": 3, "unsigned_influencers": 4, "consent_gaps": 1}
    )
    assert result["coordinator"] == "Founder Chief of Staff Agent"
    for recommendation in result["recommendations"]:
        assert recommendation["reasoning"]
        assert recommendation["required_action"]
        assert recommendation["owner"]
        assert recommendation["deadline"]
        assert recommendation["expected_outcome"]
        assert recommendation["risk_level"] in {"low", "medium", "high"}
