# hospital_kb

Sample hospital knowledge base for this deployment — replaces the café's
seeded menu/tables/locations documents in `bonbon_llm`'s RAG retriever with
hospital-specific content: departments, doctor directory, policies, FAQ,
and emergency guidance.

These are markdown files, not code — edit them directly for a real
deployment (real department list, real doctor roster with on-duty
schedule, real visiting-hours/insurance policy).

## Loading into bonbon_llm's RAG

`bonbon_llm`'s `RAGRetriever` is seeded with its own default (café)
documents at startup and exposes `add_document(text, metadata)` for adding
more at runtime (see `bonbon_llm/README.md`, "Add knowledge documents at
runtime"). This package does not import `bonbon_llm` directly — instead,
run `scripts/seed_hospital_kb.py` once against a running `bonbon_llm`
process (or call the same `add_document` calls from your own deployment
tooling) so the two packages stay decoupled.

```bash
python ros2_ws/src/bonbon_patient_kiosk/scripts/seed_hospital_kb.py
```

This intentionally does **not** run automatically on kiosk API startup —
seeding the shared knowledge base is a deployment-time step, not something
the patient-facing process should be able to trigger repeatedly.
