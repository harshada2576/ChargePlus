-- ==============================================================================
-- CHARGEPLUS — ACADEMIC OLAP SQL DEMONSTRATION SUITE
-- Subject: Data Warehouse & Data Mining (DWDM)
-- Schema: analytics (Kimball Star Schema)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- QUERY 1: ROLL-UP (Hierarchical Time Aggregation)
-- Aggregates EV charging utilization from Daily -> Weekly -> Monthly grain
-- ------------------------------------------------------------------------------
SELECT 
    d.year,
    d.month,
    d.month_name,
    COUNT(DISTINCT f.station_key) AS active_stations,
    SUM(f.total_observations) AS total_telemetry_ticks,
    ROUND(AVG(f.avg_utilization_pct), 2) AS monthly_avg_utilization_pct,
    ROUND(AVG(f.uptime_pct), 2) AS network_uptime_pct
FROM analytics.fact_station_daily f
JOIN analytics.dim_date d ON f.date_key = d.date_key
GROUP BY ROLLUP (d.year, (d.month, d.month_name))
ORDER BY d.year, d.month;

-- ------------------------------------------------------------------------------
-- QUERY 2: DRILL-DOWN (Geographic & Operator Granularity)
-- Drills down from City level -> Locality -> Station -> Operator
-- ------------------------------------------------------------------------------
SELECT 
    l.city,
    l.locality,
    o.operator_name,
    s.station_name,
    ROUND(AVG(f.avg_utilization_pct), 2) AS locality_avg_utilization,
    SUM(f.busy_observations) AS total_congestion_events
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
WHERE l.city = 'Mumbai'
GROUP BY l.city, l.locality, o.operator_name, s.station_name
ORDER BY locality_avg_utilization DESC;

-- ------------------------------------------------------------------------------
-- QUERY 3: SLICE & DICE (Multi-Dimensional Filtration)
-- Slices on: High-speed corridor operators (Tata Power, Jio-bp)
-- Dices on: Weekend vs Weekday peak hours in business districts (BKC, Lower Parel)
-- ------------------------------------------------------------------------------
SELECT 
    o.operator_name,
    l.locality,
    CASE WHEN d.is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    ROUND(AVG(f.avg_utilization_pct), 2) AS sliced_utilization_pct,
    ROUND(AVG(f.uptime_pct), 2) AS sliced_uptime_pct
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
JOIN analytics.dim_date d ON f.date_key = d.date_key
WHERE o.operator_name IN ('Tata Power', 'Jio-bp')
  AND l.locality IN ('Bandra Kurla Complex', 'Lower Parel')
GROUP BY o.operator_name, l.locality, d.is_weekend
ORDER BY o.operator_name, day_type;

-- ------------------------------------------------------------------------------
-- QUERY 4: PIVOT / CUBE (Multi-Operator Cross-Tabulation)
-- Generates full multidimensional cube of metrics across Operator x Locality
-- ------------------------------------------------------------------------------
SELECT 
    COALESCE(o.operator_name, 'ALL OPERATORS') AS operator,
    COALESCE(l.locality, 'ALL LOCALITIES') AS locality,
    COUNT(f.date_key) AS days_monitored,
    ROUND(AVG(f.avg_utilization_pct), 2) AS cube_avg_utilization
FROM analytics.fact_station_daily f
JOIN analytics.dim_station s ON f.station_key = s.station_key
JOIN analytics.dim_operator o ON s.operator_key = o.operator_key
JOIN analytics.dim_location l ON s.location_key = l.location_key
GROUP BY CUBE (o.operator_name, l.locality)
ORDER BY operator, locality;

-- ------------------------------------------------------------------------------
-- QUERY 5: ANALYTICAL WINDOW FUNCTION (Top 3 Congested Stations by Operator)
-- Demonstrates SQL analytical ranking across partitions
-- ------------------------------------------------------------------------------
WITH ranked_stations AS (
    SELECT 
        o.operator_name,
        s.station_name,
        ROUND(AVG(f.avg_utilization_pct), 2) AS overall_utilization,
        DENSE_RANK() OVER (
            PARTITION BY o.operator_name 
            ORDER BY AVG(f.avg_utilization_pct) DESC
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
