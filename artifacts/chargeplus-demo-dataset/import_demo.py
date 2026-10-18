import csv, os, json, re, psycopg2
from psycopg2.extras import execute_values

OUT = os.path.dirname(os.path.abspath(__file__))
def env():
    e={}
    for line in open("D:/Desktop/Projects/ChargePlus/.env.local",encoding="utf-8"):
        m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*"(.*)"\s*$',line)
        if m: e[m.group(1)]=m.group(2)
    return e
def load(name):
    with open(os.path.join(OUT,name),newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))
def n(v):
    v=(v or "").strip()
    return v if v not in ("","None","null") else None
def b(v):
    v=(v or "").strip().lower()
    if v in ("true","t","1","yes"): return True
    if v in ("false","f","0","no",""): return False
    return None

e=env()
conn=psycopg2.connect(e["DATABASE_URL"])
conn.autocommit=False
cur=conn.cursor()

counts={"read":{},"inserted":{},"skipped":{},"rejected":{}}

def bulk(table, cols, rows, cast=None):
    if not rows:
        counts["inserted"][table]=0; counts["skipped"][table]=0; return
    cast = cast or {}
    sql_cols = ", ".join(cols)
    placeholders = ", ".join([cast.get(c,"%s") for c in cols])
    sql = f"INSERT INTO public.{table} ({sql_cols}) VALUES %s ON CONFLICT DO NOTHING"
    # execute_values needs template
    template = "(" + ", ".join([cast.get(c,"%s") for c in cols]) + ")"
    try:
        cur.execute(f"SELECT count(*) FROM public.{table}")
        before = cur.fetchone()[0]
        execute_values(cur, f"INSERT INTO public.{table} ({sql_cols}) VALUES %s ON CONFLICT DO NOTHING", rows, template=template, page_size=1000)
        cur.execute(f"SELECT count(*) FROM public.{table}")
        after = cur.fetchone()[0]
        inserted = after - before
        counts["inserted"][table]=inserted
        counts["skipped"][table]=len(rows)-inserted
    except Exception as ex:
        conn.rollback()
        raise
    counts["inserted"][table]=inserted
    counts["skipped"][table]=len(rows)-inserted

# data_sources
rows=[]
for r in load("data_sources.csv"):
    rows.append((r["id"], r["name"], r["source_type"], n(r["base_url"]), int(r["source_priority"]), b(r["is_active"]), n(r["created_at"])))
bulk("data_sources", ["id","name","source_type","base_url","source_priority","is_active","created_at"], rows)
print("data_sources inserted", counts["inserted"]["data_sources"], flush=True)
# operators
rows=[]
for r in load("operators.csv"):
    rows.append((r["id"], r["name"], n(r["slug"]), n(r["website_url"]), n(r["support_phone"]), n(r["created_at"]), n(r["updated_at"]), True))
bulk("operators", ["id","name","slug","website_url","support_phone","created_at","updated_at","is_simulated"], rows)
# stations
rows=[]
for r in load("stations.csv"):
    rows.append((r["id"], n(r["slug"]), r["name"], r["operator_id"], n(r["address_line"]), n(r["locality"]), r["city"], r["state"], n(r["postal_code"]), r["country"], float(r["latitude"]), float(r["longitude"]), f"SRID=4326;{r['geom']}" if n(r["geom"]) else None, n(r["opening_time"]), n(r["closing_time"]), b(r["is_24_hours"]), n(r["access_type"]), b(r["is_public"]), r["operational_status"], n(r["phone"]), n(r["website_url"]), n(r["last_verified_at"]), n(r["created_at"]), n(r["updated_at"]), True))
# geom needs ST_GeomFromText; use special handling
geom_cast = {"geom":"ST_GeomFromText(%s,4326)"}
# execute manually
sql = "INSERT INTO public.stations (id,slug,name,operator_id,address_line,locality,city,state,postal_code,country,latitude,longitude,geom,opening_time,closing_time,is_24_hours,access_type,is_public,operational_status,phone,website_url,last_verified_at,created_at,updated_at,is_simulated) VALUES %s ON CONFLICT DO NOTHING"
template = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
cur.execute("SELECT count(*) FROM public.stations")
before_st = cur.fetchone()[0]
execute_values(cur, sql, rows, template=template, page_size=500)
cur.execute("SELECT count(*) FROM public.stations")
after_st = cur.fetchone()[0]
counts["inserted"]["stations"]=after_st-before_st
counts["skipped"]["stations"]=len(rows)-(after_st-before_st)
print("stations inserted", counts["inserted"].get("stations"), "skipped", counts["skipped"]["stations"], flush=True)
# connectors
rows=[]
for r in load("connectors.csv"):
    rows.append((r["id"], r["station_id"], r["connector_type"], n(r["charging_standard"]), n(r["power_kw"]) and float(r["power_kw"]) or None, int(r["quantity"]), r["pricing_type"], n(r["price_per_kwh"]) and float(r["price_per_kwh"]) or None, n(r["price_per_session"]) and float(r["price_per_session"]) or None, r["currency"], n(r["created_at"]), n(r["updated_at"]), n(r["price_estimate_per_kwh"]) and float(r["price_estimate_per_kwh"]) or None, n(r["price_estimate_raw"]), n(r["price_estimate_source"]), True))
