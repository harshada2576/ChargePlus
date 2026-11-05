"""ChargePlus — Idempotent Database Seeder for Local Development & Demo Mode.

Populates PostgreSQL/PostGIS with version-controlled canonical Mumbai stations,
connectors, and recent observations from data/canonical_stations.json.

Safety Guarantee:
- Uses require_disposable_target to strictly prevent targeting production databases.
- Idempotent via ON CONFLICT clauses; rerunning will never duplicate stations or corrupt constraints.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values

# Ensure workspace root is in python path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tests.db_target_guard import require_disposable_target, UnsafeDatabaseTarget


def seed_database(db_url: str | None = None) -> dict[str, int]:
    """Seed the local/disposable database idempotently with canonical test data."""
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not configured. Set DATABASE_URL to a local/disposable PostgreSQL target.")

    # Guard against accidental production execution
    host = require_disposable_target(url, test_id="seed_demo_db")
    print(f"[SEED] Target database verified safe ({host}). Proceeding with idempotent seed...")

    stations_file = ROOT / "data" / "canonical_stations.json"
    if not stations_file.exists():
        raise FileNotFoundError(f"Missing seed dataset at {stations_file}")

    with open(stations_file, encoding="utf-8") as f:
        stations_data = json.load(f)

    conn = psycopg2.connect(url)
    conn.autocommit = False

    counts = {
        "operators": 0,
        "sources": 0,
        "stations": 0,
        "connectors": 0,
        "observations": 0,
    }

    try:
        with conn.cursor() as cur:
            # 1. Seed or resolve data source
            cur.execute("""
                INSERT INTO public.data_sources (name, source_type, base_url, source_priority, is_active)
                VALUES ('Offline Canonical Mumbai Seed', 'demo_dataset', 'file://data/canonical_stations.json', 10, true)
                ON CONFLICT (name) DO UPDATE SET is_active = EXCLUDED.is_active
                RETURNING id;
            """)
            source_id = cur.fetchone()[0]
            counts["sources"] += 1

            # 2. Extract and seed distinct operators
            unique_operators = {s["operator"] for s in stations_data if s.get("operator")}
            operator_id_map: dict[str, str] = {}
            for op_name in unique_operators:
                slug = op_name.lower().replace(" ", "-").replace("—", "-").strip("-")[:190]
                cur.execute("""
                    INSERT INTO public.operators (name, slug)
                    VALUES (%s, %s)
                    ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                """, (op_name, slug))
                operator_id_map[op_name] = str(cur.fetchone()[0])
                counts["operators"] += 1

            # 3. Seed stations
            for s in stations_data:
                st_id = s["id"]
                op_id = operator_id_map.get(s["operator"])
                lat = float(s["latitude"])
                lng = float(s["longitude"])
                name = s["name"]
                slug = (st_id[:8] + "-" + name.lower().replace(" ", "-").replace("—", "-"))[:190]
                address = s.get("address_line", "")
                locality = s.get("locality", "Mumbai")
                city = s.get("city", "Mumbai")
                state = s.get("state", "Maharashtra")
                postal_code = s.get("postal_code")
                is_24h = bool(s.get("is_24_hours", True))
                open_time = s.get("opening_time") if not is_24h else None
                close_time = s.get("closing_time") if not is_24h else None

                cur.execute("""
                    INSERT INTO public.stations (
                        id, slug, name, operator_id, address_line, locality, city, state, postal_code,
                        country, latitude, longitude, geom, is_24_hours, opening_time, closing_time,
                        operational_status, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'India', %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s, %s, %s, 'operational', now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        geom = EXCLUDED.geom,
                        operational_status = EXCLUDED.operational_status,
                        updated_at = now();
                """, (
                    st_id, slug, name, op_id, address, locality, city, state, postal_code,
                    lat, lng, lng, lat, is_24h, open_time, close_time
                ))
                counts["stations"] += 1

                # Link record
                cur.execute("""
                    INSERT INTO public.station_source_link (
                        station_id, source_id, source_station_id, first_seen_at, last_seen_at, last_ingested_at, is_active
                    ) VALUES (
                        %s, %s, %s, now(), now(), now(), true
                    )
                    ON CONFLICT (source_id, source_station_id) DO UPDATE SET
                        last_seen_at = now(),
                        last_ingested_at = now();
                """, (st_id, source_id, st_id))

                # 4. Seed connectors
                for c in s.get("connectors", []):
                    c_id = c["id"]
                    c_type = c["connector_type"]
                    std = c.get("charging_standard")
                    power = float(c.get("power_kw", 22.0))
                    qty = int(c.get("quantity", 1))
                    price = float(c["price_per_kwh"]) if c.get("price_per_kwh") is not None else None

                    cur.execute("""
                        INSERT INTO public.connectors (
                            id, station_id, connector_type, charging_standard, power_kw, quantity,
                            pricing_type, price_per_kwh, currency, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            'per_kwh', %s, 'INR', now()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            connector_type = EXCLUDED.connector_type,
                            power_kw = EXCLUDED.power_kw,
                            quantity = EXCLUDED.quantity,
                            price_per_kwh = EXCLUDED.price_per_kwh,
                            updated_at = now();
                    """, (c_id, st_id, c_type, std, power, qty, price))
                    counts["connectors"] += 1

                    # 5. Seed one recent observation per connector so telemetry is fresh and traceable
                    obs_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                    cur.execute("""
                        INSERT INTO public.station_observations (
                            station_id, connector_id, source_id, availability_status, queue_level,
                            available_connectors, total_connectors, observed_at, received_at, confidence_score
                        ) VALUES (
                            %s, %s, %s, 'available', 'none',
                            %s, %s, %s, now(), 1.0
                        );
                    """, (st_id, c_id, source_id, qty, qty, obs_time))
                    counts["observations"] += 1

        conn.commit()
        print(f"[SEED SUCCESS] Seeded: {counts['stations']} stations, {counts['connectors']} connectors, {counts['observations']} observations.")
        return counts
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    seed_database()
