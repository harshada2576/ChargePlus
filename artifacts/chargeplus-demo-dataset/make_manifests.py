import csv, json, os, hashlib, glob

OUT = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(OUT,'*.csv')))
# data dictionary
dd_rows = []
for f in files:
    name = os.path.basename(f)
    with open(f,newline='',encoding='utf-8') as fh:
        reader = csv.reader(fh)
        header = next(reader)
    for col in header:
        dd_rows.append([name, col, "Synthetic demo field", "text/numeric", "see schema"])
with open(os.path.join(OUT,'data_dictionary.csv'),'w',newline='',encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(["file_name","column_name","description","data_type","notes"]); w.extend if False else None
    for r in dd_rows: w.writerow(r)

# manifest
manifest = []
total = 0
for f in files:
    name = os.path.basename(f)
    with open(f,newline='',encoding='utf-8') as fh:
        n = sum(1 for _ in fh)-1
    total += n
    manifest.append({"file":name,"rows":n})
with open(os.path.join(OUT,'dataset_manifest.json'),'w',encoding='utf-8') as f:
    json.dump({"total_rows":total,"files":manifest}, f, indent=2)
with open(os.path.join(OUT,'dataset_manifest.csv'),'w',newline='',encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(["file_name","row_count"]); 
    for m in manifest: w.writerow([m["file"],m["rows"]])
    w.writerow(["TOTAL",total])

# checksums
with open(os.path.join(OUT,'sha256_checksums.txt'),'w',encoding='utf-8') as f:
    for fn in sorted(os.listdir(OUT)):
        if fn.endswith('.csv') or fn.endswith('.json') or fn.endswith('.py') or fn.endswith('.md') or fn.endswith('.txt'):
            p = os.path.join(OUT,fn)
            h = hashlib.sha256(open(p,'rb').read()).hexdigest()
            f.write(f"{h}  {fn}\n")

# README
readme = """# ChargePlus Demo Dataset\n\nSynthetic demo data only. Not real operator data.\n\nTotal rows: %d\n""" % total
with open(os.path.join(OUT,'README.md'),'w',encoding='utf-8') as f:
    f.write(readme)
print("done", total)
