# ChargePlus — Data Warehouse (Step 1.4, Step 1.6 & Step 1.7 Synthesis)

> Migration: `supabase/migrations/20260922000001_step_1_4_analytics_warehouse_schema.sql`  
> Synthesized Integrity & Indexes Migration: `supabase/migrations/20260923000001_step_1_6_constraints_indexes.sql`  
> RLS & Security Policies Migration: `supabase/migrations/20260924000001_step_1_7_rls_security_policies.sql`  
> Status: canonical warehouse documentation for the implemented Step 1.4 schema, Step 1.6 integrity synthesis, and Step 1.7 RLS isolation.  
> Constraints/indexes verified in Step 1.6; RLS enabled on all 12 warehouse tables with 0 client policies (Step 1.7 EXECUTED + VERIFIED against linked Supabase project).  
> Table inventory in `docs/data_dictionary.md`.

---

## 1. Operational DB vs Data Warehouse distinction

ChargePlus maintains a hard architectural boundary. The two layers must never
be confused:

| Aspect | Operational DB (OLTP) | Data Warehouse (OLAP) |
|---|---|---|
| Schema | `public` | `analytics` |
| Purpose | Current application/product state + operational history | Historical facts, conformed dimensions, aggregates, OLAP, future ML feature preparation |
| Writers | Frontend (Supabase API, under Step 1.7 RLS) + ingestion pipeline | **Python ETL jobs only. No frontend writes.** |
| Tables | `profiles, operators, stations, connectors, data_sources, station_source_link, station_observations, user_reports, reviews, favorites, alerts` (Step 1.3) | 8 dimensions + 4 facts (see §3) |
| Identity | Operational UUIDs (canonical frontend IDs) | Warehouse surrogate keys; operational UUIDs kept as business keys for ETL only |
| Reads | Product UI (map, search, detail, reports, reviews) | OLAP queries, dashboards, ML feature jobs |

Rules that follow from this:

- The whole Supabase/PostgreSQL database is **not** "the data warehouse".
  Only the `analytics` schema is the warehouse.
- `public` operational tables and `analytics` warehouse tables are never
  mixed: no cross-layer foreign keys (e.g. `analytics.station_key →
  public.stations.id` is forbidden), no cross-layer joins from the frontend.
- Three concepts are never combined:
  `stations.operational_status` (station facet: open/closed) ≠
  observation `availability_status` (point-in-time: free/busy now) ≠
  future predicted congestion (ML output, not a fact).

## 2. Schema ownership

| Schema | Owner / writer | Reader |
|---|---|---|
| `public` | App + ingestion pipeline (Step 1.3, RLS in 1.7) | Frontend, ETL (source) |
| `analytics` | **Python ETL only** (a later step; no ETL executes in 1.4) | OLAP consumers, future ML jobs (grants/RLS land in a later step; until then the Supabase anon/authenticated roles hold no privileges on this schema, which is the enforcement mechanism for "no frontend writes") |

There are intentionally no triggers that silently populate facts, no RLS in
this step, and no scheduled jobs. Step 1.4 is DDL + deterministic
date/time seeds only.

## 3. Table inventory

All objects live in `analytics` and are created by the Step 1.4 migration.
Nothing in `public` is created, altered, or seeded by this step.

**Dimensions (8):**

| Table | SCD | Rows after 1.4 |
|---|---|---|
| `analytics.dim_station` | Type 2 (versioned) | 0 (populated by ETL) |
| `analytics.dim_operator` | Type 1 | 0 (populated by ETL) |
| `analytics.dim_location` | Type 1 | 0 (populated by ETL) |
| `analytics.dim_connector` | Type 1 (initially) | 0 (populated by ETL) |
| `analytics.dim_date` | static | **3288** (seeded) |
| `analytics.dim_time` | static | **96** (seeded) |
| `analytics.dim_source` | Type 1 | 0 (populated by ETL) |
| `analytics.dim_weather` | Type 1 (placeholder) | 0 (no adapter yet) |

