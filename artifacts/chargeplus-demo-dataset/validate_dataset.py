import csv, json, os, hashlib, glob

OUT = os.path.dirname(os.path.abspath(__file__))
def load(name):
    with open(os.path.join(OUT,name), newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)

# counts
files = sorted(glob.glob(os.path.join(OUT,'*.csv')))
manifest = {}
total = 0
for f in files:
    with open(f,newline='',encoding='utf-8') as fh:
        rows = list(csv.reader(fh))
    manifest[os.path.basename(f)] = len(rows)-1
    total += len(rows)-1

report = {"total_rows": total, "files": manifest, "checks": {}}

def check(name, ok, detail):
    report["checks"][name] = {"pass": bool(ok), "detail": detail}

# duplicate PK checks
import collections
stations_fields, stations = load("stations.csv")
ids = [r["id"] for r in stations]
check("stations_unique_pk", len(ids)==len(set(ids)), f"{len(ids)} rows, {len(set(ids))} unique")

connectors_fields, connectors = load("connectors.csv")
cids = [r["id"] for r in connectors]
check("connectors_unique_pk", len(cids)==len(set(cids)), f"{len(cids)} rows, {len(set(cids))} unique")

# FK connectors->stations
station_id_set = set(ids)
bad = [r["id"] for r in connectors if r["station_id"] not in station_id_set]
check("connectors_fk_station", len(bad)==0, f"{len(bad)} orphan connectors")

# observations FK
obs_fields, obs = load("station_observations.csv")
bad = [r["id"] for r in obs if r["station_id"] not in station_id_set]
check("obs_station_fk", len(bad)==0, f"{len(bad)} orphan observations")
badc = [r["id"] for r in obs if r["connector_id"] not in set(cids) and r["connector_id"]!=""]
check("obs_connector_fk", len(badc)==0, f"{len(badc)} bad connector refs")

# reviews FK
rev_fields, reviews = load("reviews.csv")
rev_station_bad = [r["id"] for r in reviews if r["station_id"] not in station_id_set]
check("reviews_station_fk", len(rev_station_bad)==0, f"{len(rev_station_bad)} bad")

# profiles
prof_fields, profiles = load("profiles.csv")
prof_ids = set(r["id"] for r in profiles)
rev_user_bad = [r["id"] for r in reviews if r["user_id"] not in prof_ids]
check("reviews_user_fk", len(rev_user_bad)==0, f"{len(rev_user_bad)} bad")

# pricing checks
verified_kwh = sum(1 for r in connectors if r["price_per_kwh"] not in ("",None))
verified_sess = sum(1 for r in connectors if r["price_per_session"] not in ("",None))
est = sum(1 for r in connectors if r["price_estimate_per_kwh"] not in ("",None))
free = sum(1 for r in connectors if r["price_per_kwh"]=="0" or r["price_per_kwh"]=="0.0")
none = sum(1 for r in connectors if r["price_per_kwh"] in ("",None) and r["price_per_session"] in ("",None) and r["price_estimate_per_kwh"] in ("",None))
check("pricing_no_estimate_in_verified", all(not (r["price_estimate_per_kwh"] not in ("",None) and r["price_per_kwh"] not in ("",None)) for r in connectors), "estimate never fills verified")
check("pricing_counts", True, f"verified_kwh={verified_kwh}, session={verified_sess}, estimate={est}, free={free}, none={none}")

# coordinates
badcoords = [r["id"] for r in stations if not (-90<=float(r["latitude"])<=90 and -180<=float(r["longitude"])<=180)]
check("station_coords", len(badcoords)==0, f"{len(badcoords)} bad")

# observations received>=observed
badtime = [r["id"] for r in obs if r["received_at"] < r["observed_at"]]
check("obs_time_order", len(badtime)==0, f"{len(badtime)} bad")

# deterministic hash check not run here
check("total_rows_min", total>=100000, f"total={total}")

with open(os.path.join(OUT,"validation_report.json"),"w",encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps({"total_rows":total,"checks":{k:v["pass"] for k,v in report["checks"].items()}}, indent=2))
