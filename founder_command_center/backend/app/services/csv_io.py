import csv
from io import StringIO
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models.entities import Influencer, Lead, StudentClubMember
from app.schemas.common import InfluencerCreate, LeadCreate, StudentClubMemberCreate
from app.services.crud import create_record

IMPORT_SCHEMAS: dict[str, tuple[type[BaseModel], type]] = {
    "leads": (LeadCreate, Lead),
    "influencers": (InfluencerCreate, Influencer),
    "student_club_members": (StudentClubMemberCreate, StudentClubMember),
}


def import_csv(db: Session, entity: str, csv_text: str) -> dict[str, Any]:
    if entity not in IMPORT_SCHEMAS:
        raise ValueError(f"Unsupported CSV entity: {entity}")
    schema, model = IMPORT_SCHEMAS[entity]
    reader = csv.DictReader(StringIO(csv_text))
    imported = 0
    errors = []
    for index, row in enumerate(reader, start=2):
        cleaned = {key: _coerce(value) for key, value in row.items()}
        try:
            data = schema.model_validate(cleaned).model_dump()
            create_record(db, model(**data))
            imported += 1
        except ValidationError as exc:
            errors.append({"line": index, "error": exc.errors()})
    return {"entity": entity, "imported": imported, "errors": errors}


def export_csv(rows: list[Any], fields: list[str]) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: getattr(row, field, "") for field in fields})
    return output.getvalue()


def _coerce(value: str | None) -> Any:
    if value is None or value == "":
        return None
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value