**Facts (4):**

| Table | Rows after 1.4 |
|---|---|
| `analytics.fact_station_observation` | 0 (append-only, ETL) |
| `analytics.fact_user_report` | 0 (append-only, ETL) |
| `analytics.fact_review` | 0 (append-only, ETL) |
| `analytics.fact_station_daily` | 0 (aggregate, ETL) |

**Deferred / out of scope** (do not create unless a locked requirement
demands it): `dim_user`, `dim_vehicle`, `dim_tariff`,
`fact_charging_session`, `fact_forecast`, `fact_station_hourly`.

## 4. Grain of every dimension

- `dim_station` — **one row per version of one physical station.**
  A new version opens on changes to name, operator, address/location,
  operational status, public/private status, opening/closing hours, or
  access attributes.
- `dim_operator` — **one row per operator.**
- `dim_location` — **one row per locality/location analytical entity**
  (`country, state, city, locality, postal_code`).
- `dim_connector` — **one row per operational connector** (static capacity
  group; business key = `connectors.id`).
- `dim_date` — **one row per calendar date**, 2024-01-01…2032-12-31.
  `date_key` = YYYYMMDD integer; ISO week, ISO day-of-week (1=Mon…7=Sun).
- `dim_time` — **one 15-minute slot per row, exactly 96 rows**
  (`00:00`…`23:45`, `time_key` 0…95). No second-level rows.
  `time_of_day`: morning 05:00–11:59, afternoon 12:00–16:59,
  evening 17:00–20:59, night otherwise.
- `dim_source` — **one row per data source** (feed registry mirror;
  lineage axis for facts).
- `dim_weather` — **one row per weather observation/condition
  representation.** Structural placeholder: no weather adapter or
  operational weather contract exists in Phase 1, so no rows are seeded
  and every fact `weather_key` is nullable (NULL = unknown, never "clear").

## 5. Grain of every fact

- `fact_station_observation` — **EXACT GRAIN: one row = one
  `public.station_observations` row.** Business key `observation_id =
  station_observations.id`; warehouse surrogate `observation_key`.
  Keys: `station_key`, nullable `connector_key`, `date_key`, `time_key`,
  `source_key`, nullable `weather_key`. Carries `observed_at`,
  `received_at`, `availability_status`, `queue_level`,
  `available/total_connectors`, `confidence_score`, `source_payload_hash`.
- `fact_user_report` — **EXACT GRAIN: one row = one APPROVED
  `public.user_reports` row.** Business key `report_id = user_reports.id`.
  `report_count = 1` always. Moderation audit without identities
  (`moderation_status` locked to `'approved'`, `moderated_at`,
  `is_flagged`); **no `user_id`, no comment text, no PII.**
- `fact_review` — **EXACT GRAIN: one row = one APPROVED `public.reviews`
  row.** Business key `review_id = reviews.id`. `rating` 1–5,
  `review_count = 1`, `created_at`. Analytically separate from
  availability/busy-state facts (experience quality ≠ busyness); no PII.
- `fact_station_daily` — **EXACT GRAIN: one row = one `station_key` ×
  `date_key` WITH evidence.** No-evidence days produce no row (missing =
  unknown). Primary daily OLAP table and future ML feature source.
  Holds evidence counts, status counts, ratios, queue scores, `avg_rating`,
  `data_completeness_score`, `source_count`, `maturity`, `has_evidence`.
  Session/energy/revenue measures are deliberately absent (§10).

## 6. SCD strategy

- `dim_station` — **SCD Type 2.** `effective_from / effective_to /
  is_current / version` with constraints: valid date range, current rows
  are open-ended, and a partial unique index guarantees **exactly one
  current version per `station_id`**. Step 1.6 adds composite index
  `idx_dim_station_effective (station_id, effective_from, effective_to)`
  enabling high-performance point-in-time version resolution by ETL.
  SCD2 range contiguity (`prev effective_to = next effective_from`) and
  monotonic version increment are strictly maintained as ETL invariants.
  Operating hours consistency mirrors `public.stations` via `chk_dim_station_hours`.
