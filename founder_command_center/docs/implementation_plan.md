# Implementation Plan

## MVP

1. Ship FastAPI backend with schema, RBAC foundation, seed data, dashboards, reports, agent specs, and CRUD endpoints.
2. Ship React dashboard for founder, employee tasks, leads, influencers, student clubs, products, agents, and reports.
3. Add CSV import/export for leads, influencers, and student club members.
4. Add tests for orchestration, recommendations, and CSV output.
5. Run locally with SQLite, then switch to PostgreSQL using `DATABASE_URL`.

## Next Expansion

1. Add Alembic migrations and migration CI.
2. Add Celery or Redis Queue scheduled daily/evening/weekly reports.
3. Add Gmail and Google Calendar integrations with human approval for sends.
4. Add pgvector/Qdrant memory for agent notes, documents, and decision history.
5. Expand robotics, agri, events, agreement generator, and political intelligence screens.
6. Add dedupe jobs and consent workflows managed by the Data, CRM and Compliance Agent.
7. Add role-specific dashboards and user management.
