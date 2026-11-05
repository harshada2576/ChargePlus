import csv
import json
import os
import random
import uuid
import hashlib
from datetime import datetime, timedelta, time, date

SEED = 42
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = {
    "seed": SEED,
    "station_count": 2000,
    "operator_count": 100,
    "profile_count": 100,
    "connector_per_station_min": 1,
    "connector_per_station_max": 4,
    "observation_count": 70000,
    "review_count": 10000,
    "user_report_count": 2000,
    "alert_count": 3000,
    "ingestion_run_count": 1000,
    "favorite_count": 1000,
    "session_count": 30000,
    "daily_agg_count": 10000,
    "dim_date_days": 1095,
    "dim_location_count": 2000,
    "dim_station_count": 2000,
    "dim_tariff_count": 1000,
    "dim_vehicle_count": 100,
    "dim_weather_count": 10000,
    "date_start": "2023-01-01",
    "date_end": "2026-10-18",
}
random.seed(SEED)
rng = random.Random(SEED)

def uid():
    return str(uuid.UUID(int=rng.getrandbits(128)))

def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

def dstr(d):
    return d.isoformat()

def tstr(t):
    return t.strftime("%H:%M:%S")

def wkt(lon, lat):
    return f"POINT({lon} {lat})"

CITIES = [
 ("Mumbai","Maharashtra",19.0760,72.8777,"400001"),
 ("Thane","Maharashtra",19.2183,72.9781,"400601"),
 ("Navi Mumbai","Maharashtra",19.0330,73.0297,"400703"),
 ("Kalyan","Maharashtra",19.2403,73.1305,"421301"),
 ("Pune","Maharashtra",18.5204,73.8567,"411001"),
 ("Nagpur","Maharashtra",21.1458,79.0882,"440001"),
 ("Nashik","Maharashtra",19.9975,73.7898,"422001"),
 ("Delhi","Delhi",28.6139,77.2090,"110001"),
 ("Bengaluru","Karnataka",12.9716,77.5946,"560001"),
 ("Hyderabad","Telangana",17.3850,78.4867,"500001"),
 ("Chennai","Tamil Nadu",13.0827,80.2707,"600001"),
 ("Kolkata","West Bengal",22.5726,88.3639,"700001"),
 ("Ahmedabad","Gujarat",23.0225,72.5714,"380001"),
 ("Surat","Gujarat",21.1702,72.8311,"395001"),
 ("Jaipur","Rajasthan",26.9124,75.7873,"302001"),
 ("Lucknow","Uttar Pradesh",26.8467,80.9462,"226001"),
 ("Kochi","Kerala",9.9312,76.2673,"682001"),
]

def jitter(lat, lon, scale=0.05):
    return lat + rng.uniform(-scale, scale), lon + rng.uniform(-scale, scale)

STATION_TYPES = ["Highway charging hub","Public parking facility","Shopping mall charging point","Commercial complex","Hotel charging","Fleet depot","Urban public charger","Office campus","Residential community charger","Destination charger"]

def write_csv(name, header, rows):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return len(rows)

# data_sources
data_sources = []
for i, name in enumerate([    "demo_open_charge_map","demo_operator_feed","manual_demo_import","analytics_etl","alert_service"
]):
    data_sources.append([uid(), name, "api" if i==0 else "manual", f"https://example.com/{name}", 100-i*10, True, ts(datetime(2026,1,1,tzinfo=None)+timedelta(days=i))])
ds_header = ["id","name","source_type","base_url","source_priority","is_active","created_at"]
ds_count = write_csv("data_sources.csv", ds_header, data_sources)
ds_ids = [r[0] for r in data_sources]

# operators
operators = []
operator_names = [f"Demo Operator {i+1}" for i in range(CONFIG["operator_count"])]
for i in range(CONFIG["operator_count"]):
    operators.append([uid(), operator_names[i], f"demo-operator-{i+1}", f"https://demo-operator-{i+1}.example.com", f"+91-90000{i:05d}", ts(datetime(2026,1,1)+timedelta(days=i%30)), ts(datetime(2026,1,1)+timedelta(days=i%30))])
op_header = ["id","name","slug","website_url","support_phone","created_at","updated_at"]
write_csv("operators.csv", op_header, operators)
op_ids = [r[0] for r in operators]

# profiles
profiles = []
for i in range(CONFIG["profile_count"]):
    profiles.append([uid(), f"Demo User {i+1}", "user" if i%10 else "admin", rng.choice(["en","hi","mr"]), rng.choice([c[0] for c in CITIES]), ts(datetime(2026,1,1)+timedelta(days=i)), ts(datetime(2026,1,1)+timedelta(days=i))])
