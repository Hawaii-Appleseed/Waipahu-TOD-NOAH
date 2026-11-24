"""Cut the NOAH map data down to the Waipahu Neighborhood TOD Plan area and add its context layers.

Usage: python build_waipahu_tod.py <map_data_dir> <all_5plus_unit_parcels.csv> <out_dir>
  map_data_dir holds noah.json and parcels.json from build_map_data.py.

Writes out_dir/waipahu_tod.json with the NOAH parcels inside the plan boundary or within 1/2 mile of
either Waipahu station (centroid test), each tagged with its TOD Special District and nearest rail
station; the older condo buildings that meet every NOAH rule except single ownership; and the plan
boundary, special districts, stations, rail guideway, streets and land for drawing.
"""
import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request

CITY = "https://services.arcgis.com/tNJpAOha4mODLkXz/arcgis/rest/services"
HART = "https://services6.arcgis.com/2cZSk3EXXiOHcbOl/arcgis/rest/services"
PLAN = f"{CITY}/TOD_Plan_Boundary/FeatureServer/0/query"
SPECIAL_DISTRICTS = f"{CITY}/TOD_Special_District_and_Zone_Change/FeatureServer/2/query"
STATIONS = f"{HART}/HART_Transit_Stations_PUBLIC/FeatureServer/0/query"
GUIDEWAY = f"{HART}/HART_Guideway_Alignment_Line_PUBLIC/FeatureServer/0/query"
STREETS = "https://geodata.hawaii.gov/arcgis/rest/services/Transportation/MapServer/3/query"
ADDRESSES = f"{CITY}/Cadastral_2020/FeatureServer/3/query"
BOARDS = f"{CITY}/Neighborhood_Boards_with_Dissolved_Subdistricts/FeatureServer/0/query"
PARCELS = "https://geodata.hawaii.gov/arcgis/rest/services/ParcelsZoning/MapServer/11/query"
BULLSEYE_MILES = 0.5

# Station and district names are written out here because the services' Hawaiian diacritics are mis-encoded
STATION_NAMES = {"West Loch Station": "Hōʻaeʻae (West Loch)",
                 "Waipahu Transit Center Station": "Pouhala (Waipahu Transit Center)",
                 "Leeward Community College Station": "Hālaulani (Leeward CC)"}
DISTRICT_NAMES = {1: "Hōʻaeʻae (West Loch) Station Area", 2: "Pouhala (Waipahu Transit Center) Station Area"}


def query(url, **params):
    params = {"outSR": "4326", "f": "json", "returnGeometry": "true", **params}
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(5):
        try:
            with urllib.request.urlopen(q, timeout=120) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d["features"]
        except Exception:
            if i == 4:
                raise
            time.sleep(2 * (i + 1))


def rings_to_geojson(rings):
    def area(r):
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:])) / 2
    polys = []
    for ring in rings:
        if area(ring) <= 0 or not polys:
            polys.append([ring])
        else:
            polys[-1].append(ring)
    return {"type": "MultiPolygon", "coordinates": polys}


def centroid(rings):
    def area(r):
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:])) / 2
    outer = max(rings, key=lambda r: abs(area(r)))
    a = area(outer)
    if a == 0:
        xs, ys = zip(*outer)
        return sum(xs) / len(xs), sum(ys) / len(ys)
    cx = sum((x0 + x1) * (x0 * y1 - x1 * y0) for (x0, y0), (x1, y1) in zip(outer, outer[1:])) / (6 * a)
    cy = sum((y0 + y1) * (x0 * y1 - x1 * y0) for (x0, y0), (x1, y1) in zip(outer, outer[1:])) / (6 * a)
    return cx, cy


def is_true(v):
    return str(v).strip() == "True"


def condo_candidates(path):
    """Older 5-49 unit condo buildings with separately owned units that pass every other NOAH rule.
    Limited to TMK zone 9 (Ewa district), which contains the Waipahu plan area."""
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        try:
            units, year = float(r["units"]), float(r["yb_main"])
        except ValueError:
            continue
        if (r["tmk8"].startswith("9") and r["ownership"] == "condo, multiple owners" and 5 <= units <= 49
                and year < 1990 and not is_true(r["possibly_demolished"]) and not is_true(r["any_gov_owner"])
                and r["otype"] != "government" and not r["hud_program"] and not is_true(r["large_exemption"])
                and not any(is_true(r[c]) for c in ("resort", "has_hotel", "has_gq", "gq_use", "military"))):
            out.append(r)
    return out