bulk("connectors", ["id","station_id","connector_type","charging_standard","power_kw","quantity","pricing_type","price_per_kwh","price_per_session","currency","created_at","updated_at","price_estimate_per_kwh","price_estimate_raw","price_estimate_source","is_simulated"], rows)
print("connectors inserted", counts["inserted"]["connectors"], flush=True)
# station_source_link
rows=[]
for r in load("station_source_link.csv"):
    rows.append((r["id"], r["station_id"], r["source_id"], r["source_station_id"], n(r["source_url"]), n(r["first_seen_at"]), n(r["last_seen_at"]), n(r["last_ingested_at"]), n(r["source_payload_hash"]), b(r["is_active"]), n(r["created_at"]), n(r["updated_at"]), True))
bulk("station_source_link", ["id","station_id","source_id","source_station_id","source_url","first_seen_at","last_seen_at","last_ingested_at","source_payload_hash","is_active","created_at","updated_at","is_simulated"], rows)
print("ssl inserted", counts["inserted"]["station_source_link"], flush=True)
# station_observations
inserted_connectors = set()
cur.execute("SELECT id FROM public.connectors")
inserted_connectors = set(str(x[0]) for x in cur.fetchall())
rows=[]
for r in load("station_observations.csv"):
    cid = n(r["connector_id"])
    if cid is not None and cid not in inserted_connectors:
        cid = None
    rows.append((r["id"], r["station_id"], cid, r["source_id"], r["availability_status"], r["queue_level"], n(r["available_connectors"]) and int(r["available_connectors"]) or None, int(r["total_connectors"]), n(r["observed_at"]), n(r["received_at"]), n(r["confidence_score"]) and float(r["confidence_score"]) or None, n(r["source_payload_hash"]), n(r["created_at"]), True))
bulk("station_observations", ["id","station_id","connector_id","source_id","availability_status","queue_level","available_connectors","total_connectors","observed_at","received_at","confidence_score","source_payload_hash","created_at","is_simulated"], rows)
# ingestion_runs
rows=[]
for r in load("ingestion_runs.csv"):
    rows.append((r["id"], n(r["source_id"]), r["source_name"], r["scope"], r["state"], n(r["started_at"]), n(r["completed_at"]), n(r["duration_seconds"]) and float(r["duration_seconds"]) or None, int(r["attempt_count"]), int(r["records_fetched"]), int(r["records_parsed"]), int(r["records_accepted"]), int(r["records_accepted_with_warnings"]), int(r["records_quarantined"]), int(r["records_rejected"]), int(r["stations_persisted"]), int(r["stations_updated"]), int(r["stations_unchanged"]), int(r["connectors_persisted"]), int(r["observations_persisted"]), n(r["error_summary"]), n(r["metadata"]), n(r["created_at"]), True))
bulk("ingestion_runs", ["id","source_id","source_name","scope","state","started_at","completed_at","duration_seconds","attempt_count","records_fetched","records_parsed","records_accepted","records_accepted_with_warnings","records_quarantined","records_rejected","stations_persisted","stations_updated","stations_unchanged","connectors_persisted","observations_persisted","error_summary","metadata","created_at","is_simulated"], rows, cast={"metadata":"%s::jsonb"})
# operators already inserted with is_simulated True; but operators.csv may conflict? done.
# dim tables
def bulk_dim(table, cols, rows):
    bulk(table, cols, rows)
# dim_date
rows=[]
for r in load("dim_date.csv"):
    rows.append((int(r["date_key"]), r["full_date"], int(r["day_of_week"]), r["day_name"], int(r["month"]), r["month_name"], int(r["quarter"]), int(r["year"]), b(r["is_weekend"]), b(r["is_holiday"]) if n(r["is_holiday"]) is not None else None, r["season"]))
