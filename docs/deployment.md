# ChargePlus — Production Deployment Runbook

## 1. System Architecture Overview

ChargePlus operates on a decoupled production architecture:
1. **Frontend & Serverless APIs (Vercel)**: Next.js 16 (React 19) serving the UI, station discovery, MapLibre tiles, weather integration, and OLAP analytics queries.
2. **Database & Identity Platform (Supabase)**: Managed PostgreSQL hosting the `public` relational schema, the `analytics` Kimball dimensional star schema, the `ml` model registry, and GoTrue Auth (Phone/Email OTP).
3. **ML Online Inference Service (External Python Container)**: FastAPI microservice (`backend/ml/service.py`) serving live busy-time inference from approved models.
4. **Scheduled ETL & Warehouse Processing (GitHub Actions)**: Containerized workflow (`.github/workflows/scheduled_ingestion.yml`) running multi-source ingestion (OpenChargeMap, OSM, DataGovIn), deduplication, and warehouse roll-ups every 6 hours.

---

## 2. Service Separation & Responsibilities

| Subsystem | Host / Platform | Scaling Mode | Database Access Mode |
| :--- | :--- | :--- | :--- |
| **Next.js Web & UI** | Vercel CDN | Edge / Global Cache | None (Static / Client SSR) |
| **Station Discovery Feed** | Vercel Serverless | Ephemeral Lambdas | HTTPS PostgREST (`@supabase/supabase-js`) |
| **OLAP Analytics (`/api/intelligence/olap`)** | Vercel Serverless | Ephemeral Lambdas | TCP to Supavisor Pooler (`:6543` Transaction Mode) |
| **ML Status & Governance** | Vercel Serverless | Ephemeral Lambdas | TCP to Supavisor Pooler (`:6543` Transaction Mode) |
| **ML Inference (`/api/ml/predict`)** | Vercel Serverless -> Python | Ephemeral Gateway | HTTP Proxy to Python Service (`PYTHON_API_URL`) |
| **Python ML Engine** | Railway / Modal / Docker | Dedicated Process | Read-only to Model Artifacts & ML Registry |
| **ETL & Data Warehouse Pipeline** | GitHub Actions | Scheduled Cron (Every 6h) | Privileged TCP (`DATABASE_URL` + Service Role) |

> [!IMPORTANT]
> **Supabase is hosted by Supabase Cloud, NOT by Vercel.** Vercel serverless functions connect to Supabase via HTTPS (PostgREST) and TCP (Supavisor port 6543). Never attempt to run PostgreSQL or database migrations inside Vercel build steps.

---

## 3. Environment Variables by Platform

### A. Vercel (Project Settings -> Environment Variables)

| Variable | Required | Exposure | Description |
| :--- | :--- | :--- | :--- |
| `NEXT_PUBLIC_DEMO_MODE` | **Yes** | Public (Client) | Set strictly to `"false"` in production. |
| `NEXT_PUBLIC_SUPABASE_URL` | **Yes** | Public (Client) | Supabase project URL (e.g. `https://[ref].supabase.co`). |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **Yes** | Public (Client) | Public anonymous key governed by PostgreSQL RLS. |
| `DATABASE_URL` | **Yes** | Server-Only | Supabase **Transaction Pooler** string (port `6543`). |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes** | Server-Only | Privileged key used solely by `/api/admin/warehouse` after user role verification. |
| `PYTHON_API_URL` | Optional | Server-Only | URL of the deployed Python ML service (e.g. `https://ml.chargeplus.app`). |
| `PYTHON_API_SECRET` | Optional | Server-Only | Shared Bearer token matching the Python service's `INTERNAL_SERVICE_SECRET`. |

### B. Python ML Microservice (e.g. Railway / Render / Fly.io / AWS ECS)

| Variable | Required | Exposure | Description |
| :--- | :--- | :--- | :--- |
| `PORT` | **Yes** | Server | Port to bind (defaults to `8000`). |
| `INTERNAL_SERVICE_SECRET` | **Yes** | Secret | Shared Bearer secret verifying requests from Next.js. |
| `ML_ARTIFACT_DIR` | **Yes** | Secret | Path to registry root (e.g. `backend/ml/artifacts`). |
| `DATABASE_URL` | Optional | Secret | For recording evaluation lineage into `ml.*`. |

### C. GitHub Actions (Repository Settings -> Secrets & Variables -> Actions)

| Variable / Secret | Type | Description |
| :--- | :--- | :--- |
| `STAGING_DATABASE_URL` | Secret | Direct or session pooler URL for ingestion writes. |
| `STAGING_SUPABASE_SERVICE_ROLE_KEY` | Secret | Service role key for bypass RLS ingestion persistence. |
| `STAGING_OPENCHARGEMAP_API_KEY` | Secret | API key for fetching OpenChargeMap stations. |
| `ALLOW_STAGING_WRITES` | Variable | Set to `"true"` to enable writing ingested records to the database. |
| `SCHEDULED_INGESTION_DRY_RUN` | Variable | Set to `"false"` for persistent ingestion runs (defaults to `true`). |