def inside(lon, lat, rings):
    """Even-odd ray casting over every ring, so holes count as outside."""
    hit = False
    for ring in rings:
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            if (y0 > lat) != (y1 > lat) and lon < x0 + (lat - y0) * (x1 - x0) / (y1 - y0):
                hit = not hit
    return hit


def miles(lat0, lon0, lat1, lon1):
    p0, p1 = math.radians(lat0), math.radians(lat1)
    a = (math.sin((p1 - p0) / 2) ** 2
         + math.cos(p0) * math.cos(p1) * math.sin(math.radians(lon1 - lon0) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def bbox(rings, pad):
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def main(map_dir, all_parcels_csv, out_dir):
    plan_rings = [r for f in query(PLAN, where="tod_plan='Waipahu'", outFields="tod_plan,status")
                  for r in f["geometry"]["rings"]]
    districts = query(SPECIAL_DISTRICTS, where="objectid IN (1,2)", outFields="objectid,ord_num,area_ac")
    x0, y0, x1, y1 = bbox(plan_rings, 0.004)
    env = {"geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope", "inSR": "4326",
           "spatialRel": "esriSpatialRelIntersects"}
    stations = [{"name": STATION_NAMES.get(f["attributes"]["station_name_FEIS"], f["attributes"]["station_name_FEIS"]),
                 "lat": round(f["geometry"]["y"], 6), "lon": round(f["geometry"]["x"], 6),
                 "tod": f["attributes"]["station_name_FEIS"] != "Leeward Community College Station"}
                for f in query(STATIONS, where="1=1", outFields="station_name_FEIS", **env)]
    tod_stations = [s for s in stations if s["tod"]]

    # The "bullseye": the city's TOD planning areas use a 1/2-mile radius around each station
    def in_area(lon, lat):
        return (inside(lon, lat, plan_rings)
                or any(inside(lon, lat, d["geometry"]["rings"]) for d in districts)
                or min(miles(lat, lon, s["lat"], s["lon"]) for s in tod_stations) <= BULLSEYE_MILES)

    for s in tod_stations:
        dlat = BULLSEYE_MILES / 69.05
        dlon = BULLSEYE_MILES / (69.17 * math.cos(math.radians(s["lat"])))
        x0, y0 = min(x0, s["lon"] - dlon - 0.003), min(y0, s["lat"] - dlat - 0.003)
        x1, y1 = max(x1, s["lon"] + dlon + 0.003), max(y1, s["lat"] + dlat + 0.003)
    env["geometry"] = f"{x0},{y0},{x1},{y1}"

    guideway = query(GUIDEWAY, where="1=1", outFields="*", maxAllowableOffset="0.00002",
                     geometryPrecision="6", **env)
    streets = query(STREETS, where="1=1", outFields="fullname", maxAllowableOffset="0.00002",
                    geometryPrecision="6", **env)
    # Land comes from the neighborhood boards, fetched at street-level detail so the shared edges meet
    land = query(BOARDS, where="1=1", outFields="towns", maxAllowableOffset="0.00001", geometryPrecision="6", **env)

    noah = json.load(open(f"{map_dir}/noah.json", encoding="utf-8"))
    parcels = {f["properties"]["tmk"]: f for f in json.load(open(f"{map_dir}/parcels.json", encoding="utf-8"))["features"]}
    def tag(r):
        r["district"] = next((DISTRICT_NAMES[d["attributes"]["objectid"]] for d in districts
                              if inside(r["lon"], r["lat"], d["geometry"]["rings"])), None)
        near = min(tod_stations, key=lambda s: miles(r["lat"], r["lon"], s["lat"], s["lon"]))
        r["station"], r["stationMiles"] = near["name"], round(miles(r["lat"], r["lon"], near["lat"], near["lon"]), 2)
        return r

    picked = [tag(dict(r)) for r in noah if in_area(r["lon"], r["lat"])]

    # Condo buildings that would qualify if they had a single owner
    condo_rows = {r["tmk8"]: r for r in condo_candidates(all_parcels_csv)}
    condo_geoms, condo_links = {}, {}
    tmks = list(condo_rows)
    for i in range(0, len(tmks), 150):
        for f in query(PARCELS, where=f"tmk8num IN ({','.join(tmks[i:i + 150])})", outFields="tmk8num,qpub_link",
                       maxAllowableOffset="0.000005", geometryPrecision="6"):
            t = str(f["attributes"]["tmk8num"])
            if f.get("geometry", {}).get("rings"):
                condo_geoms.setdefault(t, []).extend(f["geometry"]["rings"])
                condo_links[t] = f["attributes"].get("qpub_link")
    condos, condo_features = [], []
    for t, rings in condo_geoms.items():
        lon, lat = centroid(rings)
        if not in_area(lon, lat):
            continue
        r = condo_rows[t]
        units = int(float(r["units"]))
        value = float(r["total_value"] or 0)
        condos.append(tag({
            "tmk": t, "lat": round(lat, 6), "lon": round(lon, 6), "units": units, "year": int(float(r["yb_main"])),
            "buildings": int(float(r["n_res_bldgs"])), "unitRecords": int(float(r["n_cpr"])),
            "unitOwners": int(float(r["n_cpr_owners"])), "topShare": round(float(r["top_owner_share"]), 2),
            "valuePerUnit": int(round(value / units, -3)) if value else None, "link": condo_links.get(t)}))
        condo_features.append({"type": "Feature", "properties": {"tmk": t}, "geometry": rings_to_geojson(rings)})

    # Site addresses from the city's address points: the most common street on the parcel, lowest number first
    tmk_list = ",".join(f"'{r['tmk']}'" for r in picked + condos)
    by_tmk = {}
    for f in query(ADDRESSES, where=f"tmk IN ({tmk_list})", outFields="tmk,full_number,housenumber,streetname",
                   returnGeometry="false"):
        a = f["attributes"]
        if a.get("streetname"):
            by_tmk.setdefault(a["tmk"], []).append(a)
    for r in picked + condos:
        pts = by_tmk.get(r["tmk"], [])
        if not pts:
            r["address"] = ""
            continue
        names = [p["streetname"] for p in pts]
        main_street = max(set(names), key=names.count)
        nums = sorted({p["full_number"].rstrip("ABCDEFGHIJ") for p in pts if p["streetname"] == main_street},
                      key=lambda n: [int(x) for x in n.split("-") if x.isdigit()])
        # 94-0819 -> 94-819 and 94-0043 -> 94-043, the usual written form
        number = re.sub(r"^(\d+)-(\d+)$", lambda m: f"{m[1]}-{int(m[2]):03d}", nums[0])
        r["address"] = f"{number} {main_street.title()}" + (f" (+{len(nums) - 1} more)" if len(nums) > 1 else "")

    out = {
        "extent": [x0, y0, x1, y1],
        "noah": picked,
        "parcels": {"type": "FeatureCollection", "features": [parcels[r["tmk"]] for r in picked if r["tmk"] in parcels]},
        "condos": condos,
        "condoParcels": {"type": "FeatureCollection", "features": condo_features},
        "plan": {"type": "Feature", "properties": {"name": "Waipahu Neighborhood TOD Plan"},
                 "geometry": rings_to_geojson(plan_rings)},
        "districts": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": DISTRICT_NAMES[d["attributes"]["objectid"]],
                                               "ord": d["attributes"]["ord_num"],
                                               "acres": round(d["attributes"]["area_ac"])},
             "geometry": rings_to_geojson(d["geometry"]["rings"])} for d in districts]},
        "stations": stations,
        "guideway": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiLineString", "coordinates": f["geometry"]["paths"]}}
            for f in guideway if f.get("geometry")]},
        "streets": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": f["attributes"].get("fullname")},
             "geometry": {"type": "MultiLineString", "coordinates": f["geometry"]["paths"]}}
            for f in streets if f.get("geometry")]},
        "land": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": f["attributes"]["towns"]},
             "geometry": rings_to_geojson(f["geometry"]["rings"])} for f in land if f.get("geometry")]},
    }
    with open(f"{out_dir}/waipahu_tod.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    units = sum(r["units"] for r in picked)
    in_sd = [r for r in picked if r["district"]]
    print(f"{len(picked)} NOAH parcels, {units} units in the Waipahu TOD area (plan boundary or 1/2 mile); "
          f"{len(in_sd)} parcels ({sum(r['units'] for r in in_sd)} units) inside a TOD Special District")
    print(f"{len(condos)} multi-owner condo buildings ({sum(r['units'] for r in condos)} units) in the plan area "
          f"(of {len(condo_rows)} in TMK zone 9)")
    print(f"stations {len(stations)}; guideway {len(guideway)}; streets {len(streets)}; "
          f"land {len(out['land']['features'])}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
