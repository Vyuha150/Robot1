# AI Founder Command Center

An MVP command center for J V Kalyan that behaves like a digital organization of AI employees. It includes structured databases, dashboards, task planning, lead/influencer/student workflows, agent orchestration, reports, CSV import/export, audit logs, and role-based access foundations.

## Architecture

- Frontend: React + Vite + TypeScript
- Backend: FastAPI + SQLAlchemy + Pydantic
- Database: PostgreSQL in production, SQLite for local quickstart
- Agent orchestration: LangGraph-style coordinator with typed agent specs and recommendations
- Auth: JWT-ready role-based access control
- Automations: daily and weekly report generation endpoints, with scheduler hooks
- Compliance: consent tracking, audit logs, human approval flags for legal, mass outreach, and political content

## Project Structure

```text
founder_command_center/
  backend/
    app/
      agents/          # 14 AI employee specs and orchestration
      api/             # FastAPI routers
      core/            # config, auth, database
      models/          # SQLAlchemy database schema
      schemas/         # Pydantic API schemas
      services/        # reports, CSV, dashboards, seed data
      main.py
    migrations/        # SQL migration baseline
    tests/
  frontend/
    src/
      components/
      data/
      App.tsx
      styles.css
  docs/
    architecture.md
    implementation_plan.md
    roadmap.md
```

## Quickstart

Backend:

```bash
cd founder_command_center/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8088
```

Frontend:

```bash
cd founder_command_center/frontend
npm install
npm run dev -- --port 5178
```

Open `http://localhost:5178`. The frontend expects the API at `http://localhost:8088`.

## Environment

Create `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg://founder:founder@localhost:5432/founder_command_center
SECRET_KEY=replace-me
ACCESS_TOKEN_EXPIRE_MINUTES=720
```

If `DATABASE_URL` is omitted, the backend uses local SQLite at `founder_command_center.db`.

## MVP Scope

Implemented in this scaffold:

- Founder dashboard
- Employee task manager
- Lead manager
- Influencer database
- Student club database
- Product database
- Basic agent orchestration
- Daily and weekly report generators
- CSV import/export service
- RBAC dependency layer
- Audit log table and event helper
- Seed data
- Tests for agents, reports, and CSV validation

Advanced modules are represented in schema and agent definitions so they can be expanded without changing the foundation.