bulk_dim("dim_date", ["date_key","full_date","day_of_week","day_name","month","month_name","quarter","year","is_weekend","is_holiday","season"], rows)
# dim_location
rows=[]
for r in load("dim_location.csv"):
    rows.append((int(r["location_key"]), r["location_id"], r["city"], r["zone_name"], r["area_type"], float(r["latitude"]), float(r["longitude"]), n(r["grid_substation_id"])))
bulk_dim("dim_location", ["location_key","location_id","city","zone_name","area_type","latitude","longitude","grid_substation_id"], rows)
# dim_station
rows=[]
for r in load("dim_station.csv"):
    rows.append((int(r["station_key"]), r["station_id"], r["station_name"], r["operator"], r["charger_type"], int(r["num_ports"]), float(r["max_power_kw"]), r["installation_date"], r["effective_start_date"], n(r["effective_end_date"]), b(r["is_current"])))
bulk_dim("dim_station", ["station_key","station_id","station_name","operator","charger_type","num_ports","max_power_kw","installation_date","effective_start_date","effective_end_date","is_current"], rows)
# dim_tariff
rows=[]
for r in load("dim_tariff.csv"):
    rows.append((int(r["tariff_key"]), r["tariff_id"], r["tariff_name"], r["tier_type"], float(r["rate_per_kwh"])))
bulk_dim("dim_tariff", ["tariff_key","tariff_id","tariff_name","tier_type","rate_per_kwh"], rows)
# dim_time
rows=[]
for r in load("dim_time.csv"):
    rows.append((int(r["time_key"]), int(r["hour"]), int(r["minute"]), r["time_slot"], b(r["is_peak_hours"])))
bulk_dim("dim_time", ["time_key","hour","minute","time_slot","is_peak_hours"], rows)
# dim_vehicle
rows=[]
for r in load("dim_vehicle.csv"):
    rows.append((int(r["vehicle_key"]), r["vehicle_id"], r["make"], r["model"], r["vehicle_type"], float(r["battery_capacity_kwh"]), float(r["max_charge_rate_kw"])))
bulk_dim("dim_vehicle", ["vehicle_key","vehicle_id","make","model","vehicle_type","battery_capacity_kwh","max_charge_rate_kw"], rows)
# dim_weather
rows=[]
for r in load("dim_weather.csv"):
    rows.append((int(r["weather_key"]), r["weather_id"], float(r["temperature_celsius"]), int(r["humidity_pct"]), float(r["rainfall_mm"]), r["weather_condition"]))
bulk_dim("dim_weather", ["weather_key","weather_id","temperature_celsius","humidity_pct","rainfall_mm","weather_condition"], rows)
# fact sessions
rows=[]
for r in load("fact_charging_session.csv"):
    rows.append((int(r["session_key"]), r["session_id"], int(r["station_key"]), int(r["location_key"]), int(r["vehicle_key"]), int(r["date_key"]), int(r["time_key"]), int(r["weather_key"]), int(r["tariff_key"]), r["start_timestamp"], r["end_timestamp"], float(r["duration_minutes"]), float(r["energy_consumed_kwh"]), float(r["peak_power_kw"]), float(r["session_cost"]), int(r["queue_time_minutes"]), int(r["idle_time_minutes"]), n(r["created_at"])))
bulk_dim("fact_charging_session", ["session_key","session_id","station_key","location_key","vehicle_key","date_key","time_key","weather_key","tariff_key","start_timestamp","end_timestamp","duration_minutes","energy_consumed_kwh","peak_power_kw","session_cost","queue_time_minutes","idle_time_minutes","created_at"], rows)
# fact daily agg
rows=[]
for r in load("fact_station_daily_agg.csv"):
    rows.append((int(r["agg_id"]), int(r["station_key"]), int(r["date_key"]), int(r["location_key"]), int(r["total_sessions"]), float(r["total_energy_kwh"]), float(r["total_revenue"]), float(r["avg_duration_minutes"]), float(r["avg_queue_time_minutes"]), float(r["utilization_rate_pct"])))
bulk_dim("fact_station_daily_agg", ["agg_id","station_key","date_key","location_key","total_sessions","total_energy_kwh","total_revenue","avg_duration_minutes","avg_queue_time_minutes","utilization_rate_pct"], rows)

conn.commit()
# write report
rep = {"inserted":counts["inserted"],"skipped":counts["skipped"]}
json.dump(rep, open(os.path.join(OUT,"import_report.json"),"w"), indent=2)
print(json.dumps(rep, indent=2))
cur.close()
conn.close()