prof_header = ["id","display_name","role","preferred_language","home_city","created_at","updated_at"]
write_csv("profiles.csv", prof_header, profiles)
prof_ids = [r[0] for r in profiles]

# stations
stations = []
station_city = []
for i in range(CONFIG["station_count"]):
    city, state, lat, lon, pc = rng.choice(CITIES)
    latj, lonj = jitter(lat, lon)
    is24 = rng.random() < 0.2
    if is24:
        ot = ""; ct = ""
    else:
        if rng.random() < 0.15:
            ot = ""; ct = ""
        else:
            ot = time(rng.randint(5,9), rng.choice([0,15,30,45])).strftime("%H:%M:%S")
            ct = time(rng.randint(17,23), rng.choice([0,15,30,45])).strftime("%H:%M:%S")
    op_status = rng.choices(["operational","temporarily_unavailable","permanently_closed","unknown"], weights=[0.7,0.15,0.05,0.1])[0]
    public = rng.random() < 0.85
    access = "Public" if public else "Private / Restricted"
    slug = f"demo-station-{i+1}"
    stations.append([uid(), slug, f"Demo Charging Station {i+1}", rng.choice(op_ids), f"Demo Address {i+1}", rng.choice(["Sector","Block","Plot","Phase"])+f" {rng.randint(1,50)}", city, state, pc if rng.random()<0.85 else "", "India", latj, lonj, wkt(lonj,latj), ot, ct, is24, access, public, op_status, f"+91-9{rng.randint(100000000,999999999)}" if rng.random()<0.6 else "", f"https://demo-station-{i+1}.example.com" if rng.random()<0.5 else "", None if rng.random()<0.7 else ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,30))), ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,30))), ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,30)))])
    station_city.append(city)
st_header = ["id","slug","name","operator_id","address_line","locality","city","state","postal_code","country","latitude","longitude","geom","opening_time","closing_time","is_24_hours","access_type","is_public","operational_status","phone","website_url","last_verified_at","created_at","updated_at","is_simulated"]
write_csv("stations.csv", st_header, stations)
station_ids = [r[0] for r in stations]

# connectors
connectors = []
connector_types = ["CCS2","CCS1","CHAdeMO","Type 2","Type 1","GB/T","Bharat AC001","Bharat DC001"]
charging_standards = {"CCS2":"IEC 62196-3","CCS1":"IEC 62196-3","CHAdeMO":"IEC 62196-3","Type 2":"IEC 62196-2","Type 1":"SAE J1772","GB/T":"GB/T 20234","Bharat AC001":"IS 17017","Bharat DC001":"IS 17017"}
for i, st in enumerate(stations):
    sid = st[0]
    nconn = rng.randint(CONFIG["connector_per_station_min"], CONFIG["connector_per_station_max"])
    for j in range(nconn):
        ctype = rng.choice(connector_types)
        power = rng.choice([3.3,7.2,11,15,22,30,45,60,90,120,150,240])
        if rng.random() < 0.1:
            power = None
        qty = rng.choice([1,1,2,2,4])
        currency = "INR"
        # pricing scenario
        scen = rng.random()
        price_kwh = None
        price_sess = None
        pricing_type = "unknown"
        est = None
        est_raw = None
        est_src = None
        if scen < 0.42:
            price_kwh = round(rng.uniform(10,25),2)
            pricing_type = "paid"
        elif scen < 0.60:
            price_sess = round(rng.choice([50,75,100,120,150,200]),2)
            pricing_type = "paid"
        elif scen < 0.78:
            est = round(rng.uniform(11,24),2)
            est_raw = f"Rs {est}/kWh (demo)"
            est_src = "ocm_usage_cost"
            pricing_type = "unknown"
        elif scen < 0.83:
            price_kwh = 0.0
            pricing_type = "free"
        else:
            pass
        # free case should set price_kwh 0 if chosen
        if pricing_type == "free":
            price_kwh = 0.0
        connectors.append([uid(), sid, ctype, charging_standards[ctype], power, qty, pricing_type, price_kwh, price_sess, currency, ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,30))), ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,30))), est, est_raw, est_src])
conn_header = ["id","station_id","connector_type","charging_standard","power_kw","quantity","pricing_type","price_per_kwh","price_per_session","currency","created_at","updated_at","price_estimate_per_kwh","price_estimate_raw","price_estimate_source"]
write_csv("connectors.csv", conn_header, connectors)
connector_ids = [r[0] for r in connectors]
# map connector->station
conn_by_station = {}
for r in connectors:
    conn_by_station.setdefault(r[1], []).append(r)

