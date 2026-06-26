from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.specs import AGENT_SPECS, AgentSpec


@dataclass
class Recommendation:
    agent: str
    title: str
    reasoning: str
    required_action: str
    owner: str
    deadline: str
    expected_outcome: str
    risk_level: str


class FounderCommandOrchestrator:
    """Deterministic MVP orchestration layer with LangGraph-style agent handoffs."""

    def __init__(self, agents: list[AgentSpec] | None = None) -> None:
        self.agents = agents or AGENT_SPECS

    def list_agents(self) -> list[dict[str, Any]]:
        return [asdict(agent) for agent in self.agents]

    def run_daily_cycle(self, context: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        recommendations = [
            self._task_recommendation(context, now),
            self._sales_recommendation(context, now),
            self._influencer_recommendation(context, now),
            self._compliance_recommendation(context, now),
        ]
        return {
            "cycle": "daily",
            "generated_at": now.isoformat(),
            "coordinator": "Founder Chief of Staff Agent",
            "handoffs": [
                "employee_manager",
                "erp_sales",
                "influencer_builder",
                "student_clubs",
                "data_compliance",
            ],
            "recommendations": [asdict(item) for item in recommendations],
        }

    def run_weekly_cycle(self, context: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        base = self.run_daily_cycle(context)["recommendations"]
        strategic = Recommendation(
            agent="Strategy and Opportunity Agent",
            title="Review premium ERP, robotics, agri, influencer, and political preparation lanes",
            reasoning="Weekly planning needs cross-business prioritization so employees are not split across too many unranked initiatives.",
            required_action="Select three weekly rocks and assign measurable outputs for each business lane.",
            owner="J V Kalyan",
            deadline=(now + timedelta(days=2)).date().isoformat(),
            expected_outcome="A focused execution board with founder-approved priorities.",
            risk_level="medium",
        )
        return {
            "cycle": "weekly",
            "generated_at": now.isoformat(),
            "coordinator": "Founder Chief of Staff Agent",
            "recommendations": [*base, asdict(strategic)],
        }

    def _task_recommendation(self, context: dict[str, Any], now: datetime) -> Recommendation:
        delayed = context.get("delayed_tasks", 0)
        return Recommendation(
            agent="Task Planner and Employee Manager Agent",
            title="Clear delayed high-priority tasks",
            reasoning=f"{delayed} delayed tasks need review before new work is assigned.",
            required_action="Review delayed work, confirm blockers, and redistribute overloaded assignments.",
            owner="Operations Manager",
            deadline=(now + timedelta(days=1)).date().isoformat(),
            expected_outcome="Delayed work is either completed, reassigned, or escalated.",
            risk_level="high" if delayed else "low",
        )

    def _sales_recommendation(self, context: dict[str, Any], now: datetime) -> Recommendation:
        due = context.get("followups_due", 0)
        return Recommendation(
            agent="ERP/CRM Product Sales Agent",
            title="Complete due lead follow-ups",
            reasoning=f"{due} follow-ups are due and sales momentum decays when prospects are not contacted.",
            required_action="Send targeted follow-up scripts for ERP, CRM, website, and telemedicine prospects.",
            owner="Sales Owner",
            deadline=now.date().isoformat(),
            expected_outcome="Lead stages are updated and qualified meetings are booked.",
            risk_level="medium" if due else "low",
        )

    def _influencer_recommendation(self, context: dict[str, Any], now: datetime) -> Recommendation:
        unsigned = context.get("unsigned_influencers", 0)
        return Recommendation(
            agent="Influencer Network Builder Agent",
            title="Move influencer prospects into consented onboarding",
            reasoning=f"{unsigned} influencer records still need consent or agreement status cleanup.",
            required_action="Prioritize district-wise outreach and send lawyer-reviewable agreement checklist.",
            owner="Influencer Coordinator",
            deadline=(now + timedelta(days=3)).date().isoformat(),
            expected_outcome="Influencer pipeline becomes campaign-ready without legal ambiguity.",
            risk_level="medium" if unsigned else "low",
        )

    def _compliance_recommendation(self, context: dict[str, Any], now: datetime) -> Recommendation:
        consent_gaps = context.get("consent_gaps", 0)
        return Recommendation(
            agent="Data, CRM and Compliance Agent",
            title="Resolve consent and source gaps",
            reasoning=f"{consent_gaps} personal-data records have unknown consent or weak source tracking.",
            required_action="Mark source, consent status, and follow-up permission before outreach.",
            owner="Data and Compliance Owner",
            deadline=(now + timedelta(days=2)).date().isoformat(),
            expected_outcome="CRM records are safer for outreach and audit review.",
            risk_level="high" if consent_gaps else "low",
        )
