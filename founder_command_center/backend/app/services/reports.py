from sqlalchemy.orm import Session

from app.agents.orchestrator import FounderCommandOrchestrator
from app.services.dashboard import founder_dashboard


def daily_report(db: Session) -> dict:
    dashboard = founder_dashboard(db)
    metrics = dashboard["metrics"]
    orchestration = FounderCommandOrchestrator().run_daily_cycle(
        {
            "delayed_tasks": metrics["delayed_tasks"],
            "followups_due": metrics["followups_due"],
            "unsigned_influencers": metrics["unsigned_influencers"],
            "consent_gaps": 0,
        }
    )
    return {
        "cycle": "daily",
        "generated_at": orchestration["generated_at"],
        "sections": {
            "founder_priority_brief": dashboard["alerts"],
            "employee_task_list": "Review due and delayed tasks by priority.",
            "followups_due": metrics["followups_due"],
            "sales_actions": "Advance new and proposal-stage ERP/CRM leads.",
            "influencer_actions": "Prioritize district-wise outreach and agreement cleanup.",
            "student_club_actions": "Confirm weekly activity status and coordinator follow-ups.",
            "robotics_actions": "Review outsourcing blockers and pilot customer list.",
            "agri_market_actions": "Validate buyer categories and certification needs.",
            "political_intelligence_actions": "Update ethical public issue notes and stakeholder maps.",
            "risk_alerts": dashboard["alerts"],
        },
        "recommendations": orchestration["recommendations"],
    }


def weekly_report(db: Session) -> dict:
    dashboard = founder_dashboard(db)
    metrics = dashboard["metrics"]
    orchestration = FounderCommandOrchestrator().run_weekly_cycle(
        {
            "delayed_tasks": metrics["delayed_tasks"],
            "followups_due": metrics["followups_due"],
            "unsigned_influencers": metrics["unsigned_influencers"],
            "consent_gaps": 0,
        }
    )
    return {
        "cycle": "weekly",
        "generated_at": orchestration["generated_at"],
        "sections": {
            "founder_weekly_review": metrics,
            "employee_scorecards": "Use active task count, completion rate, and review quality.",
            "sales_pipeline_report": dashboard["charts"]["sales_by_stage"],
            "influencer_board_growth_report": dashboard["charts"]["influencers_by_platform"],
            "student_clubs_growth_report": dashboard["charts"]["students_by_district"],
            "robotics_progress_report": "MVP placeholder: roadmap, demos, pilot customers, blockers.",
            "agri_market_opportunity_report": "MVP placeholder: products, markets, buyers, export readiness.",
            "political_preparation_report": "Ethical capability building only: issues, stakeholders, office workflows.",
            "cashflow_and_billing_reminders": "Review proposals sent, invoices due, and renewal opportunities.",
            "strategic_recommendations": "Founder should select weekly rocks and review premium opportunities.",
        },
        "recommendations": orchestration["recommendations"],
    }
