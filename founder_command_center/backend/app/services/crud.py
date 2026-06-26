from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


def list_records(db: Session, model: type[ModelT], limit: int = 100, offset: int = 0) -> list[ModelT]:
    return list(db.scalars(select(model).offset(offset).limit(limit)).all())


def create_record(db: Session, record: ModelT) -> ModelT:
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_record(db: Session, model: type[ModelT], record_id: int) -> ModelT | None:
    return db.get(model, record_id)
