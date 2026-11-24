"""Identify NOAH candidate parcels on Oahu following Song & Reid (2026), adapted for Honolulu.

Rules: 5-49 dwelling units on the parcel, main residential building built before 1990,
single ownership (non-condo parcel, or a condo regime with one owner of every unit),
not government-owned, not HUD-subsidized (LIHTC / project-based / public housing),
not resort, hotel, group-quarters or military use.

Usage: python noah_filter.py <data_dir> <out_dir>
  data_dir holds facilities.csv, separations.csv, owndat.csv, asmtgis.csv (City & County of
  Honolulu CadastralTables service) and hud/hud_points_tmk.csv (HUD points matched to TMKs).
"""
import re
import sys

import numpy as np
import pandas as pd

D, OUT = sys.argv[1], sys.argv[2]

# --- Buildings (DPP facilities; vintage ~2013) ---
fac = pd.read_csv(f"{D}/facilities.csv", dtype=str)
fac["dwell"] = pd.to_numeric(fac.dwellcount, errors="coerce").fillna(0)
fac["yb"] = pd.to_numeric(fac.yearbuilt, errors="coerce").where(lambda s: s >= 1850)
code = fac.facilitycode.fillna("")
fac["is_hotel"] = code.str.startswith("11")
fac["is_gq"] = code.str.startswith("06")
fac["is_townhouse"] = code.str.contains("Townhouse")
fac["is_apartment"] = code.str.contains("Apartment")
res = fac[(fac.dwell > 0) & ~fac.is_hotel & ~fac.is_gq].copy()
res = res.sort_values(["tmk", "dwell", "yb"], ascending=[True, False, True])
bld = res.groupby("tmk").agg(
    units=("dwell", "sum"), n_res_bldgs=("dwell", "size"),
    yb_main=("yb", "first"), yb_min=("yb", "min"), yb_max=("yb", "max"),
    any_townhouse=("is_townhouse", "any"), any_apartment=("is_apartment", "any"))
flags = fac.groupby("tmk").agg(has_hotel=("is_hotel", "any"), has_gq=("is_gq", "any"))
bld = bld.join(flags, how="left")

# --- Zoning / land use (largest separation on each TMK) ---
sep = pd.read_csv(f"{D}/separations.csv", dtype=str)
sep["sf"] = pd.to_numeric(sep.split_sf, errors="coerce").fillna(0)
zone, act = sep.zone.fillna(""), sep.activitycode.fillna("")
sep["resort"] = zone.str.contains("Resort") | act.str.startswith("02 ")
sep["gq_use"] = act.str.match(r"0[34] ")
sep["military"] = zone.str.contains("Military") | act.str.startswith("62 ")
top = sep.sort_values("sf", ascending=False).drop_duplicates("tmk").set_index("tmk")[
    ["zone", "lud", "boardnum", "tract", "block", "activitycode"]]
sflags = sep.groupby("tmk")[["resort", "gq_use", "military"]].any()

# --- Owners (current fee owner per TMK + CPR unit) ---
own = pd.read_csv(f"{D}/owndat.csv", dtype=str)
own["tmk8"], own["cpr"] = own.parid.str[:8], own.parid.str[8:12]


