"""reference/CESM3_current.csv (+ Variable Group-MASTER.csv, Priority
Level-MASTER.csv) -> data/cmip7_request.yaml

Resolves the CMIP7 data request against our own catalogue: for each
requested CMIP7 variable, which native CESM history field(s) does it need,
do they exist in data/<component>.yaml, and at what priority. See
notes/cmip7-request-tool-plan.md for the rules this encodes -- in short,
`Formula`/`Scale` are never read (this prices CESM history output, not the
CMIP-side computed value), and a comma-separated `CESM Variable Name` is a
list of native fields CESM must write separately, not a formula to
evaluate.

    python tools/import_cmip7.py

The three input CSVs are local-only (see reference/.gitignore) and not
committed. Missing any of them is not an error: this script prints why and
leaves data/cmip7_request.yaml untouched, so `make build`/`make test` work
for anyone who doesn't have the CMIP7 reference data to hand.
"""

import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import estimator  # noqa: E402  (needs ROOT on sys.path first)

CESM3_CSV = ROOT / "reference" / "CESM3_current.csv"
VARIABLE_GROUP_CSV = ROOT / "reference" / "cmip7-data-request" / "Variable Group-MASTER.csv"
PRIORITY_LEVEL_CSV = ROOT / "reference" / "cmip7-data-request" / "Priority Level-MASTER.csv"
OUTPUT = ROOT / "data" / "cmip7_request.yaml"

# CMIP7's 8 "Modelling Realm - Primary" values -> the data/<component>.yaml
# file(s) that could hold a matching native field, checked in this order.
# A realm-restricted lookup is required, not optional: 8 names (FLDS, FSDS,
# NO3, Q, SST, TAUX, TAUY, U10) exist in more than one component's
# catalogue under different physical meanings, and only the realm says
# which one a given request row means.
REALM_COMPONENTS = {
    "atmos": ["atm"],
    "aerosol": ["atm"],
    "atmosChem": ["atm"],
    "land": ["lnd", "rof"],
    "ocean": ["ocn"],
    "ocnBgchem": ["ocn"],
    "seaIce": ["ice"],
    "landIce": ["glc"],
}

# CMIP7 Frequency -> our stream name. fx/subhr/dec are deliberately absent:
# fx is a one-time file with no "per simulated year" at all, and subhr needs
# a model timestep this tool has never had to track -- see
# notes/cmip7-request-tool-plan.md, open question 3. Rows at those
# frequencies still get their tokens resolved (for visibility) but carry
# stream: null and are excluded from every total until that's revisited.
FREQUENCY_STREAMS = {
    "mon": "month_1",
    "day": "day_1",
    "yr": "year_1",
    "3hr": "hour_3",
    "6hr": "hour_6",
    "1hr": "hour_1",
}

_BRACKET_TAG = re.compile(r"\[[^\]]*\]")
_AVGFLAG_SUFFIX = re.compile(r":[A-Za-z]$")


def normalize_tokens(raw):
    """`CESM Variable Name` -> the list of native CESM fields it names.

    Handles every shape seen in the real column: a plain name; a
    comma-separated list (CESM writes each one separately -- the CMIP side
    sums them later, which is exactly the "target remapping" this tool does
    not price); a `NAME  [COSP]` annotation (not a formula, just a tag
    naming the satellite simulator the field comes from); a trailing
    avgflag suffix (`O3:i`); and the one genuinely arithmetic row in the
    whole request, `SFbc_a4 + bc_a4_CLXF`, handled the same way as a
    comma-list.
    """
    if not raw or not raw.strip() or raw.strip().upper() == "N/A":
        return []
    cleaned = _BRACKET_TAG.sub("", raw)
    tokens = []
    for part in re.split(r"[,+]", cleaned):
        part = part.strip()
        if not part:
            continue
        part = _AVGFLAG_SUFFIX.sub("", part).strip()
        if part:
            tokens.append(part)
    return tokens


def load_priority_values():
    """{"Core": 1, "High": 2, ...} from Priority Level-MASTER.csv."""
    with PRIORITY_LEVEL_CSV.open(newline="", encoding="utf-8-sig") as fh:
        return {row["Name"]: int(row["Value"]) for row in csv.DictReader(fh)}


