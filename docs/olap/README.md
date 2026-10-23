# ChargePlus — Academic OLAP SQL Suite & Data Warehouse Guide

**Course:** Data Warehouse & Data Mining (DWDM)  
**Schema:** `analytics` (Kimball Star Schema)  
**Operational Storage:** Supabase PostgreSQL (`public` and `analytics` schemas)  
**SQL Script:** [`docs/olap/olap_queries.sql`](file:///d:/Desktop/Projects/ChargePlus/docs/olap/olap_queries.sql)

---

## 1. Executive Summary & Live Supabase Inventory

ChargePlus operates a dual-schema PostgreSQL architecture on Supabase:
1. **`public` schema (OLTP):** Normalized operational database powering driver discovery, station availability, connector status, driver reviews, and user reports.
2. **`analytics` schema (OLAP):** Kimball Star Schema optimized for high-performance multidimensional analytical queries, data cube materialization, and machine learning feature extraction.

### Current Database Inventory
* **Public Operational Stations:** `557` verified stations across Mumbai & Maharashtra ingested from OpenChargeMap, OpenStreetMap, and Data.gov.in.
* **Public Operational Connectors:** `661` connectors (CCS2, Type 2, Bharat AC/DC, CHAdeMO).
* **Calendar Dimension (`analytics.dim_date`):** `3,288` date records (from 2020 through 2028).
* **Station Dimension (`analytics.dim_station`):** `29` dimension stations.
* **Operator Dimension (`analytics.dim_operator`):** `11` CPO networks (Tata Power, Jio-bp, Statiq, Ather Energy, ChargeZone, Fortum, Kazam, Magenta, etc.).
* **Location Dimension (`analytics.dim_location`):** `19` geographical hierarchy records.
* **Daily Fact Table (`analytics.fact_station_daily`):** `360` records representing **12 representative Mumbai stations across all 30 days of September 2026** (17,280 total 15-minute telemetry observation ticks).

---

## 2. OLAP Operations Mapping (DWDM Syllabus)

The query suite in `docs/olap/olap_queries.sql` demonstrates core multidimensional operations:

| Operation | Query Name | Business Dimension | Analytical Purpose |
| :--- | :--- | :--- | :--- |
| **Roll-Up** | Query 1A & 1B | Time (`dim_date`) | Navigates from fine grain (Day / Week) up to coarse grain (Month, Year, Grand Total) |
| **Drill-Down** | Query 2 | Geographic (`dim_location`) & Network (`dim_operator`) | Navigates from macro city level down to locality, station, and operator grain |
| **Slice & Dice** | Query 3 | Operator (`dim_operator`), Geography (`dim_location`), Time (`dim_date`) | Slices on specific CPOs and dices across business districts and weekend vs weekday patterns |
| **CUBE / Pivot** | Query 4 | Cross-dimensional (`Operator` $\times$ `Locality`) | Generates all $2^N$ subtotal permutations across operators and localities |
| **Window Ranking** | Query 5 | Operator Partition (`DENSE_RANK()`) | Partitions by CPO network and ranks top congested infrastructure |

---

## 3. Query Suite Details & Execution Results

### Query 1: ROLL-UP (Hierarchical Time Aggregation)

#### Query 1A: Month $\rightarrow$ Year $\rightarrow$ Grand Total
```sql
SELECT 
    COALESCE(CAST(d.year AS TEXT), 'ALL YEARS') AS year,
    COALESCE(d.month_name, 'ANNUAL TOTAL') AS month_name,
    COUNT(DISTINCT f.station_key) AS active_stations,
    SUM(f.observation_count) AS total_telemetry_ticks,
    ROUND(AVG(f.busy_ratio) * 100, 2) AS monthly_avg_utilization_pct,
    ROUND(AVG(f.availability_ratio) * 100, 2) AS network_uptime_pct
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d ON f.date_key = d.date_key
GROUP BY ROLLUP (d.year, (d.month, d.month_name))
ORDER BY d.year NULLS LAST, d.month NULLS LAST;
```
**Interpretation of Output:**
```
year,month_name,active_stations,total_telemetry_ticks,monthly_avg_utilization_pct,network_uptime_pct
2026,September,12,17280,23.73,74.36
2026,ANNUAL TOTAL,12,17280,23.73,74.36
ALL YEARS,ANNUAL TOTAL,12,17280,23.73,74.36
```
> **Academic Note on `NULL`s in ROLLUP:**  
> Standard SQL `ROLLUP` produces hierarchical subtotal rows with `NULL` markers for summarized dimensions. Because the warehouse currently contains September 2026 telemetry, the September monthly aggregate, the 2026 annual total, and the grand total are mathematically identical.

#### Query 1B: Week $\rightarrow$ Month $\rightarrow$ Grand Total
To see progressive subtotals across multiple rows within the dataset:
```sql
SELECT 
    COALESCE(d.month_name, 'ALL MONTHS') AS month,
    COALESCE(CAST(d.week AS TEXT), 'MONTHLY TOTAL') AS calendar_week,
    COUNT(DISTINCT f.station_key) AS active_stations,
    SUM(f.observation_count) AS total_telemetry_ticks,
    ROUND(AVG(f.busy_ratio) * 100, 2) AS avg_utilization_pct,
    ROUND(AVG(f.availability_ratio) * 100, 2) AS network_uptime_pct
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d ON f.date_key = d.date_key
GROUP BY ROLLUP (d.month_name, d.week)
ORDER BY d.month_name NULLS LAST, d.week NULLS LAST;
```
**Execution Output:**
| month | calendar_week | active_stations | total_telemetry_ticks | avg_utilization_pct | network_uptime_pct |
| :--- | :--- | :--- | :--- | :--- | :--- |
| September | 36 | 12 | 3,456 | 23.99% | 74.07% |
| September | 37 | 12 | 4,032 | 23.84% | 74.08% |
| September | 38 | 12 | 4,032 | 22.97% | 75.07% |
| September | 39 | 12 | 4,032 | 23.66% | 74.73% |
| September | 40 | 12 | 1,728 | 24.88% | 73.03% |
| **September** | **MONTHLY TOTAL** | **12** | **17,280** | **23.73%** | **74.36%** |
| **ALL MONTHS** | **MONTHLY TOTAL** | **12** | **17,280** | **23.73%** | **74.36%** |

---

### Query 2: DRILL-DOWN (Geographic & Operator Granularity)
Drills down from Mumbai city level into specific localities, identifying congestion hotspots:
```sql
SELECT 
    l.city,
    l.locality,
    o.operator_name,
    s.station_name,
    ROUND(AVG(f.busy_ratio) * 100, 2) AS locality_avg_utilization,
    SUM(f.busy_count) AS total_congestion_events
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
WHERE l.city = 'Mumbai'
GROUP BY l.city, l.locality, o.operator_name, s.station_name
ORDER BY locality_avg_utilization DESC;
```
**Top Results:**
- **Lower Parel (Statiq Phoenix Mall):** 40.76% utilization (587 congestion events)
- **Bandra Kurla Complex (Tata Power EZ):** 32.99% utilization (475 congestion events)
- **Goregaon East (Tata Power Oberoi Mall):** 29.24% utilization (421 congestion events)
- **Sahar Airport T2 (ChargeZone Hub):** 27.50% utilization (396 congestion events)

---

### Query 3: SLICE & DICE (Multi-Dimensional Filtration)
Slices on high-density operators (`Tata Power`, `Jio-bp`) in business localities (`BKC`, `Lower Parel`) diced by weekday vs weekend:
```sql
SELECT 
    o.operator_name,
    l.locality,
    CASE WHEN d.is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    ROUND(AVG(f.busy_ratio) * 100, 2) AS sliced_utilization_pct,
    ROUND(AVG(f.availability_ratio) * 100, 2) AS sliced_uptime_pct
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
JOIN analytics.dim_date d ON f.date_key = d.date_key
WHERE o.operator_name IN ('Tata Power', 'Jio-bp')
  AND l.locality IN ('Bandra Kurla Complex', 'Lower Parel')
GROUP BY o.operator_name, l.locality, d.is_weekend
ORDER BY o.operator_name, day_type;
```
**Key Analytical Finding:**
- Tata Power in BKC experiences **35.32% utilization on weekdays** (fleet & executive commute traffic) vs **26.56% on weekends**, reflecting standard business district diurnal patterns.

---

### Query 4: CUBE (Multi-Operator Cross-Tabulation)
Computes all subtotal combinations of Operator $\times$ Locality:
```sql
SELECT 
    COALESCE(o.operator_name, 'ALL OPERATORS') AS operator,
    COALESCE(l.locality, 'ALL LOCALITIES') AS locality,
    COUNT(f.date_key) AS days_monitored,
    ROUND(AVG(f.busy_ratio) * 100, 2) AS cube_avg_utilization
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
GROUP BY CUBE (o.operator_name, l.locality)
ORDER BY operator, locality;
```

---

### Query 5: ANALYTICAL WINDOW FUNCTION (Top 3 Congested by Operator)
Applies SQL window partitioning (`PARTITION BY o.operator_name ORDER BY AVG(...) DESC`) to rank stations without self-joins:
```sql
WITH ranked_stations AS (
    SELECT 
        o.operator_name,
        s.station_name,
        ROUND(AVG(f.busy_ratio) * 100, 2) AS overall_utilization,
        DENSE_RANK() OVER (
            PARTITION BY o.operator_name 
            ORDER BY AVG(f.busy_ratio) DESC NULLS LAST
        ) AS rank_in_network
    FROM analytics.fact_station_daily f
    JOIN analytics.dim_station s ON f.station_key = s.station_key
    JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
    GROUP BY o.operator_name, s.station_name
)
SELECT * 
FROM ranked_stations
WHERE rank_in_network <= 3
ORDER BY operator_name, rank_in_network;
```

---

## 4. How to Run Against Supabase

### Option A: Via Supabase SQL Editor
1. Open the [Supabase Dashboard](https://supabase.com/dashboard).
2. Navigate to your project (`ChargePlus`) $\rightarrow$ **SQL Editor**.
3. Copy and paste queries directly from [`docs/olap/olap_queries.sql`](file:///d:/Desktop/Projects/ChargePlus/docs/olap/olap_queries.sql).
4. Run each query individually or all together.

### Option B: Via Python CLI
```bash
python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
with open('docs/olap/olap_queries.sql', 'r') as f:
    sql = f.read()
# Run desired query
"
```