# station_source_link
ssl = []
for st in stations:
    ssl.append([uid(), st[0], rng.choice(ds_ids), f"DEMO-{rng.randint(1000,9999)}", f"https://openchargemap.org/site/poi/details/{rng.randint(100000,999999)}", ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,5))), ts(datetime(2026,9,15)+timedelta(days=rng.randint(0,5))), ts(datetime(2026,9,15)+timedelta(days=rng.randint(0,5))), hashlib.sha256(str(rng.random()).encode()).hexdigest(), True, ts(datetime(2026,9,1)), ts(datetime(2026,9,15))])
ssl_header = ["id","station_id","source_id","source_station_id","source_url","first_seen_at","last_seen_at","last_ingested_at","source_payload_hash","is_active","created_at","updated_at"]
write_csv("station_source_link.csv", ssl_header, ssl)

# station_observations
obs = []
avail_statuses = ["available","busy","broken","unknown"]
queue_levels = ["none","short","medium","long","unknown"]
end_date = datetime(2026,10,18)
for _ in range(CONFIG["observation_count"]):
    st = rng.choice(stations)
    sid = st[0]
    conns = conn_by_station.get(sid, [])
    conn = rng.choice(conns) if conns and rng.random()<0.8 else None
    cid = conn[0] if conn else None
    total = conn[4] if conn and conn[4] else rng.randint(1,4)  # power? no; use qty
    # better total connectors from connector quantity
    if conn:
        total = conn[5]
    else:
        total = rng.randint(1,4)
    avail = rng.randint(0,total) if rng.random()<0.9 else None
    status = rng.choice(avail_statuses)
    queue = rng.choice(queue_levels)
    observed = end_date - timedelta(days=rng.randint(0,30), hours=rng.randint(0,23), minutes=rng.randint(0,59))
    received = observed + timedelta(minutes=rng.randint(0,60))
    conf = round(rng.uniform(0.5,1.0),2)
    obs.append([uid(), sid, cid, rng.choice(ds_ids), status, queue, avail, total, ts(observed), ts(received), conf, hashlib.sha256(str(rng.random()).encode()).hexdigest(), ts(observed)])
obs_header = ["id","station_id","connector_id","source_id","availability_status","queue_level","available_connectors","total_connectors","observed_at","received_at","confidence_score","source_payload_hash","created_at"]
write_csv("station_observations.csv", obs_header, obs)

# reviews
reviews = []
for _ in range(CONFIG["review_count"]):
    st = rng.choice(stations)
    usr = rng.choice(profiles)
    rating = rng.choices([1,2,3,4,5], weights=[0.05,0.1,0.2,0.35,0.3])[0]
    comment = rng.choice(["Good charging experience.","Fast and reliable.","A bit crowded at peak hours.","Connector was faulty once.","Affordable and convenient.","Clean location.","Staff helpful.","Would use again."]) if rng.random()<0.8 else None
    mod = rng.choices(["pending","approved","rejected"], weights=[0.2,0.75,0.05])[0]
    if mod == "pending":
        moderated_by = ""; moderated_at = ""; reason = ""
    else:
        moderated_by = rng.choice(prof_ids)
        moderated_at = ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,40)))
        reason = "spam" if mod=="rejected" else ""
    flagged = mod=="rejected"
    created = datetime(2026,8,1)+timedelta(days=rng.randint(0,60))
    reviews.append([uid(), usr[0], st[0], rating, comment, flagged, mod, moderated_by, moderated_at, reason if reason else None, ts(created), ts(created)])
rev_header = ["id","user_id","station_id","rating","comment","is_flagged","moderation_status","moderated_by","moderated_at","moderation_reason","created_at","updated_at"]
write_csv("reviews.csv", rev_header, reviews)

