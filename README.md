# AstraDeploy Cloud

A free-only, plan-first cloud workload intelligence MVP. It provides real FastAPI APIs, PostgreSQL persistence, JWT authentication, workspace isolation, workload CRUD, deterministic resource recommendations, and transparent cost estimates. Cloud provisioning and telemetry integrations are intentionally disconnected until credentials and explicit approval exist.

## Run locally with Docker

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:5173 and register a user. API docs: http://localhost:8000/docs.

## Run without Docker (backend tests)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=sqlite:///./astradeploy_test.db pytest -q
uvicorn app.main:app --reload
```

For production, set `DATABASE_URL` to PostgreSQL, use a random `JWT_SECRET`, and set `CORS_ORIGINS` to the deployed frontend origin. Never commit secrets. The default application only estimates costs from user-provided assumptions; it does not create cloud resources or claim live telemetry.

## Current scope

Implemented: registration/login, workspace creation and membership, tenant-safe workload CRUD, recommendation rules, cost estimates, API validation, audit events, responsive dashboard, Docker Compose, and tests. Planned: provider read-only adapters, Terraform plan workflow, monitoring ingestion, MLflow registry, and deployment-specific configuration.
