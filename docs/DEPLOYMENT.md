# AryaOS V1 — Production Deployment Guide & Operational Runbook

## Overview

AryaOS V1 is an agentic AI content production factory designed for deterministic, durable, multi-tenant video generation and publishing. This document outlines production requirements, configuration parameters, deployment steps, and operational guarantees.

---

## 1. Environment & Architecture Requirements

### 1.1 Python & Node Runtime
- **Backend:** Python 3.12+ managed via `uv` or containerized runtime.
- **Frontend:** Node.js 20+ with npm for building the Vite/React static assets.

### 1.2 PostgreSQL Requirements & Primary Read-After-Write Consistency
- **PostgreSQL Version:** PostgreSQL 15+ (PostgreSQL 16 recommended).
- **CRITICAL COORDINATION REQUIREMENT:**
  AryaOS V1 uses PostgreSQL ACID transactions and explicit row-level locking (`SELECT ... FOR UPDATE`) as its **sole distributed coordination authority** for:
  - Workflow execution lease acquisition and heartbeats (`claim_execution_lease`, `update_heartbeat`)
  - Approval checkpoint decisions (`decide_approval`)
  - Publishing deduplication (`publish_video`)
  - Auto-recovery lease fencing (`auto_recover_stale_workflow_runs`)
- **Primary / Read-After-Write Invariant:**
  In high-availability or clustered database environments (e.g. AWS Aurora, Cloud SQL with read replicas, Patroni):
  - **All API worker connections MUST connect directly to the primary (read-write) database node.**
  - Under no circumstances should workflow execution or approval queries be routed to asynchronous read replicas where replication lag could cause split-brain lease acquisition or stale approval reads.
- **Connection Pool Sizing:**
  - Recommended `DB_POOL_SIZE`: 20–50 connections per instance.
  - Recommended `DB_MAX_OVERFLOW`: 10–20 connections.
  - Recommended `DB_POOL_RECYCLE`: 1800 seconds (30 minutes).

---

## 2. Configuration & Environment Variables

### 2.1 Required Production Secrets
When `APP_ENV=production`, the application performs strict configuration validation on startup and will refuse to boot if default development placeholders or weak keys are detected.

| Variable | Description | Validation Rule in Production |
| :--- | :--- | :--- |
| `APP_ENV` | Application environment mode | Set to `production` |
| `ARYA_API_KEY` | Master system authentication key | Must be set, ≥ 16 characters, cannot be default placeholder |
| `DATABASE_URL` | Async PostgreSQL connection string | Must be valid asyncpg format; cannot contain `change_me` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed origins | Must be explicit origins; wildcard `*` with credentials is strictly forbidden |
| `CORS_ALLOW_CREDENTIALS` | Enable credentials header in CORS | `true` |

### 2.2 Provider Credentials (Optional / As Needed)
External provider credentials activate their respective cloud generators. If an API key is absent, the system falls back gracefully to synthetic or local generators where supported, or raises a clear, non-corrupting error.

| Provider | Environment Variable | Capabilities | Fallback Behavior when Unset |
| :--- | :--- | :--- | :--- |
| **OpenRouter** | `OPENROUTER_API_KEY` | Script, story evaluation, trends | Local deterministic linguistic heuristics & rules |
| **Kling / Replicate**| `REPLICATE_API_KEY` | Video generation | Fallback to mock video or secondary video provider |
| **ElevenLabs** | `ELEVENLABS_API_KEY` | Voice TTS & Sound effects | Fallback to silence generator or secondary TTS provider |
| **Postiz** | `POSTIZ_API_KEY`, `POSTIZ_BASE_URL` | Multi-platform publishing | Rejects publishing task with clear configuration error |
| **YouTube** | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | YouTube OAuth publishing | Rejects upload with explicit auth failure message |
| **Reddit** | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | Trend research | Internal mock trend discovery / synthetic trends |

### 2.3 Workflow Lease & Heartbeat Settings
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `WORKFLOW_LEASE_TIMEOUT_SECONDS` | `300` (5 min) | Time after which a missing worker heartbeat marks a lease stale |
| `WORKFLOW_HEARTBEAT_INTERVAL_SECONDS` | `15` | Frequency of background worker lease heartbeats |
| `ENABLE_WORKFLOW_AUTO_RECOVERY` | `false` | Enable automatic recovery sweep of stale leases by background scheduler |

