"""EMRAdapter — extension point for a real hospital EMR/HIS lookup.

This pass ships MockEMRAdapter only, per the approved plan (adapters + mock
data, not a real vendor integration). Swap in a real implementation by
subclassing EMRAdapter and wiring it up in main.py's `_build_app` — nothing
in api/patient_lookup_api.py needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from bonbon_patient_kiosk.models.patient_models import PatientLookupRequest, PatientSummary


class EMRAdapter(ABC):
    @abstractmethod
    def lookup(self, request: PatientLookupRequest) -> PatientSummary | None: ...


class MockEMRAdapter(EMRAdapter):
    """In-memory fake patient directory for demos/tests."""

    def __init__(self) -> None:
        self._patients: dict[str, PatientSummary] = {
            "+6591234567": PatientSummary(
                patient_id="pat-001",
                display_name="Tan Wei Ming",
                date_of_birth="1985-03-14",
                last_visit_at=None,
            ),
            "S1234567A": PatientSummary(
                patient_id="pat-002",
                display_name="Priya Nair",
                date_of_birth="1990-11-02",
                last_visit_at=None,
            ),
        }

    def lookup(self, request: PatientLookupRequest) -> PatientSummary | None:
        return self._patients.get(request.identifier)

    def register(self, identifier: str, summary: PatientSummary) -> None:
        """Test/demo helper — real adapters would not expose this."""
        self._patients[identifier] = summary
