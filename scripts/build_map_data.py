"""Build the data files for the Oahu NOAH map.

Usage: python build_map_data.py <noah_candidates.csv> <out_dir>

Writes to out_dir:
  noah.json     one record per candidate parcel (centroid, size, year, owner type, links); no owner names
  parcels.json  GeoJSON parcel outlines for the candidates, keyed by TMK
  base.json     GeoJSON neighborhood boards (also the island outline) and major roads
"""
import json
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

PARCELS = "https://geodata.hawaii.gov/arcgis/rest/services/ParcelsZoning/MapServer/11/query"
BOARDS = ("https://services.arcgis.com/tNJpAOha4mODLkXz/arcgis/rest/services/"
          "Neighborhood_Boards_with_Dissolved_Subdistricts/FeatureServer/0/query")
ROADS = "https://geodata.hawaii.gov/arcgis/rest/services/Transportation/MapServer/7/query"


def query(url, **params):
    params = {"outSR": "4326", "f": "json", **params}
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


def signed_area(ring):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:])) / 2


def rings_to_geojson(rings):
    """Esri rings (outer clockwise, holes counter-clockwise) -> GeoJSON MultiPolygon."""
    polys = []
    for ring in rings:
        if signed_area(ring) <= 0 or not polys:  # clockwise in lon/lat = outer ring
            polys.append([ring])
        else:
            polys[-1].append(ring)
    return {"type": "MultiPolygon", "coordinates": polys}


def centroid(rings):
    outer = max(rings, key=lambda r: abs(signed_area(r)))
    a = signed_area(outer)
    if a == 0:
        xs, ys = zip(*outer)
        return sum(xs) / len(xs), sum(ys) / len(ys)
    cx = sum((x0 + x1) * (x0 * y1 - x1 * y0) for (x0, y0), (x1, y1) in zip(outer, outer[1:])) / (6 * a)
    cy = sum((y0 + y1) * (x0 * y1 - x1 * y0) for (x0, y0), (x1, y1) in zip(outer, outer[1:])) / (6 * a)
    return cx, cy


def owner_group(otype):
    return {"corporate/LLC": "Company or LLC", "individual": "Individual or family trust",
            "individual trust": "Individual or family trust",
            "nonprofit/charitable": "Nonprofit or charitable"}.get(otype, "Unclear")


def main(csv_path, out_dir):
    noah = pd.read_csv(csv_path, dtype={"tmk8": str})
    tmks = noah.tmk8.tolist()

    geoms, links = {}, {}
    for i in range(0, len(tmks), 150):
        batch = tmks[i:i + 150]
        for f in query(PARCELS, where=f"tmk8num IN ({','.join(batch)})", outFields="tmk8num,qpub_link",
                       returnGeometry="true", maxAllowableOffset="0.000005", geometryPrecision="6"):
            t = str(f["attributes"]["tmk8num"])
            if f.get("geometry", {}).get("rings"):
                geoms.setdefault(t, []).extend(f["geometry"]["rings"])
                links[t] = f["attributes"].get("qpub_link")
    print(f"parcel shapes found for {len(geoms)} of {len(tmks)} candidates")

    records, features = [], []
    for r in noah.itertuples():
        rings = geoms.get(r.tmk8)
        if not rings:
            continue
        lon, lat = centroid(rings)
        records.append({
            "tmk": r.tmk8, "lat": round(lat, 6), "lon": round(lon, 6),
            "units": int(r.units), "year": int(r.yb_main), "buildings": int(r.n_res_bldgs),
            "type": ("Apartment" if r.any_apartment else "Townhouse" if r.any_townhouse
                     else "Houses or cottages on one lot"),
            "owner": owner_group(r.otype), "multi": bool(r.owner_noah_parcels >= 3),
            "outOfState": bool(r.out_of_state_owner), "condo": r.ownership != "single parcel",
            "board": str(r.boardnum).split(" - ", 1)[-1] if pd.notna(r.boardnum) else "",
            "zone": str(r.zone).split(" - ", 1)[-1] if pd.notna(r.zone) else "",
            "waikikiApt": bool(r.waikiki_apartment_precinct),
            "valuePerUnit": int(round(r.value_per_unit, -3)) if pd.notna(r.value_per_unit) else None,
            "link": links.get(r.tmk8),
        })
        features.append({"type": "Feature", "properties": {"tmk": r.tmk8}, "geometry": rings_to_geojson(rings)})

    boards = query(BOARDS, where="1=1", outFields="towns,board_num", returnGeometry="true",
                   maxAllowableOffset="0.0002", geometryPrecision="5")
    roads = query(ROADS, where="1=1", outFields="fullname,street_class", returnGeometry="true",
                  maxAllowableOffset="0.0002", geometryPrecision="5")
    base = {
        "boards": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": f["attributes"]["towns"], "num": f["attributes"]["board_num"]},
             "geometry": rings_to_geojson(f["geometry"]["rings"])} for f in boards if f.get("geometry")]},
        "roads": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": f["attributes"]["fullname"],
                                               "cls": f["attributes"]["street_class"]},
             "geometry": {"type": "MultiLineString", "coordinates": f["geometry"]["paths"]}}
            for f in roads if f.get("geometry")]},
    }

    with open(f"{out_dir}/noah.json", "w", encoding="utf-8") as fh:
        fh.write("[\n" + ",\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n]\n")
    with open(f"{out_dir}/parcels.json", "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, separators=(",", ":"))
    with open(f"{out_dir}/base.json", "w", encoding="utf-8") as fh:
        json.dump(base, fh, separators=(",", ":"))
    print(f"{len(records)} map records; {len(base['boards']['features'])} boards; "
          f"{len(base['roads']['features'])} road segments")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