---

## 3. Database Migration Procedure

AryaOS V1 uses Alembic with linear, reversible transactional migrations.

### Apply Migrations
```bash
# Verify current revision
uv run alembic current

# Upgrade to latest head
uv run alembic upgrade head
```

### Rollback (if required)
```bash
# Rollback one migration step
uv run alembic downgrade -1

# Rollback to specific revision
uv run alembic downgrade d4e5f6a7b8c9
```

---

## 4. Application Startup & Shutdown Procedure

### 4.1 Production Startup
AryaOS V1 runs with a single process or multi-process deployment. Because internal maintenance tasks (lease sweep, scheduler) run in-process, single worker per pod/container is standard:

```bash
uv run uvicorn app.main:app \
  --app-dir backend \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --timeout-keep-alive 65 \
  --timeout-graceful-shutdown 60
```

### 4.2 Frontend Static Assets
Build the production frontend bundle:
```bash
cd frontend
npm ci
npm run build
```
The compiled output is located in `frontend/dist` and can be served via Nginx, Cloudflare Pages, AWS S3/CloudFront, or mounted to the backend.

### 4.3 Safe Graceful Shutdown
Upon receiving `SIGTERM` or `SIGINT`:
1. Uvicorn stops accepting new HTTP connections.
2. In-flight workflow execution tasks are given up to `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` (60s) to complete their current stage.
3. If interrupted before stage completion, the execution service cleanly releases the worker lease without corrupting database state or falsely marking the run failed.
4. Database connection pools and background schedulers are cleanly closed.

---

## 5. Health Check & Monitoring Probes

AryaOS V1 provides tiered health endpoints for Kubernetes, Docker Swarm, and cloud load balancers:

### 5.1 Liveness Probe (`GET /live`)
- **Path:** `/live`
- **Purpose:** Fast container liveness check.
- **Behavior:** Decoupled from all external dependencies (database, Redis, storage). Always returns `200 OK` as long as the FastAPI event loop is responsive.
- **Kubernetes Config:**
  ```yaml
  livenessProbe:
    httpGet:
      path: /live
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
  ```

### 5.2 Readiness Probe (`GET /ready`)
- **Path:** `/ready`
- **Purpose:** Deep dependency readiness verification.
- **Behavior:**
  - Tests database connectivity with a live query (`SELECT 1`).
  - Tests local/configured storage path writeability.
  - Returns `200 OK` if all dependencies are operational; returns `503 Service Unavailable` if the database is unreachable or storage is read-only.
- **Kubernetes Config:**
  ```yaml
  readinessProbe:
    httpGet:
      path: /ready
      port: 8000
    initialDelaySeconds: 10
    periodSeconds: 15
  ```

### 5.3 Diagnostic Health Endpoint (`GET /health`)
- **Path:** `/health`
- **Purpose:** Detailed diagnostic reporting including database latency, Redis status, and storage availability.

---

## 6. Observability & Request Tracing

- **Request Correlation:** Every incoming HTTP request is assigned a unique `X-Request-ID` (or adopts the client's `X-Request-ID`).
- **Response Headers:** The correlation ID is reflected back in the `X-Request-ID` HTTP response header.
- **Structured Logs:** All log events emitted by `structlog` include the `request_id`, principal name, and workflow identifiers.
- **Exception Sanitization:** Unhandled 500 errors in production are masked with a sanitized error message and correlation ID, preventing internal tracebacks from leaking to API consumers.

---

## 7. Backup & Recovery Considerations

1. **Database Backups:** Perform regular PostgreSQL WAL archiving and automated daily snapshots (`pg_dump` or cloud managed automated backups).
2. **Media Storage:** Back up `./data/storage` (or configured S3/R2 bucket). Generated videos, scripts, and storyboard assets can be retrieved directly via workflow lineage.
3. **Lease Recovery:** If a node crashes mid-execution, the orphaned workflow run will be identified as stale once its heartbeat exceeds `WORKFLOW_LEASE_TIMEOUT_SECONDS`. An operator can call `POST /workflow-runs/{id}/recover` to resume execution from the last persisted stage.
