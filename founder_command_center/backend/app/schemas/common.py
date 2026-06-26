from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EmployeeCreate(BaseModel):
    name: str
    role: str
    skills: list[str] = Field(default_factory=list)
    workload_score: int = 0
    performance_score: int = 70
    notes: str | None = None


class EmployeeRead(EmployeeCreate, ORMModel):
    id: int
    active_tasks_count: int = 0


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    goal: str | None = None
    assigned_to_employee_id: int | None = None
    assigned_by_agent: str | None = None
    priority: str = "medium"
    status: str = "todo"
    deadline: datetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    review_notes: str | None = None
    risk_level: str = "low"
    escalation_required: bool = False


class TaskRead(TaskCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class ProductCreate(BaseModel):
    name: str
    category: str
    target_customer: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    pricing: str | None = None
    demo_link: str | None = None
    pitch_script: str | None = None
    competitors: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    status: str = "active"


class ProductRead(ProductCreate, ORMModel):
    id: int


class LeadCreate(BaseModel):
    company_name: str
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    industry: str
    district: str | None = None
    lead_source: str | None = None
    product_interest: str | None = None
    deal_value_estimate: float = 0
    stage: str = "new"
    next_followup_at: datetime | None = None
    assigned_employee: str | None = None
    notes: str | None = None


class LeadRead(LeadCreate, ORMModel):
    id: int


class InfluencerCreate(BaseModel):
    name: str
    platform: str
    profile_url: str | None = None
    district: str | None = None
    state: str | None = None
    niche: str | None = None
    followers: int = 0
    average_views: int = 0
    engagement_rate: float = 0
    audience_type: str | None = None
    contact_details: str | None = None
    collaboration_interest: str | None = None
    expected_payment: str | None = None
    legal_agreement_status: str = "not_started"
    event_attended: bool = False
    content_quality_score: int = 0
    brand_safety_score: int = 0
    relationship_score: int = 0
    notes: str | None = None


class InfluencerRead(InfluencerCreate, ORMModel):
    id: int


class StudentClubMemberCreate(BaseModel):
    name: str
    college: str
    district: str
    state: str
    interest_group: str
    skill: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    club_role: str | None = None
    weekly_activity_status: str = "pending"
    leadership_potential: int = 0
    volunteer_status: str = "new"
    assigned_coordinator: str | None = None
    notes: str | None = None


class StudentClubMemberRead(StudentClubMemberCreate, ORMModel):
    id: int


class DashboardRead(BaseModel):
    metrics: dict[str, Any]
    alerts: list[dict[str, Any]]
    charts: dict[str, Any]


class ReportRead(BaseModel):
    cycle: str
    generated_at: str
    sections: dict[str, Any]
    recommendations: list[dict[str, Any]]
