# ChargePlus — Offline Demo Experience & Local Database Setup

**Document Version**: 1.0.0  
**Phase**: Phase 3 / Reproducible Offline Demo  
**Date**: October 12, 2026  

---

## 1. Developer Setup Options

ChargePlus supports two primary developer workflows:
1. **Zero-Cloud Offline Demo Mode**: Run the interactive Next.js application immediately with no remote accounts or external database dependencies using verified local seed fixtures (`NEXT_PUBLIC_DEMO_MODE="true"`).
2. **Local PostgreSQL/PostGIS Environment**: Run full end-to-end operational and analytical pipelines locally against a local PostgreSQL instance (Docker or native Postgres with PostGIS).

---

## 2. Quickstart: Zero-Cloud Offline Demo

For rapid frontend exploration, UI review, and offline evaluation:

```bash
# 1. Clone repository
git clone <repo-url>
cd ChargePlus

# 2. Install Node dependencies
npm install

# 3. Configure environment for Demo Mode
cp .env.example .env.local
```

In `.env.local`, set:
```ini
NEXT_PUBLIC_DEMO_MODE="true"
```

Start the application:
```bash
npm run dev
```

Navigate to `http://localhost:3000/explore`:
- The header displays a visible **DEMO MODE** status badge.
- Station discovery populates with 12 canonical Mumbai charging hubs (BKC, Andheri, Powai, Lower Parel, etc.).
- Telemetry indicators honestly indicate **Simulated Demo Data** without projecting false real-time claims.

---

## 3. Local PostgreSQL + PostGIS Setup (Docker)

To run the complete OLTP, ETL, and warehouse stack locally without a Supabase cloud account:

### 1. Launch Local PostGIS Container
```bash
docker run --name chargeplus-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=chargeplus -p 5432:5432 -d postgis/postgis:16-3.4-alpine
```

### 2. Configure Local Database URL
In `.env.local`:
```ini
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/chargeplus"
```

### 3. Apply Authoritative SQL Migrations
Apply all 14 sequential migrations from `supabase/migrations/`:
```bash
python backend/warehouse/migrate.py
```

### 4. Idempotent Seed Execution
Seed the canonical Mumbai stations, connectors, and initial observations:
```bash
python backend/ingestion/seed_demo_db.py
```

*Safety Verification*: The seeder invokes `require_disposable_target(DATABASE_URL)`. Loopback targets (`localhost`, `127.0.0.1`) pass automatically. Non-loopback production targets without explicit disposable flags are refused.

---

## 4. Production vs Demo Isolation Guarantees

| Invariant | Production Mode (`NEXT_PUBLIC_DEMO_MODE="false"`) | Demo Mode (`NEXT_PUBLIC_DEMO_MODE="true"`) |
| :--- | :--- | :--- |
| **Missing DB / Supabase** | Fails closed with descriptive exception (`Supabase client not configured`) | Loads version-controlled canonical seed fixtures |
| **Data Labeling** | Real provider and observation timestamps | All records labeled with `isSimulated: true` and `sourceCategory: "simulated"` |
| **UI Indicator** | Standard brand header | Visible amber **DEMO MODE** pulse pill badge |
| **SMS / Auth** | Strict Supabase SMS / Email provider | Controlled local test accounts simulator |
| **Automatic Fallback** | ❌ **PROHIBITED**: Never falls back to synthetic data automatically | Explicit developer opt-in only |

---

## 5. Health Check & Diagnostics

Check operational health at:
```bash
curl http://localhost:3000/api/health
```

- When database is healthy:
  ```json
  { "ok": true, "status": "healthy", "mode": "demo", "database": "connected" }
  ```
- When database connection fails or is unconfigured:
  HTTP 503 Service Unavailable:
  ```json
  { "ok": false, "status": "unhealthy", "mode": "production", "database": "disconnected", "error": "Database unreachable or DATABASE_URL unconfigured" }
  ```
