from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Employee, Influencer, Lead, Product, StudentClubMember, Task


def founder_dashboard(db: Session) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    total_tasks = db.scalar(select(func.count(Task.id))) or 0
    delayed_tasks = db.scalar(
        select(func.count(Task.id)).where(Task.deadline < now, Task.status.notin_(["done", "cancelled"]))
    ) or 0
    followups_due = db.scalar(
        select(func.count(Lead.id)).where(Lead.next_followup_at <= now, Lead.stage.notin_(["won", "lost"]))
    ) or 0
    unsigned_influencers = db.scalar(
        select(func.count(Influencer.id)).where(Influencer.legal_agreement_status != "signed")
    ) or 0
    active_students = db.scalar(
        select(func.count(StudentClubMember.id)).where(StudentClubMember.volunteer_status != "inactive")
    ) or 0

    metrics = {
        "employees": db.scalar(select(func.count(Employee.id))) or 0,
        "products": db.scalar(select(func.count(Product.id))) or 0,
        "tasks": total_tasks,
        "delayed_tasks": delayed_tasks,
        "followups_due": followups_due,
        "sales_pipeline_value": db.scalar(select(func.coalesce(func.sum(Lead.deal_value_estimate), 0))) or 0,
        "influencers": db.scalar(select(func.count(Influencer.id))) or 0,
        "unsigned_influencers": unsigned_influencers,
        "student_members": active_students,
        "robotics_progress": 18,
        "agri_market_progress": 12,
        "political_preparation_progress": 9,
    }
    alerts = []
    if delayed_tasks:
        alerts.append({"level": "high", "message": f"{delayed_tasks} delayed tasks need escalation."})
    if followups_due:
        alerts.append({"level": "medium", "message": f"{followups_due} lead follow-ups are due."})
    if unsigned_influencers:
        alerts.append({"level": "medium", "message": "Influencer agreement statuses need cleanup."})

    return {
        "metrics": metrics,
        "alerts": alerts,
        "charts": {
            "sales_by_stage": _count_by(db, Lead.stage),
            "leads_by_industry": _count_by(db, Lead.industry),
            "influencers_by_platform": _count_by(db, Influencer.platform),
            "students_by_district": _count_by(db, StudentClubMember.district),
        },
    }


def _count_by(db: Session, column) -> list[dict[str, int | str]]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return [{"label": row[0] or "Unknown", "value": row[1]} for row in rows]