- All other core dimensions (`dim_operator`, `dim_location`,
  `dim_connector`, `dim_source`, `dim_weather`) — **SCD Type 1**:
  changes overwrite in place, no history kept. Step 1.6 enforces
  `chk_dim_connector_type` vocabulary parity on `dim_connector`.
- `dim_date` / `dim_time` — **static**, seeded once, never updated.
  Step 1.6 enforces deterministic surrogate-key self-consistency via
  `chk_dim_date_self_consistent` and `chk_dim_time_self_consistent` (using
  strictly immutable arithmetic/case logic).
- Facts — **append-only, idempotent by business key**
  (`UNIQUE` on the operational UUID). Reloads use the business key;
  no UPDATE-in-place semantics, no trigger-driven loads.

## 7. Business vs surrogate keys

- Every dimension has a **surrogate key** (`*_key`: `BIGINT` identity;
  `dim_date`: YYYYMMDD integer; `dim_time`: 0–95 smallint) used for all
  warehouse joins, including fact FKs.
- Every dimension also retains its **business key** (operational UUID or
  natural key: `station_id`, `operator_id`, `(country, state, city,
  locality, postal_code)`, `connector_id`, `source_id`) with uniqueness
  enforced, so ETL can map operational rows → warehouse rows
  deterministically.
- Facts carry both: their own surrogate (`observation_key`, `report_key`,
  `review_key`; `fact_station_daily` uses the composite PK
  `(station_key, date_key)`) **and** the operational business key
  (`observation_id`, `report_id`, `review_id`) with `UNIQUE` for
  idempotent loads.
- Operational UUIDs in the warehouse are **business keys for ETL only** —
  never exposed as frontend IDs; the frontend keeps using `public` UUIDs.

## 8. ETL boundary

```
public (OLTP, source of truth for current state)
  │  Python ETL (later step — NOT implemented in 1.4):
  │   extract operational rows → resolve business key → surrogate key
  │   (incl. dim_station SCD2 point-in-time version via idx_dim_station_effective)
  │   → conform date/time (UTC convention)
  ▼
analytics (OLAP: dims, facts, daily aggregates)
  │  future ML feature jobs read fact_station_daily + grains
  ▼
forecasts / recommendations (later phases; predictions never written back
as facts and never mixed with observed availability)
```

Conventions the ETL must follow (enforced where possible by DDL):

1. Load order: `dim_operator`, `dim_location` → `dim_station` →
   remaining dims → facts → `fact_station_daily`.
2. Only `approved` user reports / reviews enter facts
   (`CHECK (moderation_status = 'approved')` rejects anything else;
   `moderated_at IS NOT NULL` is enforced in Step 1.6).
3. UTC bucket convention: Map `observed_at` → (`date_key`, `time_key`)
   using UTC timestamps (`observed_at AT TIME ZONE 'UTC'`), enforced by
   `chk_fact_observation_dim_alignment` and `chk_fact_report_dim_alignment`.
   Fact causality is guaranteed by `chk_fact_observation_causal_time`.
   Leave `weather_key` NULL until a weather adapter exists.
4. One evidence row in → one fact row out (grain fidelity); aggregates
   recompute from grains, never from other aggregates.
5. Daily status-count conservation: `available_count + busy_count + broken_count <= observation_count`,
   enforced by `chk_fact_daily_status_counts`. Unknown observations are counted in total
   observation_count but none of the 3 discrete state counts.
6. No-evidence station-days stay absent from `fact_station_daily`.

## 9. Legacy table policy

Nine legacy warehouse tables pre-date this design and live in `public`:

`dim_date`, `dim_location`, `dim_station`, `dim_tariff`, `dim_time`,
`dim_vehicle`, `dim_weather`, `fact_charging_session`,
`fact_station_daily_agg`.

