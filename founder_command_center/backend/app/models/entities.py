from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Person(Base, TimestampMixin):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(180), index=True)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    mandal_or_city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    organization: Mapped[str | None] = mapped_column(String(180))
    role: Mapped[str | None] = mapped_column(String(120))
    influence_level: Mapped[str | None] = mapped_column(String(40))
    relationship_strength: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(120))
    consent_status: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    assigned_employee: Mapped[str | None] = mapped_column(String(120))
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    role: Mapped[str] = mapped_column(String(120), index=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    workload_score: Mapped[int] = mapped_column(Integer, default=0)
    active_tasks_count: Mapped[int] = mapped_column(Integer, default=0)
    performance_score: Mapped[int] = mapped_column(Integer, default=70)
    notes: Mapped[str | None] = mapped_column(Text)

    tasks: Mapped[list["Task"]] = relationship(back_populates="employee")


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(String(220), index=True)
    assigned_to_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    assigned_by_agent: Mapped[str | None] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(40), default="todo", index=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_output: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), default="low")
    escalation_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    employee: Mapped[Employee | None] = relationship(back_populates="tasks")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    target_customer: Mapped[str | None] = mapped_column(Text)
    pain_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    pricing: Mapped[str | None] = mapped_column(String(180))
    demo_link: Mapped[str | None] = mapped_column(String(255))
    pitch_script: Mapped[str | None] = mapped_column(Text)
    competitors: Mapped[list[str]] = mapped_column(JSON, default=list)
    objections: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(180), index=True)
    contact_person: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(180), index=True)
    industry: Mapped[str] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    lead_source: Mapped[str | None] = mapped_column(String(120))
    product_interest: Mapped[str | None] = mapped_column(String(180), index=True)
    deal_value_estimate: Mapped[float] = mapped_column(Float, default=0)
    stage: Mapped[str] = mapped_column(String(60), default="new", index=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    assigned_employee: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


class Influencer(Base, TimestampMixin):
    __tablename__ = "influencers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    platform: Mapped[str] = mapped_column(String(80), index=True)
    profile_url: Mapped[str | None] = mapped_column(String(255), unique=True)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(120), index=True)
    niche: Mapped[str | None] = mapped_column(String(120), index=True)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    average_views: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0)
    audience_type: Mapped[str | None] = mapped_column(String(120))
    contact_details: Mapped[str | None] = mapped_column(Text)
    collaboration_interest: Mapped[str | None] = mapped_column(String(80))
    expected_payment: Mapped[str | None] = mapped_column(String(120))
    legal_agreement_status: Mapped[str] = mapped_column(String(60), default="not_started", index=True)
    event_attended: Mapped[bool] = mapped_column(Boolean, default=False)
    content_quality_score: Mapped[int] = mapped_column(Integer, default=0)
    brand_safety_score: Mapped[int] = mapped_column(Integer, default=0)
    relationship_score: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class StudentClubMember(Base, TimestampMixin):
    __tablename__ = "student_club_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    college: Mapped[str] = mapped_column(String(220), index=True)
    district: Mapped[str] = mapped_column(String(120), index=True)
    state: Mapped[str] = mapped_column(String(120), index=True)
    interest_group: Mapped[str] = mapped_column(String(120), index=True)
    skill: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(180), index=True)
    club_role: Mapped[str | None] = mapped_column(String(120))
    weekly_activity_status: Mapped[str] = mapped_column(String(80), default="pending")
    leadership_potential: Mapped[int] = mapped_column(Integer, default=0)
    volunteer_status: Mapped[str] = mapped_column(String(80), default="new")
    assigned_coordinator: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    venue: Mapped[str | None] = mapped_column(String(220))
    date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    expected_attendees: Mapped[int] = mapped_column(Integer, default=0)
    budget: Mapped[float] = mapped_column(Float, default=0)
    sponsor_status: Mapped[str | None] = mapped_column(String(80))
    guest_list: Mapped[list[str]] = mapped_column(JSON, default=list)
    registration_link: Mapped[str | None] = mapped_column(String(255))
    agenda: Mapped[list[str]] = mapped_column(JSON, default=list)
    post_event_followup_status: Mapped[str] = mapped_column(String(80), default="pending")
    notes: Mapped[str | None] = mapped_column(Text)


class PoliticalConstituencyProfile(Base, TimestampMixin):
    __tablename__ = "political_constituency_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(120), index=True)
    district: Mapped[str] = mapped_column(String(120), index=True)
    constituency: Mapped[str] = mapped_column(String(160), index=True)
    key_leaders: Mapped[list[str]] = mapped_column(JSON, default=list)
    local_issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    youth_issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    farmer_issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    community_organizations: Mapped[list[str]] = mapped_column(JSON, default=list)
    influencers: Mapped[list[str]] = mapped_column(JSON, default=list)
    media_pages: Mapped[list[str]] = mapped_column(JSON, default=list)
    public_sentiment_notes: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    opportunities: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime)


class AgriMarketOpportunity(Base, TimestampMixin):
    __tablename__ = "agri_market_opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(160), index=True)
    sub_product: Mapped[str | None] = mapped_column(String(160), index=True)
    district_source: Mapped[str | None] = mapped_column(String(120), index=True)
    destination_market: Mapped[str] = mapped_column(String(180), index=True)
    buyer_type: Mapped[str] = mapped_column(String(120), index=True)
    buyer_company: Mapped[str | None] = mapped_column(String(180), index=True)
    contact_info: Mapped[str | None] = mapped_column(Text)
    certification_required: Mapped[str | None] = mapped_column(Text)
    packaging_requirement: Mapped[str | None] = mapped_column(Text)
    logistics_notes: Mapped[str | None] = mapped_column(Text)
    estimated_margin: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(80), default="researching", index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    risk_level: Mapped[str] = mapped_column(String(40), default="low")
    human_approval_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