def load_group_priorities():
    """{variable group name: priority value}, from Variable Group-MASTER.csv
    joined against Priority Level-MASTER.csv by name."""
    priority_values = load_priority_values()
    groups = {}
    with VARIABLE_GROUP_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            level = row["Priority Level"]
            if level not in priority_values:
                raise estimator.DataError(
                    f"{VARIABLE_GROUP_CSV.name}: group {row['Name']!r} has "
                    f"Priority Level {level!r}, not one of "
                    f"{sorted(priority_values)} in {PRIORITY_LEVEL_CSV.name}")
            groups[row["Name"]] = priority_values[level]
    return groups


def row_priority(row, group_priorities):
    """Best (lowest-value) priority across every CMIP7 Variable Group this
    row belongs to, or None if it belongs to none we recognise."""
    groups = [g.strip() for g in row.get("CMIP7 Variable Groups", "").split(",")
              if g.strip()]
    values = [group_priorities[g] for g in groups if g in group_priorities]
    return min(values) if values else None


def index_catalogue(catalogue):
    """{component: {variable name: verified state}}, for a plain name lookup.

    A name can appear twice in one component with different dims (CTSM's
    gridded/subgrid-vector pairs); `verified` is a file-wide default in
    practice today (no per-variable override exists in the real data yet),
    so collapsing to one entry per name loses nothing now. Picking which
    *dims* variant applies to a given stream is deferred to the estimator.py
    join (phase 3), which re-reads data/<component>.yaml directly rather
    than going through this index.
    """
    index = {}
    for component, (_, variables) in catalogue.items():
        by_name = {}
        for var in variables:
            by_name.setdefault(var["name"], var["verified"])
        index[component] = by_name
    return index


def resolve_token(name, realm, index):
    """(component, verified) for a native field name, searched only within
    the component(s) its realm maps to. (None, None) if not found there."""
    for component in REALM_COMPONENTS.get(realm, []):
        verified = index[component].get(name)
        if verified is not None:
            return component, verified
    return None, None


def build_requests():
    catalogue, _ = estimator.load_catalogue()
    index = index_catalogue(catalogue)
    group_priorities = load_group_priorities()
    requests = []
    with CESM3_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            realm = row.get("Modelling Realm - Primary", "")
            frequency = row.get("CMIP7 Frequency", "")
            tokens = []
            for name in normalize_tokens(row.get("CESM Variable Name", "")):
                component, verified = resolve_token(name, realm, index)
                tokens.append({"name": name, "component": component,
                                "verified": verified})
            requests.append({
                "name": row["CMIP7 Compound Name"],
                "realm": realm,
                "frequency": frequency,
                "stream": FREQUENCY_STREAMS.get(frequency),
                "priority": row_priority(row, group_priorities),
                "tokens": tokens,
            })
    return requests


HEADER = """\
# GENERATED by `tools/import_cmip7.py` from reference/CESM3_current.csv +
# reference/cmip7-data-request/{Variable Group,Priority Level}-MASTER.csv.
# Do not hand-edit -- regenerate with `make import-cmip7` whenever the CMIP7
# request CSVs change. See notes/cmip7-request-tool-plan.md for the join
# rules this encodes.

"""


def rel(path):
    """`path`, relative to ROOT when it's actually under it -- tests point
    these module globals at tmp_path, which isn't."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main():
    missing = [p for p in (CESM3_CSV, VARIABLE_GROUP_CSV, PRIORITY_LEVEL_CSV)
               if not p.exists()]
    if missing:
        names = ", ".join(rel(p) for p in missing)
        print(f"skipping: missing {names} (local-only, not committed -- see "
              f"reference/.gitignore). {rel(OUTPUT)} left as-is.")
        return
    requests = build_requests()
    body = yaml.safe_dump({"requests": requests}, sort_keys=False,
                           default_flow_style=False, allow_unicode=True,
                           width=1000)
    OUTPUT.write_text(HEADER + body)
    resolved = sum(1 for r in requests if any(t["component"] for t in r["tokens"]))
    print(f"{rel(OUTPUT)}: {len(requests)} requests, "
          f"{resolved} with at least one resolved token")


if __name__ == "__main__":
    main()