Policy (absolute): **do not DROP, ALTER, RENAME, TRUNCATE, INSERT INTO,
UPDATE, or DELETE FROM any of them.** All nine are empty and remain
untouched and future-reserved where applicable. The Step 1.4 migration
names them in header comments only — no executable statement references
them (verify: strip `--` comments, then `grep` for `public.dim_` /
`public.fact_` must return zero hits outside the new `analytics` DDL…
in fact zero hits at all, since facts reference only `analytics.dim_*`).

## 10. No-fabrication rule

Only two kinds of rows are seeded in Step 1.4, both deterministic
reference data: `dim_date` (calendar arithmetic) and `dim_time`
(96 fixed slots). Everything else enters the warehouse exclusively as
legitimate historical operational data via ETL.

Concretely forbidden in 1.4 (and enforced by simply not creating them):

- synthetic stations, connectors, observations, reports, reviews,
  weather rows, prices, predictions;
- `total_sessions`, `total_energy_kwh`, `total_revenue`,
  `avg_duration_minutes`, `session_count` in `fact_station_daily` —
  these require genuine charging-session data and must not be invented;
- `is_fast_charging` values without a documented ETL derivation rule
  (no source column exists in `public.connectors`);
- interpreting missing evidence as zero activity (`has_evidence`,
  absent daily rows, nullable `weather_key`).

Development synthetic data stays in dev/test fixtures; it never flows
into production analytics.

## 11. OLAP examples

All examples read `analytics` only. Ratios/scores are non-additive:
aggregate by recomputing from grain tables, never `SUM(ratio)`.

```sql
-- Daily availability trend for one station (current SCD2 version)
SELECT d.full_date, f.availability_ratio, f.busy_ratio, f.broken_ratio,
       f.avg_queue_score, f.observation_count
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d USING (date_key)
JOIN analytics.dim_station s USING (station_key)
WHERE s.station_id = '<operational-uuid>' AND s.is_current
ORDER BY d.full_date;

-- Busiest 15-min slots across a city (observations grain, date conformed)
SELECT t.slot_15min, count(*) AS busy_obs
FROM analytics.fact_station_observation o
JOIN analytics.dim_station s USING (station_key)
JOIN analytics.dim_location l USING (location_key)
JOIN analytics.dim_time t USING (time_key)
WHERE l.city = 'Mumbai' AND o.availability_status = 'busy'
GROUP BY t.slot_15min ORDER BY busy_obs DESC;

-- Approved community-signal volume vs system observations per day
SELECT d.full_date,
       sum(f.observation_count) AS system_obs,
       sum(f.report_count)      AS approved_reports,
       sum(f.review_count)      AS approved_reviews
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d USING (date_key)
GROUP BY d.full_date ORDER BY d.full_date;

-- Stations ready for intelligence (maturity gate before any ML use)
SELECT s.station_name, f.date_key, f.data_completeness_score
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s USING (station_key)
WHERE f.maturity = 'ready' AND s.is_current;
```

## 12. Future ML relationship

The warehouse is the ML-ready substrate, not the model layer:

- `fact_station_daily` is the primary feature source (evidence counts,
  status ratios, queue scores, ratings, completeness, maturity).
  `maturity` (`cold / warming / ready`) gates intelligence: no forecast
  or recommendation may be exposed for stations without `ready`-grade
  evidence.
- Grain facts (`fact_station_observation`, `fact_user_report`) support
  feature engineering (hour/weekday patterns, recent-status windows)
  once real history accumulates.
- `dim_weather` activates when a weather adapter lands (nullable FKs
  become populated; vocabulary locked then).
- Forecast outputs belong to a future `ml` scope — predictions are
  never written as facts, never mixed with observed availability, and
  surface as `null` when confidence/evidence is insufficient.
- Baseline-first discipline applies: establish a naive baseline on
  warehouse aggregates, then train, evaluate against it, and expose
  only sufficiently supported intelligence with explanations.