---

## 4. Step-by-Step Deployment Instructions

### Phase 1: Supabase Configuration
1. Log in to the [Supabase Dashboard](https://supabase.com/dashboard).
2. Go to **Project Settings -> Database -> Connection Pooling**:
   - Ensure the connection pooler is active.
   - Select **Mode: Transaction** and port **6543**.
   - Copy the URI for use as `DATABASE_URL`.
3. Go to **Authentication -> URL Configuration**:
   - Add your production Vercel domain to **Site URL** (e.g. `https://chargeplus.app`).
   - Add `https://chargeplus.app/**` to **Redirect URLs**.
4. Go to **Authentication -> Providers**:
   - Verify Phone (SMS) or Email OTP provider is active.

### Phase 2: Deploy Next.js to Vercel
1. In Vercel, click **Add New -> Project** and select `harshada2576/ChargePlus`.
2. Select **Framework Preset: Next.js**.
3. In **Environment Variables**, add the 5 core variables from Section 3.A.
4. Click **Deploy**.
5. Once deployment finishes, verify that `/api/health` returns:
   ```json
   { "ok": true, "status": "healthy", "mode": "production", "database": "connected" }
   ```

### Phase 3: Deploy Python ML Microservice (Optional / When ML Models Are Ready)
1. Deploy `backend/ml/service.py` to your container provider (Railway, Render, AWS App Runner).
2. Start command:
   ```bash
   uvicorn backend.ml.service:app --host 0.0.0.0 --port 8000
   ```
3. Set `INTERNAL_SERVICE_SECRET` in the Python container environment.
4. Back in Vercel, set `PYTHON_API_URL` to your container's HTTPS URL and `PYTHON_API_SECRET` to the matching secret.
5. Redeploy or restart Vercel functions to pick up the new variables.

### Phase 4: Activate Scheduled Ingestion
1. In GitHub Repository Settings -> Secrets and variables -> Actions:
   - Configure `STAGING_DATABASE_URL` and `STAGING_OPENCHARGEMAP_API_KEY`.
2. Under Variables, set `ALLOW_STAGING_WRITES="true"` and `SCHEDULED_INGESTION_DRY_RUN="false"`.
3. Go to **Actions -> Scheduled Ingestion & Warehouse Pipeline** and run a manual test with `dry_run=true` first.
4. Once verified, enable the scheduled cron trigger.

---

## 5. ML Governance & Data Maturity Rules

The production database enforces strict fail-closed data maturity gates (`backend/ml/gates.py`):
- Minimum **10,000 real observations**
- Minimum **20 distinct stations** with observations
- Minimum **14 observation days covered**
- Maximum feature staleness: **48 hours**

Until scheduled ingestion accumulates sufficient real hardware telemetry:
1. `GET /api/ml/status` reports `{ "state": "COLD", "available": false }`.
2. `POST /api/ml/predict` returns `{ "success": false, "reason": "NO_MODEL" }` (HTTP 200/503).
3. **Station discovery, search, filtering, map rendering, and OLAP analytics remain 100% operational.**
4. No synthetic predictions or fake confidence values are ever served in production.

---

## 6. Post-Deployment Verification Smoke Tests

Run these checks against your live production domain:

```bash
# 1. Health Probe
curl -i https://your-domain.vercel.app/api/health
# Expected: 200 OK, {"ok":true,"status":"healthy","database":"connected"}

# 2. Station PostgREST Feed
curl -i "https://your-domain.vercel.app/api/stations?limit=3"
# Expected: 200 OK, JSON array with valid station objects

# 3. OLAP Roll-up Operation
curl -i "https://your-domain.vercel.app/api/intelligence/olap?op=rollup&mode=weekly"
# Expected: 200 OK, JSON object with dimensions and facts from analytics schema

# 4. ML Status Probe
curl -i https://your-domain.vercel.app/api/ml/status
# Expected: 200 OK, {"ok":true,"state":"COLD",...}

# 5. Weather Cache Probe
curl -i "https://your-domain.vercel.app/api/weather?lat=19.076&lng=72.877"
# Expected: 200 OK, cached weather object
```

---

## 7. Rollback Considerations

- **Vercel Rollback**: Instant one-click rollback in Vercel Dashboard -> Deployments -> Instant Rollback.
- **Database Safety**: Application deployments make zero DDL schema mutations. A frontend rollback requires no database rollback.
- **Fail-Closed Design**: If the Python inference service experiences downtime, Next.js catches the connection error and serves standard station details without interrupting user browsing.
