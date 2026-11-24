"""Download City & County of Honolulu cadastral tables (ArcGIS FeatureServer) to CSV by objectid range."""
import csv, json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://services.arcgis.com/tNJpAOha4mODLkXz/arcgis/rest/services/CadastralTables/FeatureServer"
TABLES = {13: "facilities", 6: "owndat", 9: "asmtgis", 14: "separations"}
STEP = 2000

def get(url, params, tries=5):
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(q, timeout=120) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def fetch_range(layer, lo, hi):
    d = get(f"{BASE}/{layer}/query", {
        "where": f"objectid >= {lo} AND objectid < {hi}",
        "outFields": "*", "returnGeometry": "false", "f": "json"})
    return [f["attributes"] for f in d.get("features", [])]

def main(out_dir):
    for layer, name in TABLES.items():
        stats = get(f"{BASE}/{layer}/query", {
            "where": "1=1", "returnGeometry": "false", "f": "json",
            "outStatistics": json.dumps([
                {"statisticType": "min", "onStatisticField": "objectid", "outStatisticFieldName": "mn"},
                {"statisticType": "max", "onStatisticField": "objectid", "outStatisticFieldName": "mx"}])})
        a = stats["features"][0]["attributes"]
        mn, mx = int(a["mn"]), int(a["mx"])
        ranges = [(lo, lo + STEP) for lo in range(mn, mx + 1, STEP)]
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=4) as ex:
            chunks = list(ex.map(lambda r: fetch_range(layer, *r), ranges))
        rows = [row for c in chunks for row in c]
        fields = list(rows[0].keys()) if rows else []
        with open(f"{out_dir}/{name}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"{name}: {len(rows)} rows, {len(ranges)} requests, {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1])
