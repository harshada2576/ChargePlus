"""
backend/warehouse/seed_warehouse_demo.py
Seeds the analytics schema (dim_operator, dim_location, dim_station, fact_station_daily)
from data/canonical_stations.json and data/observations.json so that the DWDM OLAP
queries return rich demonstration data.
"""

import json
import os
import uuid
import psycopg2
from psycopg2.extras import execute_values

QUEUE_SCORES = {"none": 0.0, "short": 0.33, "medium": 0.66, "long": 1.0}

def seed_demo_warehouse(dry_run=False):
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres.abclmxvaxkdbiqdfgdvl:oSqWln784TcS8Hge@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres")
    
    with open("data/canonical_stations.json", "r", encoding="utf-8") as f:
        stations = json.load(f)
        
    with open("data/observations.json", "r", encoding="utf-8") as f:
        observations = json.load(f)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # 1. Operators
        print("[1/4] Upserting operators into analytics.dim_operator...")
        op_names = sorted(list(set(s["operator"] for s in stations)))
        op_key_map = {}
        for name in op_names:
            # Deterministic namespace UUID for operators
            op_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"chargeplus.operator.{name}"))
            cur.execute("""
                INSERT INTO analytics.dim_operator (operator_id, operator_name, slug)
                VALUES (%s, %s, %s)
                ON CONFLICT (operator_id) DO UPDATE SET operator_name = EXCLUDED.operator_name
                RETURNING operator_key;
            """, (op_uuid, name, name.lower().replace(" ", "-")))
            op_key_map[name] = cur.fetchone()[0]

        # 2. Locations
        print("[2/4] Upserting locations into analytics.dim_location...")
        loc_key_map = {}
        for s in stations:
            loc_tuple = (s.get("country", "India"), s.get("state", "Maharashtra"), s.get("city", "Mumbai"), s.get("locality"), s.get("postal_code"))
            if loc_tuple not in loc_key_map:
                cur.execute("""
                    INSERT INTO analytics.dim_location (country, state, city, locality, postal_code)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (country, state, city, COALESCE(locality, ''), COALESCE(postal_code, ''))
                    DO UPDATE SET locality = EXCLUDED.locality
                    RETURNING location_key;
                """, loc_tuple)
                loc_key_map[loc_tuple] = cur.fetchone()[0]

        # 3. Stations
        print("[3/4] Upserting stations into analytics.dim_station...")
        station_key_map = {}
        for s in stations:
            s_uuid = s["id"]
            loc_tuple = (s.get("country", "India"), s.get("state", "Maharashtra"), s.get("city", "Mumbai"), s.get("locality"), s.get("postal_code"))
            l_key = loc_key_map[loc_tuple]
            o_key = op_key_map[s["operator"]]

            # Check if station already exists
            cur.execute("SELECT station_key FROM analytics.dim_station WHERE station_id = %s AND is_current = TRUE", (s_uuid,))
            res = cur.fetchone()
            if res:
                sk = res[0]
            else:
                cur.execute("""
                    INSERT INTO analytics.dim_station (
                        station_id, station_name, operator_key, location_key,
                        latitude, longitude, is_24_hours, is_public, operational_status, is_current
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING station_key;
                """, (
                    s_uuid, s["name"], o_key, l_key,
                    s["latitude"], s["longitude"], s.get("is_24_hours", True),
                    True, s.get("operational_status", "operational")
                ))
                sk = cur.fetchone()[0]
            station_key_map[s_uuid] = sk

        # 4. Daily aggregates
        print("[4/4] Aggregating observations into analytics.fact_station_daily...")
        daily_cells = {}
        for obs in observations:
            s_id = obs["station_id"]
            sk = station_key_map.get(s_id)
            if not sk:
                continue
            dt_str = obs["observed_at"][:10].replace("-", "")
            dk = int(dt_str)
            
            cell_key = (sk, dk)
            if cell_key not in daily_cells:
                daily_cells[cell_key] = {"total": 0, "available": 0, "busy": 0, "broken": 0, "queues": []}
            
            cell = daily_cells[cell_key]
            cell["total"] += 1
            st = obs.get("availability_status")
            if st == "available":
                cell["available"] += 1
            elif st == "busy":
                cell["busy"] += 1
            elif st == "broken":
                cell["broken"] += 1
            
            q = obs.get("queue_level")
            if q in QUEUE_SCORES:
                cell["queues"].append(QUEUE_SCORES[q])

        daily_rows = []
        for (sk, dk), c in daily_cells.items():
            tot = c["total"]
            avail_ratio = round(c["available"] / tot, 4) if tot > 0 else None
            busy_ratio = round(c["busy"] / tot, 4) if tot > 0 else None
            broken_ratio = round(c["broken"] / tot, 4) if tot > 0 else None
            avg_q = round(sum(c["queues"]) / len(c["queues"]), 4) if c["queues"] else None
            peak_q = max(c["queues"]) if c["queues"] else None

            daily_rows.append((
                sk, dk, tot, 0, 0,
                c["available"], c["busy"], c["broken"],
                avail_ratio, busy_ratio, broken_ratio,
                avg_q, peak_q,
                1.0, 1, "ready", True
            ))

        sql = """
            INSERT INTO analytics.fact_station_daily (
                station_key, date_key, observation_count, report_count, review_count,
                available_count, busy_count, broken_count,
                availability_ratio, busy_ratio, broken_ratio,
                avg_queue_score, peak_queue_score,
                data_completeness_score, source_count, maturity, has_evidence
            ) VALUES %s
            ON CONFLICT (station_key, date_key) DO UPDATE SET
                observation_count = EXCLUDED.observation_count,
                available_count = EXCLUDED.available_count,
                busy_count = EXCLUDED.busy_count,
                broken_count = EXCLUDED.broken_count,
                availability_ratio = EXCLUDED.availability_ratio,
                busy_ratio = EXCLUDED.busy_ratio,
                broken_ratio = EXCLUDED.broken_ratio,
                avg_queue_score = EXCLUDED.avg_queue_score,
                peak_queue_score = EXCLUDED.peak_queue_score,
                maturity = EXCLUDED.maturity,
                updated_at = now();
        """
        execute_values(cur, sql, daily_rows, page_size=500)

        if dry_run:
            conn.rollback()
            print(f"[DRY RUN] Would insert {len(daily_rows)} daily facts, {len(station_key_map)} stations, {len(op_key_map)} operators.")
        else:
            conn.commit()
            print(f"[SUCCESS] Seeded {len(daily_rows)} daily facts across {len(station_key_map)} stations and {len(op_key_map)} operators into analytics schema!")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed seeding: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    seed_demo_warehouse(dry_run=False)
