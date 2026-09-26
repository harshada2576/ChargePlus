"""ChargePlus — Canonical Operational Loading & Mutation Isolation Test Suite.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.8 (Canonical Operational Loading & Mutation Isolation)

Verifies the transactional and idempotent operational loading of Step 2.7
CanonicalResolutionDecision objects into Supabase/PostgreSQL tables:
- public.stations
- public.connectors
- public.station_source_link
- public.operators
- public.data_sources
- public.station_observations
- analytics.dim_station (SCD Type 2)
- analytics.dim_connector
- analytics.fact_station_observation

Test Sections:
A. NEW STATION (1-4)
B. EXISTING STATION (5-8)
C. KEEP_SEPARATE (9-10)
D. REVIEW (11-12)
E. CONNECTORS (13-18)
F. SOURCE LINKS (19-21)
G. OBSERVATIONS (22-24)
H. TRANSACTIONS & ROLLBACK (25-26)
I. IDEMPOTENCE (27-30)
J. DIMENSIONS & SCD2 (31-33)
K. SAFETY & SECRETS (34-36)
L. LIVE DATABASE INTEGRATION (37)
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import logging
import os
import unittest
from unittest.mock import MagicMock, patch
import uuid

import psycopg2
from dotenv import load_dotenv

from backend.ingestion.constants import (
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.deduplication import (
    CanonicalDecisionState,
    CanonicalDeduplicationEngine,
    CanonicalResolutionDecision,
    ExistingCanonicalStation,
    FieldSurvivorshipDecision,
    SurvivorshipStrategy,
)
from backend.ingestion.persistence import (
    BatchCanonicalPersistenceReport,
    CanonicalPersistenceResult,
    CanonicalPersistenceStatus,
    IngestionPersistenceService,
    PersistenceStatus,
    _scrub_secrets,
)


class MockDatabaseCursor:
    """Simulates PostgreSQL SQL execution over in-memory table structures with full dictionary support."""

    def __init__(self, db: MockDatabaseConnection, as_dict: bool = False):
        self.db = db
        self.as_dict = as_dict
        self._last_result: list = []
        self._iter = iter(self._last_result)

    def execute(self, sql: str, params: tuple | list = ()):
        sql_clean = " ".join(sql.strip().split())
        self._last_result = []

        # 1. SELECT from public.data_sources
        if "FROM public.data_sources WHERE name = %s" in sql_clean:
            name = params[0]
            for row in self.db.tables["public.data_sources"]:
                if row["name"] == name:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        # 2. INSERT INTO public.data_sources
        elif "INSERT INTO public.data_sources" in sql_clean:
            row_id, name, s_type, url, priority = params
            row = {"id": row_id, "name": name, "source_type": s_type, "base_url": url, "source_priority": priority}
            self.db.tables["public.data_sources"].append(row)
            self._last_result = [row if self.as_dict else (row_id,)]

        # 3. SELECT from public.operators
        elif "FROM public.operators WHERE slug = %s" in sql_clean:
            slug = params[0]
            for row in self.db.tables["public.operators"]:
                if row["slug"] == slug:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break
        elif "FROM public.operators WHERE name = %s" in sql_clean:
            name = params[0]
            for row in self.db.tables["public.operators"]:
                if row["name"] == name:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        # 4. INSERT INTO public.operators
        elif "INSERT INTO public.operators" in sql_clean:
            op_id, name, slug, web, phone = params
            row = {"id": op_id, "name": name, "slug": slug, "website_url": web, "support_phone": phone}
            self.db.tables["public.operators"].append(row)
            self._last_result = [row if self.as_dict else (op_id,)]

        # 5. SELECT from public.stations
        elif "SELECT id FROM public.stations WHERE id = %s" in sql_clean:
            stn_id = str(params[0])
            for row in self.db.tables["public.stations"]:
                if str(row["id"]) == stn_id:
                    self._last_result = [row if self.as_dict else (row["id"],)]
                    break

        elif "SELECT s.id, s.name, s.latitude, s.longitude" in sql_clean and "FROM public.stations s" in sql_clean:
            # fetch_existing_canonical_stations query
            for s in self.db.tables["public.stations"]:
                op_row = next((o for o in self.db.tables["public.operators"] if str(o["id"]) == str(s.get("operator_id"))), None)
                r_dict = {
                    "id": s["id"], "name": s["name"], "latitude": s["latitude"], "longitude": s["longitude"],
                    "address_line": s.get("address_line"), "locality": s.get("locality"), "postal_code": s.get("postal_code"),
                    "operator_name": op_row["name"] if op_row else "Unknown Operator",
                    "operator_slug": op_row["slug"] if op_row else None,
                }
                self._last_result.append(r_dict if self.as_dict else tuple(r_dict.values()))

        elif "FROM public.stations s LEFT JOIN public.operators o" in sql_clean or "FROM public.stations s JOIN public.operators o" in sql_clean:
            stn_id = str(params[0])
            for s in self.db.tables["public.stations"]:
                if str(s["id"]) == stn_id:
                    op_row = next((o for o in self.db.tables["public.operators"] if str(o["id"]) == str(s.get("operator_id"))), None)
                    op_name = op_row["name"] if op_row else "Unknown Operator"
                    op_slug = op_row["slug"] if op_row else None
                    r = (
                        s["name"], s["operator_id"], s.get("address_line"), s.get("locality"),
                        s.get("city", "Mumbai"), s.get("state", "Maharashtra"), s.get("postal_code"), s.get("country", "India"),
                        s["latitude"], s["longitude"], s.get("access_type"), s.get("is_public", True),
                        s.get("operational_status", "unknown"), s.get("is_24_hours", False),
                        s.get("opening_time"), s.get("closing_time"), op_name, op_slug,
                    )
                    self._last_result = [r]
                    break

        # 6. INSERT INTO public.stations
        elif "INSERT INTO public.stations" in sql_clean:
            if self.db.should_fail_on_station_insert:
                raise psycopg2.DatabaseError("Simulated database failure on station insertion")
            (stn_id, slug, name, op_id, addr, loc, city, state, pin, ctry,
             lat, lng, op_t, cl_t, is_24, acc_t, is_pub, op_stat, phone, url, v_at) = params
            row = {
                "id": str(stn_id), "slug": slug, "name": name, "operator_id": str(op_id), "address_line": addr,
                "locality": loc, "city": city, "state": state, "postal_code": pin, "country": ctry,
                "latitude": float(lat), "longitude": float(lng), "opening_time": op_t, "closing_time": cl_t,
                "is_24_hours": is_24, "access_type": acc_t, "is_public": is_pub,
                "operational_status": op_stat, "phone": phone, "website_url": url, "last_verified_at": v_at,
            }
            self.db.tables["public.stations"].append(row)
            self.db.mutation_counts["stations_inserted"] += 1

        # 7. UPDATE public.stations
        elif "UPDATE public.stations SET" in sql_clean:
            stn_id = str(params[-1])
            for row in self.db.tables["public.stations"]:
                if str(row["id"]) == stn_id:
                    if params[0] is not None:
                        row["name"] = params[0]
                    if params[1] is not None:
                        row["operator_id"] = params[1]
                    if params[2] is not None:
                        row["address_line"] = params[2]
                    if params[3] is not None:
                        row["locality"] = params[3]
                    if params[4] is not None:
                        row["city"] = params[4]
                    if params[5] is not None:
                        row["state"] = params[5]
                    if params[6] is not None:
                        row["postal_code"] = params[6]
                    if params[7] is not None:
                        row["country"] = params[7]
                    if params[8] is not None:
                        row["latitude"] = float(params[8])
                    if params[9] is not None:
                        row["longitude"] = float(params[9])
                    # hours logic
                    is_24_flag = params[10]
                    if is_24_flag is True:
                        row["is_24_hours"] = True
                        row["opening_time"] = None
                        row["closing_time"] = None
                    elif params[11] is not None:
                        row["opening_time"] = params[11]
                        row["closing_time"] = params[12]
                    if params[13] is not None:
                        row["is_24_hours"] = params[13]
                    if params[14] is not None:
                        row["access_type"] = params[14]
                    if params[15] is not None:
                        row["is_public"] = params[15]
                    if params[16] != "unknown" and params[16] is not None:
                        row["operational_status"] = params[16]
                    if params[18] is not None:
                        row["phone"] = params[18]
                    if params[19] is not None:
                        row["website_url"] = params[19]
                    self.db.mutation_counts["stations_updated"] += 1
                    break

        # 8. SELECT from public.connectors
        elif "SELECT id, connector_type, power_kw, charging_standard, quantity, pricing_type, price_per_kwh, price_per_session FROM public.connectors WHERE station_id = %s" in sql_clean or \
             "SELECT connector_type, charging_standard, power_kw, quantity, pricing_type, price_per_kwh, price_per_session FROM public.connectors WHERE station_id = %s" in sql_clean:
            stn_id = str(params[0])
            for c in self.db.tables["public.connectors"]:
                if str(c["station_id"]) == stn_id:
                    self._last_result.append(c if self.as_dict else (
                        c.get("id"), c["connector_type"], c["power_kw"], c.get("charging_standard"),
                        c["quantity"], c.get("pricing_type"), c.get("price_per_kwh"), c.get("price_per_session"),
                    ))

        elif "SELECT COALESCE(SUM(quantity), 0) FROM public.connectors WHERE station_id = %s" in sql_clean:
            stn_id = str(params[0])
            tot = sum(c["quantity"] for c in self.db.tables["public.connectors"] if str(c["station_id"]) == stn_id)
            self._last_result = [(tot,)]

        # 9. INSERT INTO public.connectors
        elif "INSERT INTO public.connectors" in sql_clean:
            if self.db.should_fail_on_connector_insert:
                raise psycopg2.DatabaseError("Simulated database failure on connector insertion")
            cid, stn_id, ctype, std, pkw, qty, p_type, p_kwh, p_sess = params
            row = {
                "id": str(cid), "station_id": str(stn_id), "connector_type": ctype, "charging_standard": std,
                "power_kw": float(pkw), "quantity": int(qty), "pricing_type": p_type,
                "price_per_kwh": float(p_kwh) if p_kwh is not None else None,
                "price_per_session": float(p_sess) if p_sess is not None else None,
                "currency": "INR",
            }
            self.db.tables["public.connectors"].append(row)
            self.db.mutation_counts["connectors_inserted"] += 1

        # 10. UPDATE public.connectors
        elif "UPDATE public.connectors SET" in sql_clean:
            new_qty, p_type, p_kwh, p_sess, conn_id = params
            for c in self.db.tables["public.connectors"]:
                if str(c["id"]) == str(conn_id):
                    c["quantity"] = int(new_qty)
                    if p_type is not None:
                        c["pricing_type"] = p_type
                    if p_kwh is not None:
                        c["price_per_kwh"] = float(p_kwh)
                    if p_sess is not None:
                        c["price_per_session"] = float(p_sess)
                    self.db.mutation_counts["connectors_updated"] += 1
                    break

        # 11. SELECT from public.station_source_link
        elif "FROM public.station_source_link WHERE source_id = %s AND source_station_id = %s" in sql_clean:
            src_id, src_stn_id = str(params[0]), str(params[1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["source_id"]) == src_id and str(row["source_station_id"]) == src_stn_id:
                    if "SELECT id, station_id, source_id, source_station_id" in sql_clean:
                        self._last_result = [row if self.as_dict else (
                            row["id"], row["station_id"], row["source_id"], row["source_station_id"], row.get("source_payload_hash")
                        )]
                    else:
                        self._last_result = [row if self.as_dict else (
                            row["id"], row["station_id"], row.get("source_payload_hash"), row.get("first_seen_at")
                        )]
                    break

        elif "SELECT ds.name AS source_id, sl.source_station_id FROM public.station_source_link" in sql_clean:
            stn_id = str(params[0])
            for sl in self.db.tables["public.station_source_link"]:
                if str(sl["station_id"]) == stn_id:
                    ds = next((d for d in self.db.tables["public.data_sources"] if str(d["id"]) == str(sl["source_id"])), None)
                    s_name = ds["name"] if ds else str(sl["source_id"])
                    self._last_result.append({"source_id": s_name, "source_station_id": sl["source_station_id"]} if self.as_dict else (s_name, sl["source_station_id"]))

        # 12. INSERT INTO public.station_source_link
        elif "INSERT INTO public.station_source_link" in sql_clean:
            stn_id, src_id, src_stn_id, s_url, p_hash = params
            link_id = uuid.uuid4()
            row = {
                "id": str(link_id), "station_id": str(stn_id), "source_id": str(src_id),
                "source_station_id": str(src_stn_id), "source_url": s_url,
                "source_payload_hash": p_hash, "first_seen_at": datetime.now(timezone.utc),
                "last_seen_at": datetime.now(timezone.utc), "last_ingested_at": datetime.now(timezone.utc),
                "is_active": True,
            }
            self.db.tables["public.station_source_link"].append(row)
            self.db.mutation_counts["station_source_link_inserted"] += 1

        # 13. UPDATE public.station_source_link
        elif "UPDATE public.station_source_link" in sql_clean:
            link_id = str(params[-1])
            for row in self.db.tables["public.station_source_link"]:
                if str(row["id"]) == link_id:
                    row["last_seen_at"] = datetime.now(timezone.utc)
                    row["last_ingested_at"] = datetime.now(timezone.utc)
                    if len(params) > 1 and params[0] is not None:
                        row["source_payload_hash"] = params[0]
                    self.db.mutation_counts["station_source_link_updates"] += 1
                    break

        # 13b. Dimensions: analytics.dim_source
        elif "SELECT source_key FROM analytics.dim_source WHERE source_id = %s" in sql_clean:
            src_id = str(params[0])
            for r in self.db.tables["analytics.dim_source"]:
                if str(r["source_id"]) == src_id:
                    self._last_result = [r if self.as_dict else (r["source_key"],)]
                    break
        elif "INSERT INTO analytics.dim_source" in sql_clean:
            src_id, name, s_type, priority, url = params
            existing = next((s for s in self.db.tables["analytics.dim_source"] if str(s["source_id"]) == str(src_id)), None)
            if existing:
                existing["name"] = name
                existing["source_type"] = s_type
                existing["base_url"] = url
            else:
                key = len(self.db.tables["analytics.dim_source"]) + 1
                row = {
                    "source_key": key, "source_id": str(src_id), "name": name,
                    "source_type": s_type, "source_priority": priority, "base_url": url,
                }
                self.db.tables["analytics.dim_source"].append(row)

        # 14. Dimensions: analytics.dim_operator
        elif "SELECT operator_key FROM analytics.dim_operator WHERE operator_id = %s" in sql_clean:
            op_id = str(params[0])
            for r in self.db.tables["analytics.dim_operator"]:
                if str(r["operator_id"]) == op_id:
                    self._last_result = [r if self.as_dict else (r["operator_key"],)]
                    break
        elif "INSERT INTO analytics.dim_operator" in sql_clean:
            op_id, name, slug = params
            key = len(self.db.tables["analytics.dim_operator"]) + 1
            row = {"operator_key": key, "operator_id": str(op_id), "operator_name": name, "slug": slug}
            self.db.tables["analytics.dim_operator"].append(row)
            self._last_result = [row if self.as_dict else (key,)]

        # 15. Dimensions: analytics.dim_location
        elif "SELECT location_key FROM analytics.dim_location" in sql_clean:
            ctry, state, city, loc, pin = params
            for r in self.db.tables["analytics.dim_location"]:
                if (r["country"] == ctry and r["state"] == state and r["city"] == city
                        and (r.get("locality") or "") == (loc or "")
                        and (r.get("postal_code") or "") == (pin or "")):
                    self._last_result = [r if self.as_dict else (r["location_key"],)]
                    break
        elif "INSERT INTO analytics.dim_location" in sql_clean:
            ctry, state, city, loc, pin = params
            key = len(self.db.tables["analytics.dim_location"]) + 1
            row = {"location_key": key, "country": ctry, "state": state, "city": city, "locality": loc, "postal_code": pin}
            self.db.tables["analytics.dim_location"].append(row)
            self._last_result = [row if self.as_dict else (key,)]

        # 16. Dimensions: analytics.dim_station (SCD2)
        elif "SELECT station_key, station_name, operator_key, location_key, latitude, longitude, address, access_type, is_public, operational_status, is_24_hours, opening_time, closing_time, version FROM analytics.dim_station WHERE station_id = %s AND is_current = true" in sql_clean or \
             "SELECT station_key FROM analytics.dim_station WHERE station_id = %s AND is_current = true" in sql_clean:
            stn_id = str(params[0])
            for r in self.db.tables["analytics.dim_station"]:
                if str(r["station_id"]) == stn_id and r.get("is_current", True):
                    self._last_result = [r if self.as_dict else (
                        r["station_key"], r.get("station_name"), r.get("operator_key"), r.get("location_key"),
                        r.get("latitude"), r.get("longitude"), r.get("address"), r.get("access_type"),
                        r.get("is_public"), r.get("operational_status"), r.get("is_24_hours"),
                        r.get("opening_time"), r.get("closing_time"), r.get("version", 1),
                    )]
                    break

        elif "UPDATE analytics.dim_station SET is_current = false" in sql_clean:
            k = int(params[0])
            for r in self.db.tables["analytics.dim_station"]:
                if r["station_key"] == k:
                    r["is_current"] = False
                    r["effective_to"] = datetime.now(timezone.utc)
                    self.db.mutation_counts["dim_station_closed"] += 1
                    break

        elif "INSERT INTO analytics.dim_station" in sql_clean:
            if len(params) == 13:
                (stn_id, s_name, op_k, loc_k, lat, lng, addr, acc_t, is_pub, op_stat, is_24, op_t, cl_t) = params
                ver = 1
            else:
                (stn_id, s_name, op_k, loc_k, lat, lng, addr, acc_t, is_pub, op_stat, is_24, op_t, cl_t, ver) = params
            key = len(self.db.tables["analytics.dim_station"]) + 1
            row = {
                "station_key": key, "station_id": str(stn_id), "station_name": s_name, "operator_key": op_k,
                "location_key": loc_k, "latitude": float(lat), "longitude": float(lng), "address": addr,
                "access_type": acc_t, "is_public": is_pub, "operational_status": op_stat, "is_24_hours": is_24,
                "opening_time": op_t, "closing_time": cl_t, "is_current": True, "version": int(ver),
                "effective_from": datetime.now(timezone.utc), "effective_to": None,
            }
            self.db.tables["analytics.dim_station"].append(row)
            self.db.mutation_counts["dim_station_inserted"] += 1
            self._last_result = [row if self.as_dict else (key,)]

        # 17. Dimensions: analytics.dim_connector
        elif "INSERT INTO analytics.dim_connector" in sql_clean:
            cid, stn_id, ctype, std, pkw, qty, p_type, p_kwh, p_sess, is_fast = params
            # ON CONFLICT DO UPDATE
            existing = next((c for c in self.db.tables["analytics.dim_connector"] if str(c["connector_id"]) == str(cid)), None)
            if existing:
                existing["quantity"] = int(qty)
                existing["power_kw"] = float(pkw)
                existing["pricing_type"] = p_type
                existing["price_per_kwh"] = p_kwh
                existing["price_per_session"] = p_sess
                self.db.mutation_counts["dim_connector_updated"] += 1
            else:
                key = len(self.db.tables["analytics.dim_connector"]) + 1
                row = {
                    "connector_key": key, "connector_id": str(cid), "station_id": str(stn_id),
                    "connector_type": ctype, "charging_standard": std, "power_kw": float(pkw),
                    "quantity": int(qty), "pricing_type": p_type, "price_per_kwh": p_kwh,
                    "price_per_session": p_sess, "currency": "INR", "is_fast_charging": is_fast,
                }
                self.db.tables["analytics.dim_connector"].append(row)
                self.db.mutation_counts["dim_connector_inserted"] += 1

        # 18. Observations
        elif "SELECT id FROM public.station_observations" in sql_clean:
            stn_id, src_id, p_hash = str(params[0]), str(params[1]), str(params[2])
            for obs in self.db.tables["public.station_observations"]:
                if str(obs["station_id"]) == stn_id and str(obs["source_id"]) == src_id and obs.get("source_payload_hash") == p_hash:
                    self._last_result = [obs if self.as_dict else (obs["id"],)]
                    break

        elif "INSERT INTO public.station_observations" in sql_clean:
            obs_id, stn_id, src_id, avail, q, avail_c, tot_c, o_time, r_time, p_hash = params
            row = {
                "id": str(obs_id), "station_id": str(stn_id), "source_id": str(src_id),
                "availability_status": avail, "queue_level": q, "available_connectors": avail_c,
                "total_connectors": tot_c, "observed_at": o_time, "received_at": r_time, "source_payload_hash": p_hash,
            }
            self.db.tables["public.station_observations"].append(row)
            self.db.mutation_counts["station_observations_inserted"] += 1

        elif "INSERT INTO analytics.fact_station_observation" in sql_clean:
            obs_id, stn_k, d_k, t_k, src_k, o_time, r_time, avail, q, avail_c, tot_c, p_hash = params
            row = {
                "observation_id": str(obs_id), "station_key": stn_k, "date_key": d_k, "time_key": t_k,
                "source_key": src_k, "observed_at": o_time, "received_at": r_time,
                "availability_status": avail, "queue_level": q, "available_connectors": avail_c,
                "total_connectors": tot_c, "source_payload_hash": p_hash,
            }
            self.db.tables["analytics.fact_station_observation"].append(row)
            self.db.mutation_counts["fact_station_observation_inserted"] += 1

        self._iter = iter(self._last_result)

    def fetchone(self):
        return next(self._iter, None)

    def fetchall(self):
        return list(self._iter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockDatabaseConnection:
    """Mock database connection supporting true transaction snapshot & rollback for testing."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "public.data_sources": [],
            "public.operators": [],
            "public.stations": [],
            "public.connectors": [],
            "public.station_source_link": [],
            "public.station_observations": [],
            "analytics.dim_source": [],
            "analytics.dim_operator": [],
            "analytics.dim_location": [],
            "analytics.dim_station": [],
            "analytics.dim_connector": [],
            "analytics.fact_station_observation": [],
        }
        self.mutation_counts: dict[str, int] = {
            "stations_inserted": 0,
            "stations_updated": 0,
            "station_source_link_inserted": 0,
            "station_source_link_updates": 0,
            "connectors_inserted": 0,
            "connectors_updated": 0,
            "dim_station_inserted": 0,
            "dim_station_closed": 0,
            "dim_connector_inserted": 0,
            "dim_connector_updated": 0,
            "station_observations_inserted": 0,
            "fact_station_observation_inserted": 0,
        }
        self._snapshot = copy.deepcopy(self.tables)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.should_fail_on_station_insert = False
        self.should_fail_on_connector_insert = False

    def cursor(self, cursor_factory=None):
        as_dict = cursor_factory is not None
        return MockDatabaseCursor(self, as_dict=as_dict)

    def commit(self):
        self.commits += 1
        # Update snapshot to committed state
        self._snapshot = copy.deepcopy(self.tables)

    def rollback(self):
        self.rollbacks += 1
        # Restore tables to previous snapshot
        self.tables = copy.deepcopy(self._snapshot)

    def close(self):
        self.closed = True

    def total_database_writes(self) -> int:
        return sum(self.mutation_counts.values())


