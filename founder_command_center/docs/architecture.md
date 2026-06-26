# Architecture

The MVP is organized as a modular command center rather than a chatbot.

## Backend Layers

- `models`: PostgreSQL-ready tables for people, employees, tasks, products, leads, influencers, student clubs, events, political profiles, agri opportunities, users, and audit logs.
- `schemas`: Pydantic request/response contracts.
- `api`: FastAPI routes for dashboards, agents, reports, CRUD workflows, CSV import/export, seed data, and auth.
- `agents`: deterministic MVP orchestration with 14 agent definitions. The Chief of Staff coordinates handoffs and every recommendation includes reasoning, owner, deadline, expected outcome, and risk level.
- `services`: dashboards, report generation, CSV import/export, seed data, and reusable CRUD helpers.

## Frontend

React renders an operational dashboard with tabs for founder overview, tasks, leads, influencers, student clubs, products, agents, and reports. It avoids a marketing landing page and opens directly into the work surface.

## Compliance

The schema tracks consent, source, agreement status, audit logs, and human approval requirements. Political tooling is constrained to ethical consulting, office workflows, public issue research, volunteer coordination, grievance systems, and lawful communication.

## Future Integrations

The API boundaries are ready for Gmail, Google Calendar, Google Sheets, WhatsApp Business API, Notion/Airtable, approved social media APIs, pgvector/Qdrant, Redis Queue/Celery, and external opportunity monitoring.