# user_reports
user_reports = []
for _ in range(CONFIG["user_report_count"]):
    st = rng.choice(stations)
    conns = conn_by_station.get(st[0], [])
    conn = rng.choice(conns) if conns and rng.random()<0.7 else None
    cid = conn[0] if conn else ""
    usr = rng.choice(profiles)
    status = rng.choice(["available","busy","broken","unknown"])
    queue = rng.choice(queue_levels)
    comment = rng.choice(["Working fine.","Slow charging.","Out of service.","Occupied.","Good access."]) if rng.random()<0.7 else None
    observed = datetime(2026,9,1)+timedelta(days=rng.randint(0,40), hours=rng.randint(0,23))
    created = observed + timedelta(minutes=rng.randint(0,120))
    mod = rng.choices(["pending","approved","rejected"], weights=[0.3,0.6,0.1])[0]
    if mod=="pending":
        mb=""; ma=""; mr=""
    else:
        mb=rng.choice(prof_ids); ma=ts(created+timedelta(days=1)); mr="invalid" if mod=="rejected" else ""
    flagged = mod=="rejected"
    user_reports.append([uid(), usr[0], st[0], cid, status, queue, comment, ts(observed), ts(created), flagged, mod, mb, ma, mr if mr else None])
ur_header = ["id","user_id","station_id","connector_id","availability_status","queue_level","comment","observed_at","created_at","is_flagged","moderation_status","moderated_by","moderated_at","moderation_reason"]
write_csv("user_reports.csv", ur_header, user_reports)

# alerts
alerts = []
alert_types = ["station_available","station_status_change","congestion_threshold","nearby_station_change"]
for _ in range(CONFIG["alert_count"]):
    usr = rng.choice(profiles)
    st = rng.choice(stations) if rng.random()<0.8 else None
    sid = st[0] if st else ""
    enabled = rng.random()<0.85
    params = {"station_id": sid, "threshold": rng.choice([2,4,6])}
    last_trig = ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,40))) if rng.random()<0.6 else ""
    alerts.append([uid(), usr[0], sid if sid else None, rng.choice(alert_types), json.dumps(params), round(rng.uniform(0,10),2) if rng.random()<0.5 else None, enabled, last_trig, ts(datetime(2026,8,1)+timedelta(days=rng.randint(0,60))), ts(datetime(2026,8,1)+timedelta(days=rng.randint(0,60)))])
al_header = ["id","user_id","station_id","alert_type","params","threshold_value","is_enabled","last_triggered_at","created_at","updated_at"]
write_csv("alerts.csv", al_header, alerts)

# ingestion_runs
ingestion_runs = []
states = ["SUCCEEDED","PARTIAL","FAILED","CANCELLED","RUNNING","STARTED"]
for _ in range(CONFIG["ingestion_run_count"]):
    state = rng.choices(states, weights=[0.6,0.15,0.1,0.05,0.05,0.05])[0]
    source = rng.choice(data_sources)
    sid = source[0]
    started = datetime(2026,8,1)+timedelta(days=rng.randint(0,70), hours=rng.randint(0,23), minutes=rng.randint(0,59))
    if state in ("SUCCEEDED","PARTIAL","FAILED","CANCELLED"):
        completed = started + timedelta(minutes=rng.randint(1,90))
        dur = round((completed-started).total_seconds()/60.0,2)
    else:
        completed = None
        dur = None
    fetched = rng.randint(0,50)
    parsed = rng.randint(0,fetched) if fetched>0 else 0
    accepted = rng.randint(0,parsed) if parsed>0 else 0
    accepted_warn = rng.randint(0,accepted) if accepted>0 else 0
    quar = rng.randint(0,5)
    rejected = rng.randint(0,5)
    st_persisted = rng.randint(0,20) if state in ("SUCCEEDED","PARTIAL") else 0
    st_updated = rng.randint(0,st_persisted) if st_persisted>0 else 0
    st_unchanged = st_persisted - st_updated
    conn_persisted = rng.randint(0,40) if state in ("SUCCEEDED","PARTIAL") else 0
    obs_persisted = rng.randint(0,100) if state in ("SUCCEEDED","PARTIAL") else 0
    error_summary = "Connection timeout" if state=="FAILED" else ("Partial ingest" if state=="PARTIAL" else None)
    meta = {"job":"demo","dry_run":False}
    ingestion_runs.append([uid(), sid, source[1], f"scope-{rng.randint(1,5)}", state, ts(started), ts(completed) if completed else None, dur, rng.randint(1,3), fetched, parsed, accepted, accepted_warn, quar, rejected, st_persisted, st_updated, st_unchanged, conn_persisted, obs_persisted, error_summary, json.dumps(meta), ts(started)])
ir_header = ["id","source_id","source_name","scope","state","started_at","completed_at","duration_seconds","attempt_count","records_fetched","records_parsed","records_accepted","records_accepted_with_warnings","records_quarantined","records_rejected","stations_persisted","stations_updated","stations_unchanged","connectors_persisted","observations_persisted","error_summary","metadata","created_at"]
write_csv("ingestion_runs.csv", ir_header, ingestion_runs)

