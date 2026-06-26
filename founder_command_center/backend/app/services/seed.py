from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.entities import Employee, Influencer, Lead, Product, StudentClubMember, Task, User


def seed_database(db: Session) -> dict[str, int]:
    if db.scalar(select(User).where(User.username == "founder")):
        return {"created": 0}

    employees = [
        Employee(name="Software Employee 1", role="Full-stack Developer", skills=["websites", "ERP", "CRM"]),
        Employee(name="Software Employee 2", role="Backend Developer", skills=["FastAPI", "databases", "automation"]),
        Employee(name="Operations Coordinator", role="Operations", skills=["documentation", "fieldwork"]),
        Employee(name="Marketing Coordinator", role="Marketing", skills=["outreach", "events", "content"]),
    ]
    products = [
        Product(name="Hospital ERP", category="ERP", target_customer="Hospitals and clinics", pricing="Custom"),
        Product(name="University ERP", category="ERP", target_customer="Universities and colleges", pricing="Custom"),
        Product(name="School ERP", category="ERP", target_customer="Premium schools", pricing="Custom"),
        Product(name="Construction Company ERP", category="ERP", target_customer="Builders and contractors"),
        Product(name="Election Campaign ERP", category="Political ERP", target_customer="Ethical campaign offices"),
        Product(name="Political Office Management ERP", category="Political ERP", target_customer="Public offices"),
        Product(name="Telemedicine Global Connect", category="Digital Health", target_customer="Doctors and foreign patients"),
        Product(name="Consultancy Management System", category="CRM", target_customer="Consulting firms"),
        Product(name="Website Development Services", category="Service", target_customer="Premium local businesses"),
        Product(name="Digital Marketing Services", category="Service", target_customer="Growth-focused businesses"),
    ]
    now = datetime.now(UTC).replace(tzinfo=None)
    tasks = [
        Task(
            title="Prepare premium Hospital ERP demo flow",
            goal="ERP sales",
            assigned_by_agent="ERP/CRM Product Sales Agent",
            priority="high",
            deadline=now + timedelta(days=2),
            expected_output="Demo script and screenshots",
        ),
        Task(
            title="Create district influencer onboarding sheet",
            goal="10,000 influencer network",
            assigned_by_agent="Influencer Network Builder Agent",
            priority="high",
            deadline=now + timedelta(days=3),
            expected_output="CSV-ready onboarding tracker",
        ),
    ]
    leads = [
        Lead(
            company_name="Sri Care Hospital",
            contact_person="Operations Head",
            industry="Hospital",
            district="Vijayawada",
            product_interest="Hospital ERP",
            deal_value_estimate=750000,
            stage="qualified",
            next_followup_at=now,
        ),
        Lead(
            company_name="Elite Builders AP",
            industry="Construction",
            district="Guntur",
            product_interest="Construction Company ERP",
            deal_value_estimate=500000,
            stage="new",
            next_followup_at=now + timedelta(days=1),
        ),
    ]
    influencers = [
        Influencer(
            name="Vizag Tech Voice",
            platform="YouTube",
            district="Visakhapatnam",
            state="Andhra Pradesh",
            niche="technology",
            followers=45000,
            average_views=9000,
            engagement_rate=4.8,
            legal_agreement_status="review_pending",
            content_quality_score=82,
            brand_safety_score=88,
        )
    ]
    students = [
        StudentClubMember(
            name="Campus Lead A",
            college="AP Engineering College",
            district="Guntur",
            state="Andhra Pradesh",
            interest_group="Robotics",
            leadership_potential=80,
            volunteer_status="active",
        )
    ]
    db.add(User(username="founder", password_hash=hash_password("founder123"), role="founder"))
    db.add_all([*employees, *products, *tasks, *leads, *influencers, *students])
    db.commit()
    return {"created": 1}
