"""Retry unmatched HUD points with a 25 m search radius; keep every parcel within it (flagged as approximate)."""
import csv, json, sys, time, urllib.parse, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

PARCELS = "https://geodata.hawaii.gov/arcgis/rest/services/ParcelsZoning/MapServer/11/query"

def tmks_near(lat, lon, meters=25, tries=4):
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "distance": meters, "units": "esriSRUnit_Meter",
              "outFields": "tmk8num", "returnGeometry": "false", "f": "json"}
    url = PARCELS + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            return ";".join(str(f["attributes"].get("tmk8num")) for f in d.get("features", []))
        except Exception:
            time.sleep(2 * (i + 1))
    return "ERROR"

def main(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    print("unmatched by program before:", Counter(r["program"] for r in rows if r["tmk8"] in ("", "ERROR")))
    todo = [r for r in rows if r["tmk8"] in ("", "ERROR")]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda r: tmks_near(float(r["lat"]), float(r["lon"])), todo))
    for r in rows:
        r["match"] = "point-in-parcel" if r["tmk8"] not in ("", "ERROR") else ""
    for r, t in zip(todo, res):
        r["tmk8"], r["match"] = t, ("within 25 m" if t not in ("", "ERROR") else "none")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("match types:", Counter(r["match"] for r in rows))

if __name__ == "__main__":
    main(sys.argv[1])
