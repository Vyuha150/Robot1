from __future__ import annotations

from bonbon_patient_kiosk.models.patient_models import PatientLookupRequest


def test_mock_emr_adapter_lookup_hit_and_miss(emr_adapter):
    hit = emr_adapter.lookup(PatientLookupRequest(identifier="+6591234567", identifier_type="phone"))
    assert hit is not None
    assert hit.display_name == "Tan Wei Ming"

    miss = emr_adapter.lookup(PatientLookupRequest(identifier="no-such-id", identifier_type="phone"))
    assert miss is None


def test_mock_scheduling_adapter_reserve_and_release(scheduling_adapter):
    slots = scheduling_adapter.list_available_slots("doc-tan")
    assert len(slots) > 0
    slot_id = slots[0].slot_id

    reserved = scheduling_adapter.reserve_slot(slot_id)
    assert reserved is not None
    assert scheduling_adapter.reserve_slot(slot_id) is None  # can't double-book

    scheduling_adapter.release_slot(slot_id)
    assert scheduling_adapter.reserve_slot(slot_id) is not None


def test_mock_notifier_adapter_records_sends(notifier_adapter):
    notifier_adapter.send_token_sms("+6591112222", "A1", "Cardiology")
    notifier_adapter.print_token("A1", "Cardiology", 12.0)
    assert len(notifier_adapter.sent) == 2