def norm(n):
    n = re.sub(r"[^A-Z0-9 ,&]", " ", str(n).upper())
    n = re.sub(r"\b(TRS?|TRUSTEES?|ET AL|ETAL)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip(" ,")


GOV = re.compile(r"STATE OF HAWAII|CITY (AND|&) COUNTY|CITY & CO|UNITED STATES OF AMERICA|HAWAII PUBLIC HOUSING|"
                 r"HAWAII HOUSING AUTH|HOUSING FINANCE (AND|&) DEV|HHFDC|HAWAIIAN HOME LANDS|UNIVERSITY OF HAWAII|"
                 r"HAWAII COMMUNITY DEV|BOARD OF WATER SUPPLY|DEPT OF|DEPARTMENT OF|REPUBLIC OF")
NPO = re.compile(r"FOUNDATION|\bFDN\b|CHURCH|\bCH OF\b|MINISTR|DIOCESE|CATHOLIC|SALVATION ARMY|YMCA|YWCA|"
                 r"HABITAT FOR HUMANITY|LAND TRUST|MUTUAL HOUSING|HALE MAHAOLU|SELF HELP HOUSING|KAMEHAMEHA SCHOOLS|"
                 r"BERNICE PAUAHI|LILIUOKALANI TRUST|LUNALILO|QUEEN EMMA|QUEEN'?S MEDICAL|NONPROFIT|NON PROFIT|CHARIT|"
                 r"MISSION|TEMPLE|HONGWANJI|\bSCHOOL\b|INSTITUTE|HOSPITAL|BENEVOLENT|\bSOCIETY\b|\bTONG\b|KYOKAI|"
                 r"CULTURAL CENTER|COUNCIL FOR|PROGRAMS|FAMILY PROMISE|CEMETERY|SHINNYO|ZEN\b|\w+JI\b")
# Large private ground lessors: the city tables list them as fee owner, so the building owner is not visible
GROUND_LESSOR = re.compile(r"KAMEHAMEHA SCHOOLS|BERNICE PAUAHI|QUEEN EMMA LAND|LILIUOKALANI TRUST|LUNALILO|"
                           r"CAMPBELL ESTATE|JAMES CAMPBELL|DAMON ESTATE|SAMUEL M DAMON")
CORP = re.compile(r"\b(LLC|L L C|INC|INCORPORATED|CORP|CORPORATION|LTD|LIMITED|LP|L P|LLP|LLLP|CO|COMPANY|PARTNERS|"
                  r"PARTNERSHIP|PART|ASSOC|ASSOCIATES|HOLDINGS?|PROPERT(Y|IES)|INVEST\w*|REALTY|ENTERPRISES?|"
                  r"DEVELOPMENT|BANK|FUND|CAPITAL|VENTURES?|GROUP|MANAGEMENT|EQUITIES|SVC|MAINT|HUI)\b|LLC$")
TRUST = re.compile(r"\bTRS?\b|TRUST")


def owner_type(raw):
    n = str(raw).upper()
    if GOV.search(n):
        return "government"
    if NPO.search(n):
        return "nonprofit/charitable"
    if "," in n:
        return "individual trust" if TRUST.search(n) else "individual"
    if CORP.search(n):
        return "corporate/LLC"
    if TRUST.search(n):
        return "individual trust"
    return "other/unclear"


own["owner_norm"] = own.taxbillowner.map(norm)
own["otype"] = own.taxbillowner.map(owner_type)

units_own = own[own.cpr != "0000"]
cpr = units_own.groupby("tmk8").agg(
    n_cpr=("cpr", "size"), n_cpr_owners=("owner_norm", "nunique"),
    top_owner_share=("owner_norm", lambda s: s.value_counts(normalize=True).iloc[0]))
base = own.sort_values("cpr").drop_duplicates("tmk8").set_index("tmk8")
# addrnum/addrstreet/addrtype in OWNDAT are the owner's tax-bill mailing address, not the property's
owners = base[["taxbillowner", "owner_norm", "otype", "taxbillstate", "taxbillcountry",
               "addrnum", "addrstreet", "addrtype"]].rename(columns={
    "addrnum": "owner_mail_number", "addrstreet": "owner_mail_street", "addrtype": "owner_mail_type"}).join(cpr, how="left")
owners["n_cpr"] = owners.n_cpr.fillna(0).astype(int)
is_condo = owners.n_cpr > 0
# owner of record: base (0000) record for non-condo parcels, the most common unit owner for condo regimes
top_unit_owner = units_own.groupby("tmk8").taxbillowner.agg(lambda s: s.value_counts().index[0])
owners.loc[is_condo, "taxbillowner"] = top_unit_owner.reindex(owners.index[is_condo]).values
owners.loc[is_condo, "owner_norm"] = owners.loc[is_condo, "taxbillowner"].map(norm)
owners.loc[is_condo, "otype"] = owners.loc[is_condo, "taxbillowner"].map(owner_type)
owners["ownership"] = np.select(
    [~is_condo, is_condo & (owners.n_cpr_owners == 1)],
    ["single parcel", "condo, one owner of all units"], "condo, multiple owners")
owners["any_gov_owner"] = own.groupby("tmk8").otype.agg(lambda s: (s == "government").any())

# --- Assessed values (2026) ---
asm = pd.read_csv(f"{D}/asmtgis.csv", dtype=str)
for c in ["buildingvalue", "landvalue", "buildingexemption", "landexemption"]:
    asm[c] = pd.to_numeric(asm[c], errors="coerce").fillna(0)
asm["tmk8"] = asm.parid.str[:8]
val = asm.groupby("tmk8")[["buildingvalue", "landvalue", "buildingexemption", "landexemption"]].sum()

# --- HUD-subsidized parcels ---
hud = pd.read_csv(f"{D}/hud/hud_points_tmk.csv", dtype=str)
hud = hud.assign(tmk8=hud.tmk8.str.split(";")).explode("tmk8")
hud_prog = hud.groupby("tmk8").program.agg(lambda s: "; ".join(sorted(set(s))))
hud_match = hud.groupby("tmk8").match.agg(lambda s: "exact" if (s == "point-in-parcel").any() else "within 25 m")

# --- Assemble ---
df = bld.join(top, how="left").join(sflags, how="left").join(owners, how="left").join(val, how="left")
df["hud_program"], df["hud_match"] = hud_prog.reindex(df.index), hud_match.reindex(df.index)
for c in ["has_hotel", "has_gq", "resort", "gq_use", "military", "any_gov_owner"]:
    df[c] = df[c].astype("boolean").fillna(False).astype(bool)
df["total_value"] = df.buildingvalue + df.landvalue
df["value_per_unit"] = df.total_value / df.units
df["possibly_demolished"] = df.buildingvalue.fillna(0) == 0
df["large_exemption"] = (df.buildingexemption + df.landexemption) > 0.5 * df.total_value
df["ground_lessor_owner"] = df.taxbillowner.fillna("").str.upper().str.contains(GROUND_LESSOR)
df["waikiki_apartment_precinct"] = df.zone.fillna("").str.contains("Waikiki Special District")

steps = [
    ("Parcels with 5+ dwelling units (excl. hotel and group-quarter buildings)", df.units >= 5),
    ("...with 5-49 units", df.units <= 49),
    ("...main building built before 1990", df.yb_main < 1990),
    ("...building still on the current tax roll (owner record, building value > 0)",
     df.ownership.notna() & ~df.possibly_demolished),
    ("...single owner (non-condo, or one owner of every condo unit)", df.ownership != "condo, multiple owners"),
    ("...not government-owned", ~df.any_gov_owner & (df.otype != "government")),
    ("...not HUD-subsidized (LIHTC, project-based Sec. 8, public housing)", df.hud_program.isna()),
    ("...no large property-tax exemption (tax-exempt institution or regulated affordable)", ~df.large_exemption),
    ("...not resort, hotel, group-quarters or military use",
     ~(df.resort | df.has_hotel | df.has_gq | df.gq_use | df.military)),
]
mask = pd.Series(True, index=df.index)
funnel = []
for label, cond in steps:
    cond = cond.astype("boolean").fillna(False).astype(bool)
    before = mask.copy()
    mask &= cond
    funnel.append((label, int(mask.sum()), int(df.loc[mask, "units"].sum())))
    if "single owner" in label:
        multi = before & ~cond
        funnel.append(("   [dropped at this step: multi-owner condo buildings]",
                       int(multi.sum()), int(df.loc[multi, "units"].sum())))
df["noah"] = mask

# Comparison group for the value check: same size and ownership rules, built 1990 or later
newer = (df.units.between(5, 49) & (df.yb_main >= 1990) & (df.ownership != "condo, multiple owners")
         & ~df.any_gov_owner & df.hud_program.isna())

noah = df[df.noah].copy()
port = noah.groupby("owner_norm").size()
noah["owner_noah_parcels"] = noah.owner_norm.map(port)
noah["out_of_state_owner"] = (noah.taxbillstate.fillna("HI").ne("HI")
                              | noah.taxbillcountry.fillna("").str.strip().ne(""))
noah.index.name = df.index.name = "tmk8"
noah.to_csv(f"{OUT}/noah_candidates.csv")
df[df.units >= 5].to_csv(f"{OUT}/all_5plus_unit_parcels.csv")

print("FUNNEL (parcels, units)")
for label, n, u in funnel:
    print(f"  {n:>6,}  {u:>8,}  {label}")
buckets = pd.cut(noah.units, [4, 10, 20, 30, 49], labels=["5-10", "11-20", "21-30", "31-49"])
print("\nUnits per building:", buckets.value_counts().sort_index().to_dict())
print("Decade built:", (noah.yb_main // 10 * 10).astype(int).value_counts().sort_index().to_dict())
print("Ownership:", noah.ownership.value_counts().to_dict())
print("Owner type (parcels):", noah.otype.value_counts().to_dict())
print("Owner type (units):", noah.groupby("otype").units.sum().astype(int).to_dict())
print("Owners holding 3+ NOAH parcels:", int((port >= 3).sum()), "owners;",
      int((noah.owner_noah_parcels >= 3).sum()), "parcels")
print("Out-of-state owner address:", int(noah.out_of_state_owner.sum()))
print("Flags: nonprofit owner", int((noah.otype == "nonprofit/charitable").sum()),
      "| ground-lessor fee owner (likely leasehold)", int(noah.ground_lessor_owner.sum()),
      "| Waikiki Apartment Precinct", int(noah.waikiki_apartment_precinct.sum()),
      "| townhouse-type buildings", int(noah.any_townhouse.sum()))

# Value check (the paper's robustness test): per-unit assessed value vs. newer housing
unit_vals = asm[asm.parid.str[8:12] != "0000"].assign(v=lambda a: a.buildingvalue + a.landvalue)
unit_vals = unit_vals.join(df[["yb_main", "units"]], on="tmk8", how="inner")
newer_condo_units = unit_vals[(unit_vals.yb_main >= 1990) & (unit_vals.units >= 5)].v
older_condo_units = unit_vals[(unit_vals.yb_main < 1990) & unit_vals.units.between(5, 49)].v
print(f"\nMedian assessed value per unit (2026): NOAH ${noah.value_per_unit.median():,.0f}")
print(f"  vs. single-owner 5-49 unit buildings built 1990+: ${df.loc[newer, 'value_per_unit'].median():,.0f} "
      f"(n={int(newer.sum())} buildings)")
print(f"  vs. condo units in buildings built 1990+: ${newer_condo_units.median():,.0f} (n={len(newer_condo_units):,} units)")
print(f"  vs. condo units in pre-1990 5-49 unit buildings: ${older_condo_units.median():,.0f} "
      f"(n={len(older_condo_units):,} units)")
print("\nTop neighborhood boards (parcels, units):")
print(noah.groupby("boardnum").agg(parcels=("units", "size"), units=("units", "sum"))
      .sort_values("parcels", ascending=False).head(15).to_string())
in_scope = df.units.between(5, 49) & (df.yb_main < 1990)
print("\nHUD-matched parcels among 5-49 unit, pre-1990:", int((in_scope & df.hud_program.notna()).sum()),
      df.loc[in_scope & df.hud_program.notna(), "hud_match"].value_counts().to_dict())
