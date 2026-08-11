"""SchedulingAdapter — extension point for a real hospital scheduling system.

MockSchedulingAdapter seeds a small department/doctor/slot directory in
memory so the full booking flow is demoable end-to-end. Real deployments
swap this for an adapter backed by the hospital's actual scheduling API.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

from bonbon_patient_kiosk.models.appointment_models import AvailabilitySlot, Department, Doctor


class SchedulingAdapter(ABC):
    @abstractmethod
    def list_departments(self) -> list[Department]: ...

    @abstractmethod
    def list_doctors(self, department_id: str | None = None) -> list[Doctor]: ...

    @abstractmethod
    def list_available_slots(self, doctor_id: str) -> list[AvailabilitySlot]: ...

    @abstractmethod
    def reserve_slot(self, slot_id: str) -> AvailabilitySlot | None: ...

    @abstractmethod
    def release_slot(self, slot_id: str) -> None: ...

    @abstractmethod
    def get_slot(self, slot_id: str) -> AvailabilitySlot | None: ...

    @abstractmethod
    def get_department(self, department_id: str) -> Department | None: ...

    @abstractmethod
    def get_doctor(self, doctor_id: str) -> Doctor | None: ...


class MockSchedulingAdapter(SchedulingAdapter):
    def __init__(self) -> None:
        self._departments = [
            Department(
                department_id="dept-cardio",
                name="Cardiology",
                floor="2",
                named_location="cardiology_dept",
                description="Heart and cardiovascular care.",
            ),
            Department(
                department_id="dept-ortho",
                name="Orthopaedics",
                floor="3",
                named_location="orthopaedics_dept",
                description="Bones, joints, and muscles.",
            ),
            Department(
                department_id="dept-peds",
                name="Paediatrics",
                floor="1",
                named_location="paediatrics_dept",
                description="Care for infants, children, and adolescents.",
            ),
            Department(
                department_id="dept-gp",
                name="General Practice",
                floor="1",
                named_location="general_practice_dept",
                description="Walk-in and general consultations.",
            ),
        ]
        self._doctors = [
            Doctor(
                doctor_id="doc-tan",
                display_name="Dr. Tan Wei Ling",
                department_id="dept-cardio",
                named_location="dr_tan_room_204",
                languages=["en", "zh"],
            ),
            Doctor(
                doctor_id="doc-lim",
                display_name="Dr. Lim Kok Seng",
                department_id="dept-ortho",
                named_location="dr_lim_room_305",
                languages=["en", "ms"],
            ),
            Doctor(
                doctor_id="doc-nair",
                display_name="Dr. Priya Nair",
                department_id="dept-peds",
                named_location="dr_nair_room_112",
                languages=["en", "ta"],
            ),
            Doctor(
                doctor_id="doc-goh",
                display_name="Dr. Goh Hui Min",
                department_id="dept-gp",
                named_location="dr_goh_room_101",
                languages=["en", "zh"],
            ),
        ]
        self._slots: dict[str, AvailabilitySlot] = {}
        self._seed_slots()

    def _seed_slots(self) -> None:
        now = time.time()
        for doctor in self._doctors:
            for i in range(6):
                slot = AvailabilitySlot(
                    slot_id=str(uuid.uuid4()),
                    doctor_id=doctor.doctor_id,
                    start_ts=now + (i + 1) * 1800,
                    end_ts=now + (i + 1) * 1800 + 1500,
                    is_available=True,
                )
                self._slots[slot.slot_id] = slot

    def list_departments(self) -> list[Department]:
        return list(self._departments)

    def list_doctors(self, department_id: str | None = None) -> list[Doctor]:
        if department_id is None:
            return list(self._doctors)
        return [d for d in self._doctors if d.department_id == department_id]

    def list_available_slots(self, doctor_id: str) -> list[AvailabilitySlot]:
        return [
            s for s in self._slots.values() if s.doctor_id == doctor_id and s.is_available
        ]

    def reserve_slot(self, slot_id: str) -> AvailabilitySlot | None:
        slot = self._slots.get(slot_id)
        if slot is None or not slot.is_available:
            return None
        slot.is_available = False
        return slot

    def release_slot(self, slot_id: str) -> None:
        slot = self._slots.get(slot_id)
        if slot is not None:
            slot.is_available = True

    def get_department(self, department_id: str) -> Department | None:
        return next((d for d in self._departments if d.department_id == department_id), None)

    def get_doctor(self, doctor_id: str) -> Doctor | None:
        return next((d for d in self._doctors if d.doctor_id == doctor_id), None)

    def get_slot(self, slot_id: str) -> AvailabilitySlot | None:
        """Look up a slot regardless of availability -- used by the staff
        dashboard to show an already-booked appointment's scheduled time."""
        return self._slots.get(slot_id)
