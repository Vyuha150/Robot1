# bonbon_patient_kiosk

Patient/customer-facing kiosk for the **BonBon** service robot's hospital
reception deployment. Separate from `bonbon_operator_api` (the staff-only
dashboard) — this package is what a patient actually taps on: check-in,
patient history intake, appointment booking, queue tokens, RAG-grounded
Q&A, and wayfinding/escort to a room or doctor. A staff-only Facility Map
Editor is also included for labeling rooms/doctors after a LiDAR scan.

---

## Why a separate package

`bonbon_operator_api` is an authenticated engineering/ops cockpit — camera
feeds, LLM test consoles, safety diagnostics. None of that belongs in
front of a patient. `bonbon_patient_kiosk` is the opposite: anonymous
session-scoped interaction for the public, a tiny staff-only slice
(check-in desk + admin), and PHI-aware storage the operator dashboard has
no reason to touch.

Both packages call the **same underlying safety-gated services**
(`/navigation/navigate_to`, `/llm/query`) — neither ever bypasses
`bonbon_safety` / `bonbon_navigation`'s own safety pipeline, and neither
publishes to `/cmd_vel` directly.

---

## What already exists elsewhere (not duplicated here)

| Capability | Owner |
|---|---|
| LiDAR SLAM / hospital-wide mapping | `bonbon_navigation` (`slam.launch.py` + RTAB-Map) |
| Named-location navigation, human-aware costmap, docking | `bonbon_navigation` |
| RAG-grounded LLM Q&A, hallucination guard | `bonbon_llm` |
| Central behavior dispatch / operator alerting | `bonbon_behavior_engine` |
| Face/voice privacy suppression | `bonbon_affective_ai` (`SetPrivacyMode`) |

This package seeds `bonbon_llm`'s RAG with hospital content (see
`hospital_kb/`) instead of the café defaults, and reads/writes its own
data — it does not fork or reimplement any of the above.

---

## Architecture

```
bonbon_patient_kiosk/
├── nodes/kiosk_api_node.py     ROS2 LifecycleNode hosting the FastAPI server
├── ros2/ros2_bridge.py         Only place this package talks to ROS2:
│                               /llm/query, /navigation/navigate_to,
│                               /bonbon/affective/set_privacy_mode,
│                               /bonbon/tts/request
├── safety/                     CommandValidator + KioskSafetyGate — every
│                               navigation/panic request is validated and
│                               audited before it reaches ROS2
├── audit/audit_logger.py       PHI-access audit trail (never stores raw PHI)
├── auth/                       Staff-only JWT auth (roles: staff, admin)
├── data/
│   ├── session_store.py        In-memory-only patient session + draft intake
│   ├── store.py                AES-256-GCM encrypted-at-rest submitted records
│   ├── facility_store.py       Facility Map Editor labels (export-only)
│   └── adapters/                EMR / Scheduling / Notifier interfaces + mocks
├── api/                        FastAPI routers (see below)
├── hospital_kb/                Sample hospital knowledge base for bonbon_llm's RAG
├── frontend/                   Vite + React + TypeScript kiosk UI
└── tests/
```

### API routers

| Router | Purpose |
|---|---|
| `session_api` | Create/heartbeat/end a patient session; engages privacy mode |
| `consent_api` | Data-use disclosure + consent recording |
| `patient_lookup_api` | Returning-patient lookup via `EMRAdapter` |
| `intake_api` | Draft save (in-memory) + confirmed submit; red-flag detection |
| `appointment_api` | Department/doctor directory, slots, book/reschedule/cancel |
| `queue_api` | Walk-in check-in → token issuance, live queue status |
| `chat_api` | RAG Q&A via `/llm/query`, non-diagnostic department suggestion |
| `navigation_api` | "Show directions" vs "please guide me" (escort) |
| `panic_api` | Always-available "call staff" button |
| `feedback_api` | End-of-visit CSAT |
| `facility_map_api` | Staff-only room/doctor pin editor + YAML export |
| `auth_api` | Staff login / user management |

---

## PHI safety model

- Draft intake data lives **only in memory** (`SessionStore`) until the
  patient explicitly confirms and submits — never written to disk before then.
- Submitted records are AES-256-GCM encrypted at rest (`data/crypto.py`);
  the key comes from `BONBON_KIOSK_DATA_KEY`, never hardcoded.
- Idle sessions (default 90s) and their drafts are purged automatically so
  the next patient never sees a prior patient's half-finished form.
- `chat_api` never sends PHI into `bonbon_llm`'s RAG context — only the
  patient's free-text question and the hospital directory/FAQ knowledge base.
- Red-flag symptom language (in intake or chat) skips the LLM entirely and
  triggers immediate staff escalation — never a diagnosis.
- Every PHI-adjacent action is audited (`audit/audit_logger.py`), recording
  *that* an action happened, never the PHI value itself.

## Facility Map Editor (export-only, this pass)

Staff place pins on the map image already produced by `bonbon_navigation`'s
SLAM pipeline and export a `named_locations` YAML block
(`GET /api/v1/facility-map/export`) to paste into
`bonbon_navigation/config/nav_params.yaml`, then relaunch. This package
never calls back into `bonbon_navigation` to mutate its location registry —
see the plan decision recorded when this package was created.

## Known gap inherited from bonbon_llm

`bonbon_llm`'s README documents `/llm/query` (`LLMQuery.srv`) as its
synchronous query service, but `llm_orchestrator_node` does not yet create
a server for it (confirmed: only referenced in `bonbon_llm`'s own test
mocks). `ros2_bridge.py`'s `wait_for_service` check will honestly report
"unavailable" until that server exists, and `chat_api.py` degrades to a
graceful fallback response rather than erroring — see the `NOTE` in
`ros2/ros2_bridge.py`.

---

## Running

```bash
cd ros2_ws && colcon build --packages-select bonbon_patient_kiosk
ros2 launch bonbon_patient_kiosk kiosk_api.launch.py
```

Standalone (no ROS2, mock adapters only):

```powershell
$env:BONBON_TEST_MODE = "1"
$env:BONBON_KIOSK_ADMIN_PASSWORD = "your-chosen-password"
python -m uvicorn bonbon_patient_kiosk.main:create_app --factory --port 8090
```

## Testing

```bash
cd ros2_ws/src/bonbon_patient_kiosk
python -m pytest tests/ -v
```

All tests stub ROS2 entirely (see `tests/conftest.py`) — no live ROS2
installation required.

## Frontend

See [`frontend/README.md`](frontend/README.md).
