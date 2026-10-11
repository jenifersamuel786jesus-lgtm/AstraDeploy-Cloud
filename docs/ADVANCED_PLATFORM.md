# Advanced platform phase

This phase adds the persisted API foundation for the advanced AstraDeploy platform.

## Available API groups

All routes are workspace-scoped and require a bearer token:

- `/api/workspaces/{id}/providers` — AWS/Azure/GCP connection metadata and disconnected status
- `/api/workspaces/{id}/provisioning-plans` — reviewed plan-only records
- `/api/workspaces/{id}/workloads/{workload_id}/provisioning-plans` — deterministic Terraform-like plan generation
- `/api/workspaces/{id}/deployments` — deployment status records
- `/api/workspaces/{id}/monitoring` and `/metrics` — source-labelled metric observations
- `/api/workspaces/{id}/cost-observations` — source-labelled cost observations
- `/api/workspaces/{id}/alerts` — alert and incident foundation
- `/api/workspaces/{id}/audit-logs` — security-sensitive workspace actions
- `/api/workspaces/{id}/experiments` — experiment metadata and dataset references
- `/api/workspaces/{id}/models` — model version and lifecycle metadata
- `/api/workspaces/{id}/pipelines` — pipeline definitions, disabled by default

## Safety boundaries

- Provider connection records do not store raw credentials.
- Provider status is `disconnected` until a secure provider connector is configured.
- Terraform output is plan-only and has `apply_allowed: false`.
- Monitoring and cost records are shown only when explicitly recorded with a source.
- Synthetic datasets and ML evaluation results are not invented by the API.
- Pipelines are disabled by default.

## Migrations

```bash
cd backend
alembic -c alembic.ini upgrade head
```

The application still calls `create_all` for backwards-compatible startup of the existing MVP database. Production PostgreSQL should use the Alembic migration command during release deployment.
