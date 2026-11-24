"""Attach an Oahu TMK to each HUD subsidized-housing point by querying the state parcel layer."""
import csv, json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

PARCELS = "https://geodata.hawaii.gov/arcgis/rest/services/ParcelsZoning/MapServer/11/query"

def tmk_at(lat, lon, tries=4):
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "tmk8num,tmk",
              "returnGeometry": "false", "f": "json"}
    url = PARCELS + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            fs = d.get("features", [])
            return ";".join(str(f["attributes"].get("tmk8num")) for f in fs)
        except Exception:
            time.sleep(2 * (i + 1))
    return "ERROR"

def main(hud_dir):
    specs = {
        "lihtc": ("LIHTC", "PROJECT", "PROJ_ADD", "N_UNITS"),
        "mfa": ("HUD multifamily assisted", "PROPERTY_NAME_TEXT", "ADDRESS_LINE1_TEXT", "TOTAL_UNIT_COUNT"),
        "ph": ("Public housing", "PROJECT_NAME", "STD_ADDR", "TOTAL_DWELLING_UNITS"),
    }
    rows = []
    for key, (program, name_f, addr_f, units_f) in specs.items():
        d = json.load(open(f"{hud_dir}/{key}.json", encoding="utf-8"))
        for f in d["features"]:
            a = f["attributes"]
            if str(a.get("CNTY2KX")).lstrip("0").replace("15", "", 1) not in ("3",) and str(a.get("CNTY2KX")) not in ("003", "15003", "3"):
                continue
            if a.get("LAT") is None or a.get("LON") is None:
                continue
            rows.append({"program": program, "name": (a.get(name_f) or "").strip(),
                         "address": (a.get(addr_f) or "").strip(), "units": a.get(units_f),
                         "lat": a["LAT"], "lon": a["LON"]})
    with ThreadPoolExecutor(max_workers=6) as ex:
        tmks = list(ex.map(lambda r: tmk_at(r["lat"], r["lon"]), rows))
    for r, t in zip(rows, tmks):
        r["tmk8"] = t
    with open(f"{hud_dir}/hud_points_tmk.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    hit = sum(1 for r in rows if r["tmk8"] not in ("", "ERROR"))
    print(f"{len(rows)} Honolulu HUD points, {hit} matched to a parcel")

if __name__ == "__main__":
    main(sys.argv[1])
