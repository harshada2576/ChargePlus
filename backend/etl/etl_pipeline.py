"""
backend/etl/etl_pipeline.py
ChargePlus — Phase 4 Data Warehouse ETL Pipeline
Extracts canonical stations and observation streams, transforms into Kimball Star Schema dimensions and facts,
and generates local data warehouse files.
"""

import json
import os
import pandas as pd
from datetime import datetime

def run_etl():
    print("[ETL] Step 1: Extracting canonical stations and observations...")
    with open("data/canonical_stations.json") as f:
        stations = json.load(f)
    with open("data/observations.json") as f:
        observations = json.load(f)

    # -------------------------------------------------------------
    # 1. Transform Dimensions
    # -------------------------------------------------------------
    print("[ETL] Step 2: Transforming Conformed Dimensions (dim_station, dim_operator, dim_location)...")
    
    # dim_operator
    operators_data = []
    op_key_map = {}
    for idx, s in enumerate(stations):
        op_name = s["operator"]
        if op_name not in op_key_map:
            op_key = len(op_key_map) + 1
            op_key_map[op_name] = op_key
            operators_data.append({
                "operator_key": op_key,
                "operator_name": op_name,
                "created_at": datetime.now().isoformat()
            })
    df_dim_operator = pd.DataFrame(operators_data)

    # dim_location
    locations_data = []
    loc_key_map = {}
    for s in stations:
        loc_str = f"{s['locality']}|{s['postal_code']}"
        if loc_str not in loc_key_map:
            loc_key = len(loc_key_map) + 1
            loc_key_map[loc_str] = loc_key
            locations_data.append({
                "location_key": loc_key,
                "locality": s["locality"],
                "city": s["city"],
                "state": s["state"],
                "postal_code": s["postal_code"],
                "country": s["country"]
            })
    df_dim_location = pd.DataFrame(locations_data)

    # dim_station (SCD Type 2 compatible snapshot)
    station_data = []
    station_key_map = {}
    for idx, s in enumerate(stations):
        s_key = idx + 1
        station_key_map[s["id"]] = s_key
        loc_str = f"{s['locality']}|{s['postal_code']}"
        station_data.append({
            "station_key": s_key,
            "station_id": s["id"],
            "operator_key": op_key_map[s["operator"]],
            "location_key": loc_key_map[loc_str],
            "station_name": s["name"],
            "latitude": s["latitude"],
            "longitude": s["longitude"],
            "is_24_hours": s["is_24_hours"],
            "total_connectors": sum(c["quantity"] for c in s["connectors"]),
            "is_current": True,
            "valid_from": "2026-09-01T00:00:00Z"
        })
    df_dim_station = pd.DataFrame(station_data)

    # dim_connector
    connector_data = []
    conn_key_map = {}
    for s in stations:
        for c in s["connectors"]:
            c_key = len(conn_key_map) + 1
            conn_key_map[c["id"]] = c_key
            connector_data.append({
                "connector_key": c_key,
                "connector_id": c["id"],
                "station_key": station_key_map[s["id"]],
                "connector_type": c["connector_type"],
                "power_kw": c["power_kw"],
                "total_quantity": c["quantity"],
                "price_per_kwh": c["price_per_kwh"]
            })
    df_dim_connector = pd.DataFrame(connector_data)

    # -------------------------------------------------------------
    # 2. Transform Facts
    # -------------------------------------------------------------
    print("[ETL] Step 3: Transforming Atomic Facts & Aggregating Daily Summaries...")
    df_obs = pd.DataFrame(observations)
    df_obs["dt"] = pd.to_datetime(df_obs["observed_at"])
    df_obs["date_key"] = df_obs["dt"].dt.strftime("%Y%m%d").astype(int)
    # Time key: 15-minute slot index (0 to 95)
    df_obs["time_key"] = (df_obs["dt"].dt.hour * 4 + df_obs["dt"].dt.minute // 15).astype(int)
    df_obs["station_key"] = df_obs["station_id"].map(station_key_map)
    df_obs["connector_key"] = df_obs["connector_id"].map(conn_key_map)
    df_obs["is_available"] = (df_obs["availability_status"] == "available").astype(int)
    df_obs["is_busy"] = (df_obs["availability_status"] == "busy").astype(int)
    df_obs["is_broken"] = (df_obs["availability_status"] == "broken").astype(int)
    df_obs["utilization_pct"] = (
        (df_obs["total_connectors"] - df_obs["available_connectors"]) / df_obs["total_connectors"] * 100
    ).round(2)

    # fact_station_daily summary aggregate
    daily_summary = df_obs.groupby(["station_key", "date_key"]).agg(
        total_observations=("id", "count"),
        avg_utilization_pct=("utilization_pct", "mean"),
        busy_observations=("is_busy", "sum"),
        broken_observations=("is_broken", "sum"),
        available_observations=("is_available", "sum")
    ).reset_index()
    daily_summary["avg_utilization_pct"] = daily_summary["avg_utilization_pct"].round(2)
    daily_summary["uptime_pct"] = (
        (daily_summary["total_observations"] - daily_summary["broken_observations"]) 
        / daily_summary["total_observations"] * 100
    ).round(2)

    # -------------------------------------------------------------
    # 3. Load & Export Warehouse Schema Tables
    # -------------------------------------------------------------
    print("[ETL] Step 4: Loading into Warehouse Data Catalog...")
    os.makedirs("data/warehouse", exist_ok=True)
    
    df_dim_operator.to_csv("data/warehouse/dim_operator.csv", index=False)
    df_dim_location.to_csv("data/warehouse/dim_location.csv", index=False)
    df_dim_station.to_csv("data/warehouse/dim_station.csv", index=False)
    df_dim_connector.to_csv("data/warehouse/dim_connector.csv", index=False)
    daily_summary.to_csv("data/warehouse/fact_station_daily.csv", index=False)
    
    print("\n[ETL SUCCESS] Warehouse Star Schema Tables Populated:")
    print(f"  • analytics.dim_operator:        {len(df_dim_operator)} rows")
    print(f"  • analytics.dim_location:        {len(df_dim_location)} rows")
    print(f"  • analytics.dim_station:         {len(df_dim_station)} rows")
    print(f"  • analytics.dim_connector:       {len(df_dim_connector)} rows")
    print(f"  • analytics.fact_station_daily:  {len(daily_summary)} daily aggregates")

if __name__ == "__main__":
    run_etl()
