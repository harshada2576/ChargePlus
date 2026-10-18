import csv, os, re, psycopg2
OUT="D:/Desktop/Projects/ChargePlus/artifacts/chargeplus-demo-dataset"
def env():
    e={}
    for line in open("D:/Desktop/Projects/ChargePlus/.env.local",encoding="utf-8"):
        m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*"(.*)"\s*$',line)
        if m: e[m.group(1)]=m.group(2)
    return e
conn=psycopg2.connect(env()["DATABASE_URL"])
cur=conn.cursor()
# ensure stations exist? transaction fresh; insert stations first quickly? Instead, just test connectors against existing 16 stations? Our connector station_ids are new. Need stations inserted. We'll insert stations from CSV first.
import csv
stations=list(csv.DictReader(open(os.path.join(OUT,"stations.csv"))))
for r in stations:
    cur.execute("INSERT INTO public.stations (id,slug,name,operator_id,address_line,locality,city,state,postal_code,country,latitude,longitude,geom,opening_time,closing_time,is_24_hours,access_type,is_public,operational_status,phone,website_url,last_verified_at,created_at,updated_at,is_simulated) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (r["id"],r["slug"] or None,r["name"],r["operator_id"],r["address_line"] or None,r["locality"] or None,r["city"],r["state"],r["postal_code"] or None,r["country"],float(r["latitude"]),float(r["longitude"]),r["geom"],r["opening_time"] or None,r["closing_time"] or None,r["is_24_hours"].lower()=="true",r["access_type"] or None,r["is_public"].lower()=="true",r["operational_status"],r["phone"] or None,r["website_url"] or None,r["last_verified_at"] or None,r["created_at"],r["updated_at"],True))
# operators needed first
conn.rollback()
print("rollback")
cur.close(); conn.close()
EOF