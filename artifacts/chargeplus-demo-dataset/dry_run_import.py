import csv, json, os, re

OUT = os.path.dirname(os.path.abspath(__file__))
def env():
    env={}
    for line in open("D:/Desktop/Projects/ChargePlus/.env.local",encoding="utf-8"):
        m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*"(.*)"\s*$',line)
        if m: env[m.group(1)]=m.group(2)
    return env

def load(name):
    with open(os.path.join(OUT,name),newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))

import psycopg2
e=env()
conn=psycopg2.connect(e["DATABASE_URL"])
conn.set_session(readonly=True)
cur=conn.cursor()

excluded = ["profiles.csv","favorites.csv","reviews.csv","user_reports.csv","alerts.csv"]
importable = ["data_sources.csv","operators.csv","stations.csv","connectors.csv","station_source_link.csv","station_observations.csv","ingestion_runs.csv","dim_date.csv","dim_location.csv","dim_station.csv","dim_tariff.csv","dim_time.csv","dim_vehicle.csv","dim_weather.csv","fact_charging_session.csv","fact_station_daily_agg.csv"]

# existing ids
def existing(table,col):
    cur.execute(f"SELECT {col} FROM public.{table}")
    return set(str(r[0]) for r in cur.fetchall())

report = {"excluded_files": excluded, "tables": {}, "provenance": {}}

# provenance check: any demo marker columns?
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='stations'")
station_cols = [r[0] for r in cur.fetchall()]
report["provenance"]["stations_has_demo_marker"] = any("demo" in c or "provenance" in c or "is_simulated" in c for c in station_cols)
report["provenance"]["station_columns"] = station_cols

# PK conflict map
pk_map = {
 "data_sources.csv": ("data_sources","id"),
 "operators.csv": ("operators","id"),
 "stations.csv": ("stations","id"),
 "connectors.csv": ("connectors","id"),
 "station_source_link.csv": ("station_source_link","id"),
 "station_observations.csv": ("station_observations","id"),
 "ingestion_runs.csv": ("ingestion_runs","id"),
}

for fn in importable:
    rows = load(fn)
    table = fn.replace(".csv","")
    # map table name special
    tname = {
     "dim_date":"dim_date","dim_location":"dim_location","dim_station":"dim_station","dim_tariff":"dim_tariff","dim_time":"dim_time","dim_vehicle":"dim_vehicle","dim_weather":"dim_weather","fact_charging_session":"fact_charging_session","fact_station_daily_agg":"fact_station_daily_agg",
    }.get(table, table)
    # pk
    pk = None
    if fn in pk_map:
        t,pk = pk_map[fn]
        ex = existing(t,pk)
        conflicts = [r[pk] for r in rows if r[pk] in ex]
    else:
        conflicts = []
    report["tables"][fn] = {
        "rows": len(rows),
        "pk_conflicts_with_remote": len(conflicts),
        "sample_conflicts": conflicts[:5],
        "intended_inserts": len(rows)-len(conflicts),
    }

# FK local checks
stations = load("stations.csv")
station_ids = set(r["id"] for r in stations)
connectors = load("connectors.csv")
bad = [r["id"] for r in connectors if r["station_id"] not in station_ids]
report["fk_checks"] = {"connectors_orphan": len(bad)}

obs = load("station_observations.csv")
bad2 = [r["id"] for r in obs if r["station_id"] not in station_ids]
report["fk_checks"]["obs_station_orphan"] = len(bad2)
bad3 = [r["id"] for r in obs if r["connector_id"] not in set(r2["id"] for r2 in connectors) and r["connector_id"]!=""]
report["fk_checks"]["obs_connector_orphan"] = len(bad3)

cur.close()
conn.close()

# write report
with open(os.path.join(OUT,"dry_run_report.json"),"w",encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
