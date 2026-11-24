# Waipahu TOD NOAH

An interactive map of potential naturally occurring affordable housing (NOAH) around the Hōʻaeʻae (West Loch) and Pouhala (Waipahu Transit Center) rail stations in Waipahu, Oʻahu. NOAH means older, privately owned rental buildings that rent below market without a public subsidy.

**Map:** https://hawaii-appleseed.github.io/Waipahu-TOD-NOAH/

## What the map shows

- **78 buildings, 740 homes** that meet the NOAH definition below, colored by number of homes, owner type or year built.
- **7 older condo buildings, 192 homes**, shown in gray. They meet every rule except single ownership: their units are owned separately, so they are left out of the count.
- **The two adopted TOD Special Districts** (Ord. 2017-054), where zoning allows denser redevelopment.
- **¼- and ½-mile rings around each station.** The city's TOD planning areas use a ½-mile radius.

The map covers both special districts, the 2014 Waipahu Neighborhood TOD Plan area, and anything within ½ mile of either station.

## Definition

The method is adapted from Song & Reid (2026), "The Implications of Naturally Occurring Affordable Housing (NOAH) Sales for Residential Mobility," *Journal of the American Planning Association* 92(3). A parcel counts when it:

1. has 5 to 49 dwelling units, with its main building built before 1990;
2. has one owner for the whole building (a regular parcel, or a condo where one owner holds every unit);
3. is not government-owned;
4. is not HUD-subsidized (LIHTC, project-based Section 8 or public housing);
5. has no large property-tax exemption (more than half of its assessed value);
6. is not used as a hotel, group quarters or military housing, and is not zoned resort.

These are candidates. Rents and building condition have not been checked. Owner type comes from the owner's name on the tax roll. "Company or LLC" includes family holding companies. Owner names are not published here.

## Data sources

- **City & County of Honolulu:** cadastral tables (`FACILITIES`, `SEPARATIONS`, `OWNDAT`, `ASMTGIS`), TOD Plan and TOD Special District boundaries, address points and neighborhood boards.
- **State of Hawaiʻi:** Oʻahu parcels and road layers.
- **HART:** rail stations and guideway.
- **HUD:** LIHTC properties, Multifamily Properties – Assisted, and Public Housing Buildings.

Building records (year built, unit counts) date from about 2013. Ownership and assessed values are from the 2026 tax roll. Data was pulled in November 2026.

## Rebuilding the data

The scripts in `scripts/` need Python 3 and pandas. Run them in this order:

```bash
python scripts/download.py data/                          # city cadastral tables to CSV
python scripts/hud_tmk.py data/hud/                       # HUD points matched to parcels (needs lihtc.json, mfa.json, ph.json from HUD's open data services)
python scripts/hud_tmk_retry.py data/hud/hud_points_tmk.csv
python scripts/noah_filter.py data/ out/                  # island-wide NOAH candidates
python scripts/build_map_data.py out/noah_candidates.csv map/
python scripts/build_waipahu_tod.py map/ out/all_5plus_unit_parcels.csv .   # writes waipahu_tod.json
```

`noah_filter.py` writes owner names and mailing addresses into its CSV outputs. They come from the public tax roll, but keep those files out of the repository.

The map uses [Leaflet](https://leafletjs.com/) 1.9.4 and draws its own base layers, without map tiles.