# favorites
favorites = []
fav_set = set()
while len(favorites) < CONFIG["favorite_count"]:
    u = rng.choice(profiles)[0]
    s = rng.choice(stations)[0]
    key = (u,s)
    if key in fav_set:
        continue
    fav_set.add(key)
    favorites.append([u, s, ts(datetime(2026,9,1)+timedelta(days=rng.randint(0,40)))])
fav_header = ["user_id","station_id","created_at"]
write_csv("favorites.csv", fav_header, favorites)

# dim_date
dim_date = []
start = date(2023,1,1)
for i in range(CONFIG["dim_date_days"]):
    d = start + timedelta(days=i)
    dow = d.isoweekday()
    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    month_names = ["January","February","March","April","May","June","July","August","September","October","November","December"]
    is_weekend = dow in (6,7)
    season = "Winter" if d.month in (12,1,2) else "Summer" if d.month in (3,4,5) else "Monsoon" if d.month in (6,7,8,9) else "Autumn"
    dim_date.append([i+1, dstr(d), dow, day_names[dow-1], d.month, month_names[d.month-1], (d.month-1)//3+1, d.year, is_weekend, rng.random()<0.05, season])
dd_header = ["date_key","full_date","day_of_week","day_name","month","month_name","quarter","year","is_weekend","is_holiday","season"]
write_csv("dim_date.csv", dd_header, dim_date)
date_keys = [r[0] for r in dim_date]

# dim_time
dim_time = []
tk = 1
for h in range(24):
    for m in (0,15,30,45):
        slot = "Peak" if h in (8,9,18,19,20) else "Off-Peak"
        is_peak = h in (8,9,18,19,20)
        dim_time.append([tk, h, m, slot, is_peak])
        tk += 1
# trim to 1440? we only generated 96; need 1440 minutes? spec says 1440. Generate per minute
dim_time = []
tk = 1
for h in range(24):
    for m in range(60):
        slot = "Peak" if h in (8,9,18,19,20) else "Off-Peak"
        is_peak = h in (8,9,18,19,20)
        dim_time.append([tk, h, m, slot, is_peak])
        tk += 1
dt_header = ["time_key","hour","minute","time_slot","is_peak_hours"]
write_csv("dim_time.csv", dt_header, dim_time)
time_keys = [r[0] for r in dim_time]

# dim_location
dim_location = []
area_types = ["Residential","Commercial","Highway","Workplace","Airport","Transit Hub"]
for i in range(CONFIG["dim_location_count"]):
    city, state, lat, lon, pc = rng.choice(CITIES)
    latj, lonj = jitter(lat, lon, 0.08)
    dim_location.append([i+1, f"LOC-{i+1:05d}", city, f"Zone {rng.randint(1,8)}", rng.choice(area_types), round(latj,6), round(lonj,6), f"GS-{rng.randint(100,999)}" if rng.random()<0.7 else None])
dl_header = ["location_key","location_id","city","zone_name","area_type","latitude","longitude","grid_substation_id"]
write_csv("dim_location.csv", dl_header, dim_location)
location_keys = [r[0] for r in dim_location]

# dim_station
dim_station = []
charger_types = ["AC Level 2","DC Fast Charger","Ultra-Fast HPC"]
for i in range(CONFIG["dim_station_count"]):
    city = rng.choice([c[0] for c in CITIES])
    ct = rng.choice(charger_types)
    ports = rng.randint(1,8)
    maxp = rng.choice([7.2,22,30,60,120,240])
    inst = date(2021,1,1)+timedelta(days=rng.randint(0,1800))
    eff_start = date(2023,1,1)+timedelta(days=rng.randint(0,365))
    eff_end = eff_start+timedelta(days=rng.randint(365,730)) if rng.random()<0.3 else None
    is_current = eff_end is None
    dim_station.append([i+1, f"ST-{i+1:05d}", f"Demo Analytics Station {i+1}", rng.choice(operator_names), ct, ports, maxp, dstr(inst), dstr(eff_start), dstr(eff_end) if eff_end else None, is_current])
ds2_header = ["station_key","station_id","station_name","operator","charger_type","num_ports","max_power_kw","installation_date","effective_start_date","effective_end_date","is_current"]
write_csv("dim_station.csv", ds2_header, dim_station)
station_keys = [r[0] for r in dim_station]

# dim_tariff
dim_tariff = []
tier_types = ["Off-Peak","Standard","Peak","Critical Surge"]
for i in range(CONFIG["dim_tariff_count"]):
    dim_tariff.append([i+1, f"TAR-{i+1:05d}", f"Tariff Plan {i+1}", rng.choice(tier_types), round(rng.uniform(8,28),2)])
dtar_header = ["tariff_key","tariff_id","tariff_name","tier_type","rate_per_kwh"]
write_csv("dim_tariff.csv", dtar_header, dim_tariff)
tariff_keys = [r[0] for r in dim_tariff]

# dim_vehicle
dim_vehicle = []
vehicle_types = ["2-Wheeler","3-Wheeler","Passenger Sedan/SUV","Commercial Fleet/Bus"]
makes = ["Tata","MG","Mahindra","Hyundai","Kia","Ola","Ather","Hero"]
models = ["Nexon EV","ZS EV","XUV400","Kona","EV6","S1 Pro","450X","Optima"]
for i in range(CONFIG["dim_vehicle_count"]):
    vt = rng.choice(vehicle_types)
    dim_vehicle.append([i+1, f"VEH-{i+1:05d}", rng.choice(makes), rng.choice(models), vt, round(rng.uniform(2,100),2), round(rng.uniform(3,120),2)])
dv_header = ["vehicle_key","vehicle_id","make","model","vehicle_type","battery_capacity_kwh","max_charge_rate_kw"]
write_csv("dim_vehicle.csv", dv_header, dim_vehicle)
vehicle_keys = [r[0] for r in dim_vehicle]

# dim_weather
dim_weather = []
conditions = ["Clear","Cloudy","Rain","Hot","Humid","Fog"]
for i in range(CONFIG["dim_weather_count"]):
    dim_weather.append([i+1, f"WX-{i+1:05d}", round(rng.uniform(15,45),2), rng.randint(20,95), round(rng.uniform(0,20),2), rng.choice(conditions)])
dw_header = ["weather_key","weather_id","temperature_celsius","humidity_pct","rainfall_mm","weather_condition"]
write_csv("dim_weather.csv", dw_header, dim_weather)
weather_keys = [r[0] for r in dim_weather]

# fact_charging_session
sessions = []
for i in range(CONFIG["session_count"]):
    sk = rng.choice(station_keys)
    lk = rng.choice(location_keys)
    vk = rng.choice(vehicle_keys)
    dk = rng.choice(date_keys)
    tk = rng.choice(time_keys)
    wk = rng.choice(weather_keys)
    tariffk = rng.choice(tariff_keys)
    start_dt = datetime(2024,1,1)+timedelta(days=rng.randint(0,700), hours=rng.randint(0,23), minutes=rng.randint(0,59))
    dur = round(rng.uniform(10,180),2)
    end_dt = start_dt + timedelta(minutes=dur)
    energy = round(rng.uniform(1,60),3)
    peak = round(rng.uniform(3,150),2)
    cost = round(rng.uniform(20,1500),2)
    sessions.append([i+1, f"SES-{i+1:07d}", sk, lk, vk, dk, tk, wk, tariffk, ts(start_dt), ts(end_dt), dur, energy, peak, cost, rng.randint(0,20), rng.randint(0,15), ts(start_dt)])
fcs_header = ["session_key","session_id","station_key","location_key","vehicle_key","date_key","time_key","weather_key","tariff_key","start_timestamp","end_timestamp","duration_minutes","energy_consumed_kwh","peak_power_kw","session_cost","queue_time_minutes","idle_time_minutes","created_at"]
write_csv("fact_charging_session.csv", fcs_header, sessions)

# fact_station_daily_agg
agg = []
for i in range(CONFIG["daily_agg_count"]):
    sk = rng.choice(station_keys)
    dk = rng.choice(date_keys)
    lk = rng.choice(location_keys)
    total_sessions = rng.randint(1,80)
    total_energy = round(rng.uniform(10,500),3)
    total_revenue = round(rng.uniform(100,5000),2)
    avg_dur = round(rng.uniform(20,90),2)
    avg_queue = round(rng.uniform(0,15),2)
    util = round(rng.uniform(5,95),2)
    agg.append([i+1, sk, dk, lk, total_sessions, total_energy, total_revenue, avg_dur, avg_queue, util])
fsda_header = ["agg_id","station_key","date_key","location_key","total_sessions","total_energy_kwh","total_revenue","avg_duration_minutes","avg_queue_time_minutes","utilization_rate_pct"]
write_csv("fact_station_daily_agg.csv", fsda_header, agg)

print("done")