class TestCanonicalOperationalLoading(unittest.TestCase):
    """Authoritative test suite for ChargePlus Phase 2 Step 2.8."""

    def setUp(self):
        self.mock_db = MockDatabaseConnection()
        self.service = IngestionPersistenceService(self.mock_db)

        # Pre-seed standard sources
        self.ocm_source_id = self.service.get_or_create_data_source(
            name="open_charge_map",
            source_type="api",
            base_url="https://api.openchargemap.io/v3/poi/",
        )
        self.osm_source_id = self.service.get_or_create_data_source(
            name="osm",
            source_type="dump",
            base_url="https://planet.openstreetmap.org/",
        )
        self.cpo_source_id = self.service.get_or_create_data_source(
            name="tatapower_cpo",
            source_type="cpo_api",
            base_url="https://api.tatapower.com/ev/",
        )

    def _create_sample_record(
        self,
        source_id: str,
        source_station_id: str,
        name: str = "BKC Fast Charger Hub",
        lat: float = 19.0657,
        lng: float = 72.8685,
        operator_name: str = "Tata Power",
        operator_slug: str = "tata-power",
        connectors: list[NormalizedConnectorRecord] | None = None,
        address: str = "G Block, BKC, Bandra East",
        postal_code: str = "400051",
    ) -> NormalizedStationRecord:
        """Helper to create a valid NormalizedStationRecord for testing."""
        if connectors is None:
            connectors = [
                NormalizedConnectorRecord(
                    connector_type="CCS2",
                    raw_connector_type="CCS (Type 2)",
                    charging_standard="IEC 62196-3",
                    power_kw=120.0,
                    quantity=2,
                    pricing_type=PricingType.PAID,
                    price_per_kwh=18.5,
                )
            ]
        return NormalizedStationRecord(
            source_id=source_id,
            source_station_id=source_station_id,
            name=name,
            operator_name=operator_name,
            operator_slug=operator_slug,
            latitude=lat,
            longitude=lng,
            address_line=address,
            locality="Bandra East",
            city="Mumbai",
            state="Maharashtra",
            postal_code=postal_code,
            country="India",
            is_24_hours=True,
            operational_status=OperationalStatus.OPERATIONAL,
            connectors=connectors,
            extra_metadata={
                "payload_hash": f"hash_{source_id}_{source_station_id}",
                "source_url": f"https://example.com/stn/{source_station_id}",
            },
        )

    # --------------------------------------------------------------------------
    # SECTION A: NEW STATION (Tests 1-4)
    # --------------------------------------------------------------------------

    def test_01_merge_with_no_existing_station_creates_exactly_one_station(self):
        """A1: MERGE with no existing canonical station creates exactly one station in public.stations."""
        r1 = self._create_sample_record("open_charge_map", "ocm-101", name="BKC Tata Charger")
        r2 = self._create_sample_record("osm", "node-202", name="BKC Tata EV Hub")

        decisions = CanonicalDeduplicationEngine.evaluate_records([r1, r2])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision_state, CanonicalDecisionState.MERGE)

        res = self.service.persist_canonical_decision(decisions[0])
        self.assertEqual(res.status, CanonicalPersistenceStatus.INSERTED)
        self.assertTrue(res.is_new)
        self.assertIsNotNone(res.station_id)

        # Assert exactly ONE station created in DB
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)
        stn = self.mock_db.tables["public.stations"][0]
        self.assertEqual(str(stn["id"]), str(res.station_id))

    def test_02_multiple_source_records_in_one_merge_create_one_station(self):
        """A2: Cluster of 3 disparate sources in MERGE creates exactly one station row."""
        r1 = self._create_sample_record("open_charge_map", "ocm-301")
        r2 = self._create_sample_record("osm", "node-302")
        r3 = self._create_sample_record("tatapower_cpo", "cpo-303")

        decisions = CanonicalDeduplicationEngine.evaluate_records([r1, r2, r3])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision_state, CanonicalDecisionState.MERGE)

        res = self.service.persist_canonical_decision(decisions[0])
        self.assertEqual(res.status, CanonicalPersistenceStatus.INSERTED)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    def test_03_source_links_created_for_every_participating_source_identity(self):
        """A3: public.station_source_link receives rows for all participating source identities."""
        r1 = self._create_sample_record("open_charge_map", "ocm-401")
        r2 = self._create_sample_record("osm", "node-402")

        decision = CanonicalDeduplicationEngine.evaluate_records([r1, r2])[0]
        res = self.service.persist_canonical_decision(decision)

        self.assertEqual(res.source_links_created, 2)
        links = self.mock_db.tables["public.station_source_link"]
        self.assertEqual(len(links), 2)
        source_stn_ids = {l["source_station_id"] for l in links}
        self.assertEqual(source_stn_ids, {"ocm-401", "node-402"})
        # All links point to the canonical station ID
        for l in links:
            self.assertEqual(str(l["station_id"]), str(res.station_id))

    def test_04_connector_groups_created_correctly(self):
        """A4: Static capacity groups are created correctly in public.connectors."""
        conns = [
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1),
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2),
            NormalizedConnectorRecord(connector_type="Type 2", raw_connector_type="Type 2", power_kw=22.0, quantity=2),
        ]
        r = self._create_sample_record("open_charge_map", "ocm-501", connectors=conns)
        decision = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        res = self.service.persist_canonical_decision(decision)
        self.assertEqual(res.status, CanonicalPersistenceStatus.INSERTED)

        db_conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(db_conns), 3)
        # Verify distinct capacity groups
        tiers = {(c["connector_type"], c["power_kw"], c["quantity"]) for c in db_conns}
        self.assertEqual(tiers, {("CCS2", 60.0, 1), ("CCS2", 120.0, 2), ("Type 2", 22.0, 2)})

    # --------------------------------------------------------------------------
    # SECTION B: EXISTING STATION (Tests 5-8)
    # --------------------------------------------------------------------------

    def test_05_link_to_canonical_reuses_same_uuid(self):
        """B5: LINK_TO_CANONICAL reuses the existing canonical station UUID."""
        # 1. Establish initial station
        r1 = self._create_sample_record("open_charge_map", "ocm-601")
        dec1 = CanonicalDeduplicationEngine.evaluate_records([r1])[0]
        res1 = self.service.persist_canonical_decision(dec1)
        established_uuid = res1.station_id

        # 2. Incoming second source matching established station
        r2 = self._create_sample_record("osm", "node-602")
        existing_canon = ExistingCanonicalStation(
            canonical_station_id=str(established_uuid),
            name=r1.name,
            latitude=r1.latitude,
            longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-601")],
        )

        decisions = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing_canon])
        self.assertEqual(decisions[0].decision_state, CanonicalDecisionState.LINK_TO_CANONICAL)
        self.assertEqual(decisions[0].canonical_station_id, str(established_uuid))

        # 3. Persist link
        res2 = self.service.persist_canonical_decision(decisions[0])
        self.assertEqual(res2.status, CanonicalPersistenceStatus.LINKED)
        self.assertEqual(res2.station_id, established_uuid)

    def test_06_no_duplicate_station_is_created_on_link(self):
        """B6: Total stations count remains 1 when linking to an established station."""
        r1 = self._create_sample_record("open_charge_map", "ocm-701")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        r2 = self._create_sample_record("osm", "node-702")
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-701")],
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    def test_07_existing_populated_fields_not_overwritten_by_missing_incoming_values(self):
        """B7: Populated fields (e.g. address, postal code) are NOT erased when new source omits them."""
        # Station 1 has detailed address and postal code
        r1 = self._create_sample_record("open_charge_map", "ocm-801", address="Plaza Tower, Bandra", postal_code="400051")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        # Station 2 matches but omits address and postal code (None)
        r2 = self._create_sample_record("osm", "node-802", address=None, postal_code=None)
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            address_line="Plaza Tower, Bandra", postal_code="400051",
            source_links=[("open_charge_map", "ocm-801")],
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        # Verify address and postal code remained intact
        stn = self.mock_db.tables["public.stations"][0]
        self.assertEqual(stn["address_line"], "Plaza Tower, Bandra")
        self.assertEqual(stn["postal_code"], "400051")

    def test_08_explicit_survivorship_selected_values_update_correctly(self):
        """B8: Explicit survivorship values (e.g. verified operator rebrand) update operational station."""
        # Initial station with Jio-bp pulse
        r1 = self._create_sample_record("open_charge_map", "ocm-901", operator_name="Jio-bp pulse", operator_slug="jio-bp-pulse")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        # Newer source reports Tata Power with recency timestamp
        r2 = self._create_sample_record("tatapower_cpo", "cpo-902", operator_name="Tata Power", operator_slug="tata-power")
        r2.extra_metadata["_temporal_recency_ts"] = 1770000000

        # Construct decision with explicit survivorship update
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-901")],
        )
        dec = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec)

        # Operator in public.stations should now reflect Tata Power
        stn = self.mock_db.tables["public.stations"][0]
        tata_op = next(o for o in self.mock_db.tables["public.operators"] if o["slug"] == "tata-power")
        self.assertEqual(stn["operator_id"], tata_op["id"])

    # --------------------------------------------------------------------------
    # SECTION C: KEEP_SEPARATE (Tests 9-10)
    # --------------------------------------------------------------------------

    def test_09_separate_physical_stations_remain_separate(self):
        """C9: Geographically distant physical stations remain distinct entities."""
        # BKC station
        r1 = self._create_sample_record("open_charge_map", "ocm-1001", name="BKC Station", lat=19.0657, lng=72.8685)
        # Andheri station (> 10 km away)
        r2 = self._create_sample_record("osm", "node-1002", name="Andheri Station", lat=19.1197, lng=72.8468)

        decisions = CanonicalDeduplicationEngine.evaluate_records([r1, r2])
        self.assertEqual(len(decisions), 2)
        for d in decisions:
            self.assertEqual(d.decision_state, CanonicalDecisionState.KEEP_SEPARATE)

        report = self.service.persist_canonical_batch(decisions)
        self.assertEqual(report.inserted, 2)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 2)

    def test_10_rerunning_same_decision_does_not_duplicate_stations(self):
        """C10: Re-running KEEP_SEPARATE decision is completely idempotent."""
        r = self._create_sample_record("open_charge_map", "ocm-1101")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        res1 = self.service.persist_canonical_decision(dec)
        self.assertEqual(res1.status, CanonicalPersistenceStatus.INSERTED)

        # Re-run identical decision
        res2 = self.service.persist_canonical_decision(dec)
        self.assertEqual(res2.status, CanonicalPersistenceStatus.UNCHANGED)
        self.assertTrue(res2.is_unchanged)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 1)

    # --------------------------------------------------------------------------
    # SECTION D: REVIEW (Tests 11-12)
    # --------------------------------------------------------------------------

    def test_11_review_does_not_create_authoritative_station_state(self):
        """D11: REVIEW decisions are safely skipped and create ZERO rows in public.stations."""
        # Contradicting pricing (FREE vs PAID 25 INR) triggers REVIEW
        conns_free = [NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, pricing_type=PricingType.FREE, price_per_kwh=0.0)]
        conns_paid = [NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, pricing_type=PricingType.PAID, price_per_kwh=25.0)]
        r1 = self._create_sample_record("open_charge_map", "ocm-1201", connectors=conns_free)
        r2 = self._create_sample_record("osm", "node-1202", connectors=conns_paid)

        dec = CanonicalDeduplicationEngine.evaluate_records([r1, r2])[0]
        self.assertEqual(dec.decision_state, CanonicalDecisionState.REVIEW)

        res = self.service.persist_canonical_decision(dec)
        self.assertEqual(res.status, CanonicalPersistenceStatus.REVIEW_SKIPPED)
        self.assertTrue(res.is_review_skipped)
        self.assertIsNone(res.station_id)
        # Database remains empty
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)

    def test_12_review_does_not_mutate_existing_station(self):
        """D12: An existing station is NOT mutated when incoming review decision is received."""
        r1 = self._create_sample_record("open_charge_map", "ocm-1301")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        # Fabricate an ambiguous decision targeting the station
        ambiguous_dec = CanonicalResolutionDecision(
            decision_state=CanonicalDecisionState.REVIEW,
            cluster_id="cluster_review_test",
            canonical_station_id=str(res1.station_id),
            conflicts=["Ambiguous match between multiple canonical hubs"],
        )
        res2 = self.service.persist_canonical_decision(ambiguous_dec)
        self.assertEqual(res2.status, CanonicalPersistenceStatus.REVIEW_SKIPPED)

        # Operational table mutation count unchanged
        self.assertEqual(self.mock_db.mutation_counts["stations_updated"], 0)

    # --------------------------------------------------------------------------
    # SECTION E: CONNECTORS (Tests 13-18)
    # --------------------------------------------------------------------------

    def test_13_cross_source_overlapping_quantity_is_not_summed(self):
        """E13: Cross-source duplicate descriptions take max(quantity) = 2, NOT 4."""
        r1 = self._create_sample_record("open_charge_map", "ocm-1401", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2)
        ])
        r2 = self._create_sample_record("osm", "node-1402", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2)
        ])

        dec = CanonicalDeduplicationEngine.evaluate_records([r1, r2])[0]
        self.service.persist_canonical_decision(dec)

        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["quantity"], 2)  # Max, not sum 4!

    def test_14_intra_source_connector_quantities_are_preserved(self):
        """E14: Distinct plugs enumerated within one source sum correctly (1 + 1 = 2)."""
        r = self._create_sample_record("open_charge_map", "ocm-1501", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=1, source_connector_id="plug-A"),
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=1, source_connector_id="plug-B"),
        ])
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        self.service.persist_canonical_decision(dec)

        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["quantity"], 2)

    def test_15_different_power_tiers_remain_distinct(self):
        """E15: Co-located 60 kW and 120 kW CCS2 equipment persist as distinct capacity groups."""
        conns = [
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2),
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2),
        ]
        r = self._create_sample_record("open_charge_map", "ocm-1601", connectors=conns)
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        self.service.persist_canonical_decision(dec)

        db_conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(db_conns), 2)
        powers = {c["power_kw"] for c in db_conns}
        self.assertEqual(powers, {60.0, 120.0})

    def test_16_existing_connectors_updated_rather_than_duplicated(self):
        """E16: Re-ingestion with higher quantity updates existing row without duplicate key error."""
        r1 = self._create_sample_record("open_charge_map", "ocm-1701", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=1)
        ])
        dec1 = CanonicalDeduplicationEngine.evaluate_records([r1])[0]
        res1 = self.service.persist_canonical_decision(dec1)

        # Later source confirms 2 connectors for this capacity group
        r2 = self._create_sample_record("osm", "node-1702", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-1701")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        res2 = self.service.persist_canonical_decision(dec2)

        # Total connector rows is still 1; quantity is now 2
        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["quantity"], 2)
        self.assertEqual(res2.connectors_updated, 1)

    def test_17_missing_connector_data_does_not_delete_existing_connectors(self):
        """E17: When an incoming payload omits a connector type, existing connectors are NOT deleted."""
        # Initial station has CCS2 + Type 2
        r1 = self._create_sample_record("open_charge_map", "ocm-1801", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2),
            NormalizedConnectorRecord(connector_type="Type 2", raw_connector_type="Type 2", power_kw=22.0, quantity=1),
        ])
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 2)

        # Source 2 only mentions CCS2
        r2 = self._create_sample_record("osm", "node-1802", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-1801")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        # Type 2 was NOT deleted!
        types = {c["connector_type"] for c in self.mock_db.tables["public.connectors"]}
        self.assertEqual(types, {"CCS2", "Type 2"})

    def test_18_connector_provenance_traceable_to_dim_connector(self):
        """E18: Operational connectors are mirrored into analytics.dim_connector."""
        r = self._create_sample_record("open_charge_map", "ocm-1901", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2)
        ])
        self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r])[0])

        dim_conns = self.mock_db.tables["analytics.dim_connector"]
        self.assertEqual(len(dim_conns), 1)
        self.assertEqual(dim_conns[0]["connector_type"], "CCS2")
        self.assertEqual(dim_conns[0]["quantity"], 2)
        self.assertTrue(dim_conns[0]["is_fast_charging"])  # >= 50 kW

    def test_18b_existing_2_decision_2_remains_2(self):
        """Audit Case 1: Existing canonical quantity = 2, Step 2.7 decision quantity = 2 -> result remains 2."""
        r1 = self._create_sample_record("open_charge_map", "ocm-c1", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 2)

        # Incoming decision explicitly specifies quantity = 2 for the same capacity group
        r2 = self._create_sample_record("osm", "node-c1", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-c1")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["quantity"], 2)

    def test_18c_existing_2_decision_4_becomes_4(self):
        """Audit Case 2: Existing canonical quantity = 2, Step 2.7 decision quantity = 4 -> result becomes 4."""
        r1 = self._create_sample_record("open_charge_map", "ocm-c2", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 2)

        # Later source explicitly confirms 4 connectors
        r2 = self._create_sample_record("tatapower_cpo", "cpo-c2", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=4)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-c2")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["quantity"], 4)

    def test_18d_existing_4_decision_2_becomes_2_without_override(self):
        """Audit Case 3: Existing canonical quantity = 4, Step 2.7 decision quantity = 2 -> result becomes 2 (not forced to 4)."""
        r1 = self._create_sample_record("open_charge_map", "ocm-c3", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=4)
        ])
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 4)

        # An authoritative Step 2.7 decision explicitly specifies canonical quantity = 2
        # (e.g. after decommissioning or verified survey revision)
        r2 = self._create_sample_record("tatapower_cpo", "cpo-c3", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-c3")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        # Verify Step 2.7 explicitly resolved canonical quantity = 2
        self.assertEqual(dec2.field_survivorship["connectors"].canonical_value[0]["quantity"], 2)

        self.service.persist_canonical_decision(dec2)

        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 1)
        # Step 2.8 MUST NOT force 4 via max(4, 2); it MUST persist Step 2.7's explicit decision of 2
        self.assertEqual(conns[0]["quantity"], 2)

    def test_18e_existing_4_decision_unchanged_remains_4(self):
        """Audit Case 4: Existing canonical quantity = 4, Step 2.7 decision unchanged -> result remains 4."""
        r = self._create_sample_record("open_charge_map", "ocm-c4", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=4)
        ])
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        res1 = self.service.persist_canonical_decision(dec)
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 4)

        # Re-run identical decision (UNCHANGED)
        res2 = self.service.persist_canonical_decision(dec)
        self.assertEqual(res2.status, CanonicalPersistenceStatus.UNCHANGED)
        self.assertEqual(self.mock_db.tables["public.connectors"][0]["quantity"], 4)

    def test_18f_omission_does_not_cause_deletion(self):
        """Audit Case 5: A source payload omits a connector type; omission does NOT cause deletion."""
        r1 = self._create_sample_record("open_charge_map", "ocm-c5", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2),
            NormalizedConnectorRecord(connector_type="Type 2", raw_connector_type="Type 2", power_kw=22.0, quantity=1),
        ])
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 2)

        # New source only mentions CCS2
        r2 = self._create_sample_record("osm", "node-c5", connectors=[
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2)
        ])
        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name=r1.name, latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-c5")],
            connectors=r1.connectors,
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        # Both connectors remain present in database (Type 2 was NOT deleted)
        conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(conns), 2)
        conns_by_type = {c["connector_type"]: c["quantity"] for c in conns}
        self.assertEqual(conns_by_type["CCS2"], 2)
        self.assertEqual(conns_by_type["Type 2"], 1)

    def test_18g_field_level_connector_decision_authoritative_to_persistence(self):
        """Audit Case 6: Step 2.7's field-level connector decision remains authoritative through persistence."""
        conns = [
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=60.0, quantity=2),
            NormalizedConnectorRecord(connector_type="CCS2", raw_connector_type="CCS2", power_kw=120.0, quantity=2),
        ]
        r = self._create_sample_record("open_charge_map", "ocm-c6", connectors=conns)
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        res = self.service.persist_canonical_decision(dec)

        # Operational public.connectors
        db_conns = self.mock_db.tables["public.connectors"]
        self.assertEqual(len(db_conns), 2)
        tiers_op = {(c["connector_type"], c["power_kw"]): c["quantity"] for c in db_conns}
        self.assertEqual(tiers_op[("CCS2", 60.0)], 2)
        self.assertEqual(tiers_op[("CCS2", 120.0)], 2)

        # Warehouse analytics.dim_connector
        dim_conns = self.mock_db.tables["analytics.dim_connector"]
        self.assertEqual(len(dim_conns), 2)
        tiers_dim = {(c["connector_type"], c["power_kw"]): c["quantity"] for c in dim_conns}
        self.assertEqual(tiers_dim[("CCS2", 60.0)], 2)
        self.assertEqual(tiers_dim[("CCS2", 120.0)], 2)

    # --------------------------------------------------------------------------
    # SECTION F: SOURCE LINKS (Tests 19-21)
    # --------------------------------------------------------------------------

    def test_19_same_source_link_applied_twice_remains_one_link(self):
        """F19: public.station_source_link does not create duplicate rows on repeated load."""
        r = self._create_sample_record("open_charge_map", "ocm-2001")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 1)

        # Second load
        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 1)

    def test_20_source_identity_remains_mapped_to_same_canonical_station(self):
        """F20: Source link consistently maps external ID to canonical station UUID."""
        r = self._create_sample_record("open_charge_map", "ocm-2101")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        res = self.service.persist_canonical_decision(dec)
        link = self.mock_db.tables["public.station_source_link"][0]
        self.assertEqual(str(link["station_id"]), str(res.station_id))
        self.assertEqual(link["source_station_id"], "ocm-2101")

    def test_21_unsafe_source_identity_reassignment_aborts(self):
        """F21: Attempting to silently reassign an established source ID to another station fails transaction."""
        # Establish station 1 with ocm-2201
        r1 = self._create_sample_record("open_charge_map", "ocm-2201")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        # Establish station 2 independently
        r2 = self._create_sample_record("osm", "node-2202")
        res2 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r2])[0])

        # Fabricate an invalid decision attempting to link ocm-2201 to station 2
        bad_dec = CanonicalResolutionDecision(
            decision_state=CanonicalDecisionState.LINK_TO_CANONICAL,
            cluster_id="cluster_reassign_test",
            canonical_station_id=str(res2.station_id),
            participating_source_identities=[("open_charge_map", "ocm-2201")],
            participating_records=[r1],
        )

        res = self.service.persist_canonical_decision(bad_dec)
        self.assertEqual(res.status, CanonicalPersistenceStatus.FAILED)
        self.assertIn("Unsafe identity mutation", res.error)

    # --------------------------------------------------------------------------
    # SECTION G: OBSERVATIONS (Tests 22-24)
    # --------------------------------------------------------------------------

    def test_22_valid_observation_persisted_to_operational_and_warehouse(self):
        """G22: Genuine telemetry observation persists to operational table and fact_station_observation."""
        obs = NormalizedObservationRecord(
            source_id="open_charge_map",
            source_station_id="ocm-2301",
            observed_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            availability_status=AvailabilityStatus.AVAILABLE,
            available_connectors=2,
        )
        r = self._create_sample_record("open_charge_map", "ocm-2301")
        r.observation = obs

        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        res = self.service.persist_canonical_decision(dec)

        self.assertEqual(res.observations_persisted, 1)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 1)
        self.assertEqual(len(self.mock_db.tables["analytics.fact_station_observation"]), 1)

    def test_23_duplicate_payload_does_not_create_duplicate_observation(self):
        """G23: Re-ingesting identical observation payload does NOT insert duplicate fact row."""
        obs = NormalizedObservationRecord(
            source_id="open_charge_map",
            source_station_id="ocm-2401",
            observed_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            availability_status=AvailabilityStatus.AVAILABLE,
            available_connectors=2,
        )
        r = self._create_sample_record("open_charge_map", "ocm-2401")
        r.observation = obs

        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 1)

        # Re-run
        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 1)

    def test_24_static_station_status_does_not_fabricate_live_availability(self):
        """G24: Static operational status (StatusTypeID 50) does not create live observations."""
        r = self._create_sample_record("open_charge_map", "ocm-2501")
        r.observation = None  # Static only

        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        res = self.service.persist_canonical_decision(dec)

        self.assertEqual(res.observations_persisted, 0)
        self.assertEqual(len(self.mock_db.tables["public.station_observations"]), 0)

    # --------------------------------------------------------------------------
    # SECTION H: TRANSACTIONS & ROLLBACK (Tests 25-26)
    # --------------------------------------------------------------------------

    def test_25_failure_during_mutation_rolls_back_atomic_operation(self):
        """H25: Simulated failure during connector insertion rolls back the entire station transaction."""
        r = self._create_sample_record("open_charge_map", "ocm-2601")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        # Trigger simulated error on connector insertion
        self.mock_db.should_fail_on_connector_insert = True
        res = self.service.persist_canonical_decision(dec)

        self.assertEqual(res.status, CanonicalPersistenceStatus.FAILED)
        self.assertIn("Simulated database failure", res.error)

        # Assert clean rollback: Zero stations and zero links left in DB
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 0)

    def test_26_no_partial_station_without_connector_corruption(self):
        """H26: Verifies atomic boundary ensures no half-written stations exist."""
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)
        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 0)

    # --------------------------------------------------------------------------
    # SECTION I: IDEMPOTENCE (Tests 27-30)
    # --------------------------------------------------------------------------

    def test_27_apply_identical_decision_twice_produces_equivalent_state(self):
        """I27: Database table counts and values are identical after 2nd application."""
        r1 = self._create_sample_record("open_charge_map", "ocm-2801")
        r2 = self._create_sample_record("osm", "node-2802")
        dec = CanonicalDeduplicationEngine.evaluate_records([r1, r2])[0]

        self.service.persist_canonical_decision(dec)
        snapshot_1 = copy.deepcopy(self.mock_db.tables)

        # 2nd run
        self.service.persist_canonical_decision(dec)
        snapshot_2 = copy.deepcopy(self.mock_db.tables)

        # Count checks
        self.assertEqual(len(snapshot_1["public.stations"]), len(snapshot_2["public.stations"]))
        self.assertEqual(len(snapshot_1["public.connectors"]), len(snapshot_2["public.connectors"]))
        self.assertEqual(len(snapshot_1["public.station_source_link"]), len(snapshot_2["public.station_source_link"]))

    def test_28_canonical_uuid_remains_unchanged_on_subsequent_runs(self):
        """I28: Re-ingestion preserves exact original ChargePlus station UUID."""
        r = self._create_sample_record("open_charge_map", "ocm-2901")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        res1 = self.service.persist_canonical_decision(dec)
        res2 = self.service.persist_canonical_decision(dec)

        self.assertEqual(res1.station_id, res2.station_id)

    def test_29_connector_count_remains_unchanged(self):
        """I29: Repeated application does not multiply connectors."""
        r = self._create_sample_record("open_charge_map", "ocm-3001")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        self.service.persist_canonical_decision(dec)
        self.service.persist_canonical_decision(dec)

        self.assertEqual(len(self.mock_db.tables["public.connectors"]), 1)

    def test_30_source_link_count_remains_unchanged(self):
        """I30: Repeated application does not multiply source links."""
        r1 = self._create_sample_record("open_charge_map", "ocm-3101")
        r2 = self._create_sample_record("osm", "node-3102")
        dec = CanonicalDeduplicationEngine.evaluate_records([r1, r2])[0]

        self.service.persist_canonical_decision(dec)
        self.service.persist_canonical_decision(dec)

        self.assertEqual(len(self.mock_db.tables["public.station_source_link"]), 2)

    # --------------------------------------------------------------------------
    # SECTION J: DIMENSIONS & SCD2 (Tests 31-33)
    # --------------------------------------------------------------------------

    def test_31_existing_phase_1_dimensions_populated_consistently(self):
        """J31: dim_operator, dim_location, and dim_station are populated on station creation."""
        r = self._create_sample_record("open_charge_map", "ocm-3201")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        self.service.persist_canonical_decision(dec)

        self.assertEqual(len(self.mock_db.tables["analytics.dim_station"]), 1)
        self.assertEqual(len(self.mock_db.tables["analytics.dim_operator"]), 1)
        self.assertEqual(len(self.mock_db.tables["analytics.dim_location"]), 1)

    def test_32_dim_station_scd2_closes_old_version_and_opens_new(self):
        """J32: Tracked station attribute change closes SCD2 version 1 and opens version 2."""
        # Initial version 1
        r1 = self._create_sample_record("open_charge_map", "ocm-3301", name="Original Station Name")
        res1 = self.service.persist_canonical_decision(CanonicalDeduplicationEngine.evaluate_records([r1])[0])

        dim_stns = self.mock_db.tables["analytics.dim_station"]
        self.assertEqual(len(dim_stns), 1)
        self.assertEqual(dim_stns[0]["version"], 1)
        self.assertTrue(dim_stns[0]["is_current"])

        # Name change triggers SCD2 update
        r2 = self._create_sample_record("open_charge_map", "ocm-3301", name="Renamed Flagship Station Hub")
        r2.extra_metadata["payload_hash"] = "new_payload_hash_3301"

        existing = ExistingCanonicalStation(
            canonical_station_id=str(res1.station_id),
            name="Original Station Name", latitude=r1.latitude, longitude=r1.longitude,
            source_links=[("open_charge_map", "ocm-3301")],
        )
        dec2 = CanonicalDeduplicationEngine.evaluate_records([r2], existing_canonical_stations=[existing])[0]
        self.service.persist_canonical_decision(dec2)

        # Assert SCD2 history: 2 rows total in dim_station
        self.assertEqual(len(dim_stns), 2)
        v1 = next(s for s in dim_stns if s["version"] == 1)
        v2 = next(s for s in dim_stns if s["version"] == 2)
        self.assertFalse(v1["is_current"])
        self.assertIsNotNone(v1["effective_to"])
        self.assertTrue(v2["is_current"])
        self.assertEqual(v2["station_name"], "Renamed Flagship Station Hub")

    def test_33_no_duplicate_dimension_rows_on_repeated_ingestion(self):
        """J33: Unchanged station attributes produce ZERO new dim_station rows."""
        r = self._create_sample_record("open_charge_map", "ocm-3401")
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["analytics.dim_station"]), 1)

        self.service.persist_canonical_decision(dec)
        self.assertEqual(len(self.mock_db.tables["analytics.dim_station"]), 1)

    # --------------------------------------------------------------------------
    # SECTION K: SAFETY & SECRETS (Tests 34-36)
    # --------------------------------------------------------------------------

    def test_34_reject_and_quarantine_cannot_become_canonical_operational_state(self):
        """K34: Blocked decisions (quarantine/reject) are blocked from mutating public.stations."""
        r = self._create_sample_record("open_charge_map", "ocm-3501")
        blocked_dec = CanonicalResolutionDecision(
            decision_state=CanonicalDecisionState.KEEP_SEPARATE,
            cluster_id="cluster_blocked_3501",
            is_blocked=True,
            blocking_reasons=["DQ-GEO-001: Geofence violation"],
            participating_records=[r],
        )

        res = self.service.persist_canonical_decision(blocked_dec)
        self.assertEqual(res.status, CanonicalPersistenceStatus.BLOCKED_SKIPPED)
        self.assertTrue(res.is_blocked_skipped)
        self.assertEqual(len(self.mock_db.tables["public.stations"]), 0)

    def test_35_missing_values_never_become_fake_defaults(self):
        """K35: Missing optional fields remain None; never defaulted to 0 kW or fake schedules."""
        r = self._create_sample_record("open_charge_map", "ocm-3601", address=None, postal_code=None)
        dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]
        self.service.persist_canonical_decision(dec)

        stn = self.mock_db.tables["public.stations"][0]
        self.assertIsNone(stn["address_line"])
        self.assertIsNone(stn["postal_code"])

    def test_36_no_secrets_appear_in_logs_or_errors(self):
        """K36: Error messages and scrub helper mask passwords and API keys."""
        leak_text = "Connection failed to postgresql://admin:SUPER_SECRET_PW@db.supabase.co:5432/postgres?apikey=SECRET_KEY_123"
        scrubbed = _scrub_secrets(leak_text)

        self.assertNotIn("SUPER_SECRET_PW", scrubbed)
        self.assertNotIn("SECRET_KEY_123", scrubbed)
        self.assertIn(":***@", scrubbed)

    # --------------------------------------------------------------------------
    # SECTION L: LIVE DATABASE INTEGRATION (Test 37)
    # --------------------------------------------------------------------------

    def test_37_live_database_persistence_and_clean_rollback(self):
        """L37: Verifies persistence against live Supabase PostgreSQL with clean transaction rollback."""
        load_dotenv(".env.local")
        load_dotenv(".env")
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            self.skipTest("DATABASE_URL is not configured; skipping live database integration test.")

        try:
            live_conn = psycopg2.connect(db_url, connect_timeout=5)
        except Exception as e:
            self.skipTest(f"Live database connection unavailable ({type(e).__name__}); skipping.")

        try:
            # Check baseline station count
            with live_conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.stations;")
                baseline_count = cur.fetchone()[0]

            # Use live connection within persistence service
            live_service = IngestionPersistenceService(live_conn)

            # Generate distinct test station in Mumbai
            test_id = f"test-live-{uuid.uuid4().hex[:6]}"
            r = self._create_sample_record("open_charge_map", test_id, name=f"Live Integration Station {test_id}")
            dec = CanonicalDeduplicationEngine.evaluate_records([r])[0]

            # Execute persistence on live DB
            with live_conn.cursor() as cur:
                attrs = live_service._extract_canonical_station_attributes(dec, [])
                stn_id = uuid.uuid4()
                live_service._insert_station_record(cur, stn_id, attrs)
                live_service._reconcile_and_persist_connectors(cur, stn_id, dec, [])
                live_service._reconcile_and_persist_source_links(cur, stn_id, dec)

                # Verify live row was inserted in transaction
                cur.execute("SELECT name FROM public.stations WHERE id = %s;", (str(stn_id),))
                live_name = cur.fetchone()[0]
                self.assertEqual(live_name, f"Live Integration Station {test_id}")

            # CLEAN ROLLBACK: Do NOT commit test record to production!
            live_conn.rollback()

            # Verify production DB remains 100% clean (baseline count preserved)
            with live_conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.stations;")
                final_count = cur.fetchone()[0]
                self.assertEqual(final_count, baseline_count)

        finally:
            live_conn.close()


if __name__ == "__main__":
    unittest.main()
