# BonBon Patient Kiosk Frontend

Vite + React + TypeScript touchscreen UI for patients checking in at
hospital reception. Runs on `http://localhost:3100` and talks to the
`bonbon_patient_kiosk` FastAPI backend on `http://127.0.0.1:8090` by default.

Separate from `bonbon_operator_api/frontend` (the staff test cockpit) —
this app has no camera/mic testbench, no diagnostics, and no operator
authentication for the patient-facing flow. It does have a small
staff-only area (`/staff/login`, `/staff/facility-map`) gated by the same
JWT auth the backend enforces server-side.

## Screens

Welcome → Language → Consent → (Patient lookup) → Intake form → Next
steps → **Book appointment** or **Check in (queue token)** or **Ask
BonBon** (chat + wayfinding) → Feedback.

Every patient screen is wrapped in `KioskShell`, which:
- shows a countdown warning and wipes the session on ~90s of inactivity
  (the core PHI safety control — the next patient never sees a prior
  patient's half-finished form),
- keeps an always-visible red "Call Staff" panic button on screen,
- exposes an accessibility toolbar (large text, high contrast, language).

## Quick start

```powershell
cd "C:\Users\venka\AI service robot\bonbon_robot_ai\ros2_ws\src\bonbon_patient_kiosk\frontend"
npm install
npm start
```

Open `http://localhost:3100`. Start the backend separately — see the
package [README](../README.md#running).

## Facility Map Editor

`/staff/login` → `/staff/facility-map` lets staff register room/doctor
pins (by map coordinate, read off `bonbon_navigation`'s map viewer/RViz)
and export a `named_locations` YAML block to paste into
`nav_params.yaml`. Export-only for this pass — see the package README's
"Known gap" / plan-decision notes.

## Kiosk deployment

For the physical touchscreen, run this build in a kiosk-mode browser —
see `devops/scripts/launch_patient_kiosk.sh` at the repo root, which waits
for the backend's `/health` endpoint before opening the browser.
