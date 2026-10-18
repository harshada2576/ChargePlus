import csv, json, os

OUT = "D:/Desktop/Projects/ChargePlus/artifacts/chargeplus-demo-dataset"
schema = json.load(open(os.path.join(OUT,"remote_schema_inventory.json")))
db = {t["table_name"]: {c["column_name"]: c for c in t["columns"]} for t in schema["tables"]}

# map csv -> table (None for excluded)
mapping = {
 "data_sources.csv": "data_sources",
 "operators.csv": "operators",
 "stations.csv": "stations",
 "connectors.csv": "connectors",
 "station_observations.csv": "station_observations",
 "station_source_link.csv": "station_source_link",
 "ingestion_runs.csv": "ingestion_runs",
 "dim_date.csv": "dim_date",
 "dim_location.csv": "dim_location",
 "dim_station.csv": "dim_station",
 "dim_tariff.csv": "dim_tariff",
 "dim_time.csv": "dim_time",
 "dim_vehicle.csv": "dim_vehicle",
 "dim_weather.csv": "dim_weather",
 "fact_charging_session.csv": "fact_charging_session",
 "fact_station_daily_agg.csv": "fact_station_daily_agg",
 "profiles.csv": None,
 "favorites.csv": None,
 "reviews.csv": None,
 "user_reports.csv": None,
 "alerts.csv": None,
}

# manual transform notes
transforms = {
 ("stations.csv","geom"): "WKT POINT(lon lat) into geometry; validate SRID",
 ("stations.csv","opening_time"): "empty -> NULL; time format HH:MM:SS",
 ("stations.csv","closing_time"): "empty -> NULL",
 ("stations.csv","postal_code"): "empty -> NULL; regex check",
 ("stations.csv","last_verified_at"): "empty -> NULL",
 ("stations.csv","operator_id"): "must exist in operators",
 ("connectors.csv","power_kw"): "empty -> NULL",
 ("connectors.csv","price_per_kwh"): "empty -> NULL; numeric",
 ("connectors.csv","price_per_session"): "empty -> NULL",
 ("connectors.csv","price_estimate_per_kwh"): "empty -> NULL; 0-500",
 ("connectors.csv","price_estimate_raw"): "empty -> NULL; <=500 chars",
 ("connectors.csv","price_estimate_source"): "empty or ocm_usage_cost",
 ("station_observations.csv","connector_id"): "empty -> NULL; must belong to same station",
 ("station_observations.csv","available_connectors"): "empty -> NULL",
 ("station_observations.csv","confidence_score"): "empty -> NULL",
 ("station_observations.csv","source_payload_hash"): "empty -> NULL",
 ("station_source_link.csv","source_url"): "empty -> NULL",
 ("station_source_link.csv","first_seen_at"): "empty -> NULL",
 ("station_source_link.csv","last_seen_at"): "empty -> NULL",
 ("station_source_link.csv","last_ingested_at"): "empty -> NULL",
 ("station_source_link.csv","source_payload_hash"): "empty -> NULL",
 ("ingestion_runs.csv","source_id"): "empty -> NULL; must exist in data_sources",
 ("ingestion_runs.csv","completed_at"): "empty -> NULL",
 ("ingestion_runs.csv","duration_seconds"): "empty -> NULL",
 ("ingestion_runs.csv","error_summary"): "empty -> NULL",
 ("ingestion_runs.csv","metadata"): "JSON string into jsonb",
 ("dim_station.csv","effective_end_date"): "empty -> NULL",
 ("fact_charging_session.csv","created_at"): "timestamptz",
}

excluded_reason = "Excluded user-dependent data per safety rules (profiles/favorites/reviews/user_reports/alerts)."

report = []
counts = {"EXACT_MATCH":0,"SAFE_TRANSFORMATION_REQUIRED":0,"TARGET_COLUMN_MISSING":0,"TYPE_INCOMPATIBLE":0,"CONSTRAINT_INCOMPATIBLE":0,"EXCLUDED_USER_DATA":0,"NOT_VERIFIABLE":0}

for csv_file, table in mapping.items():
    path = os.path.join(OUT, csv_file)
    with open(path, newline='', encoding='utf-8') as f:
        header = next(csv.reader(f))
    if table is None:
        for col in header:
            cat = "EXCLUDED_USER_DATA"
            counts[cat]+=1
            report.append({"csv_file":csv_file,"csv_field":col,"target_table":None,"target_column":None,"db_type":None,"compatibility":cat,"transformation":"Excluded","nullability":None,"constraints":None,"default_behavior":None,"validation":"Excluded","decision":"exclude","evidence":"user-data restriction"})
        continue
    cols = db[table]
    for col in header:
        if col in cols:
            c = cols[col]
            t = transforms.get((csv_file,col))
            cat = "SAFE_TRANSFORMATION_REQUIRED" if t else "EXACT_MATCH"
            counts[cat]+=1
            report.append({"csv_file":csv_file,"csv_field":col,"target_table":table,"target_column":col,"db_type":c["data_type"],"compatibility":cat,"transformation": t if t else "None","nullability":c["is_nullable"],"constraints":"","default_behavior":c["column_default"],"validation":"type/null/constraints","decision":"keep" if not t else "transform","evidence":"remote_schema_inventory.json"})
        else:
            cat = "TARGET_COLUMN_MISSING"
            counts[cat]+=1
            report.append({"csv_file":csv_file,"csv_field":col,"target_table":table,"target_column":None,"db_type":None,"compatibility":cat,"transformation":"N/A","nullability":None,"constraints":None,"default_behavior":None,"validation":"N/A","decision":"exclude","evidence":"remote_schema_inventory.json"})

# write json
with open(os.path.join(OUT,"schema_compatibility_report.json"),"w",encoding="utf-8") as f:
    json.dump({"summary":counts,"fields":report}, f, indent=2)

# write md
with open(os.path.join(OUT,"schema_compatibility_report.md"),"w",encoding="utf-8") as f:
    f.write("# Schema Compatibility Report\n\n")
    f.write(f"Total fields checked: {len(report)}\n\n")
    for k,v in counts.items():
        f.write(f"- {k}: {v}\n")
    f.write("\n| CSV | Field | Table | Column | Type | Compatibility | Transformation |\n|---|---|---|---|---|---|---|\n")
    for r in report:
        f.write(f"| {r['csv_file']} | {r['csv_field']} | {r['target_table']} | {r['target_column']} | {r['db_type']} | {r['compatibility']} | {r['transformation']} |\n")
print("done", len(report), counts)
