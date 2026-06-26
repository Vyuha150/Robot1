from app.agents.orchestrator import FounderCommandOrchestrator


def test_weekly_cycle_adds_strategic_recommendation() -> None:
    result = FounderCommandOrchestrator().run_weekly_cycle(
        {"delayed_tasks": 0, "followups_due": 0, "unsigned_influencers": 0, "consent_gaps": 0}
    )
    assert result["cycle"] == "weekly"
    assert any(item["agent"] == "Strategy and Opportunity Agent" for item in result["recommendations"])
