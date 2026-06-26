from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.agents.orchestrator import FounderCommandOrchestrator
from app.core.auth import create_access_token, require_permission, verify_password
from app.core.database import get_db
from app.models.entities import Employee, Influencer, Lead, Product, StudentClubMember, Task, User
from app.schemas.common import (
    EmployeeCreate,
    EmployeeRead,
    InfluencerCreate,
    InfluencerRead,
    LeadCreate,
    LeadRead,
    ProductCreate,
    ProductRead,
    StudentClubMemberCreate,
    StudentClubMemberRead,
    TaskCreate,
    TaskRead,
)
from app.services.crud import create_record, get_record, list_records
from app.services.csv_io import export_csv, import_csv
from app.services.dashboard import founder_dashboard
from app.services.reports import daily_report, weekly_report
from app.services.seed import seed_database

router = APIRouter(prefix="/api")


@router.post("/auth/login")
def login(payload: dict, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.username == payload.get("username")).first()
    if not user or not verify_password(payload.get("password", ""), user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"access_token": create_access_token(user.username, user.role), "token_type": "bearer", "role": user.role}


@router.post("/seed")
def seed(db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> dict:
    return seed_database(db)


@router.get("/dashboard/founder")
def get_founder_dashboard(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> dict:
    return founder_dashboard(db)


@router.get("/agents")
def list_agents(_: dict = Depends(require_permission("read"))) -> list[dict]:
    return FounderCommandOrchestrator().list_agents()


@router.post("/agents/daily-cycle")
def run_daily_agent_cycle(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> dict:
    report = daily_report(db)
    return {"cycle": report["cycle"], "recommendations": report["recommendations"]}


@router.get("/reports/daily")
def get_daily_report(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> dict:
    return daily_report(db)


@router.get("/reports/weekly")
def get_weekly_report(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> dict:
    return weekly_report(db)


@router.get("/employees", response_model=list[EmployeeRead])
def employees(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[Employee]:
    return list_records(db, Employee)


@router.post("/employees", response_model=EmployeeRead)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> Employee:
    return create_record(db, Employee(**payload.model_dump()))


@router.get("/tasks", response_model=list[TaskRead])
def tasks(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[Task]:
    return list_records(db, Task)


@router.post("/tasks", response_model=TaskRead)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> Task:
    return create_record(db, Task(**payload.model_dump()))


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: dict, db: Session = Depends(get_db), _: dict = Depends(require_permission("task:update"))) -> Task:
    task = get_record(db, Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for key, value in payload.items():
        if hasattr(task, key):
            setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


@router.get("/products", response_model=list[ProductRead])
def products(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[Product]:
    return list_records(db, Product)


@router.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> Product:
    return create_record(db, Product(**payload.model_dump()))


@router.get("/leads", response_model=list[LeadRead])
def leads(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[Lead]:
    return list_records(db, Lead)


@router.post("/leads", response_model=LeadRead)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> Lead:
    return create_record(db, Lead(**payload.model_dump()))


@router.get("/influencers", response_model=list[InfluencerRead])
def influencers(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[Influencer]:
    return list_records(db, Influencer)


@router.post("/influencers", response_model=InfluencerRead)
def create_influencer(payload: InfluencerCreate, db: Session = Depends(get_db), _: dict = Depends(require_permission("write"))) -> Influencer:
    return create_record(db, Influencer(**payload.model_dump()))


@router.get("/student-clubs", response_model=list[StudentClubMemberRead])
def student_club_members(db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> list[StudentClubMember]:
    return list_records(db, StudentClubMember)


@router.post("/student-clubs", response_model=StudentClubMemberRead)
def create_student_member(
    payload: StudentClubMemberCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write")),
) -> StudentClubMember:
    return create_record(db, StudentClubMember(**payload.model_dump()))


@router.post("/csv/{entity}/import")
async def import_entity_csv(
    entity: str,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("write")),
) -> dict:
    body = await request.body()
    return import_csv(db, entity, body.decode("utf-8"))


@router.get("/csv/{entity}/export")
def export_entity_csv(entity: str, db: Session = Depends(get_db), _: dict = Depends(require_permission("read"))) -> Response:
    mapping = {
        "leads": (Lead, ["company_name", "contact_person", "phone", "email", "industry", "district", "stage"]),
        "influencers": (Influencer, ["name", "platform", "profile_url", "district", "niche", "followers"]),
        "student_club_members": (StudentClubMember, ["name", "college", "district", "interest_group", "phone", "email"]),
    }
    if entity not in mapping:
        raise HTTPException(status_code=404, detail="Unsupported CSV entity")
    model, fields = mapping[entity]
    content = export_csv(list_records(db, model, limit=5000), fields)
    return Response(content=content, media_type="text/csv")
