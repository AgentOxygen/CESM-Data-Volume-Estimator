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

Every token gets a mapping `status` and a `component_source`, so the web app
can show how each mapping was derived (see notes/cmip7-namelist-lists-plan.md):

    status             verified          named in CESM3_current.csv AND registered
                                         in a real CESM3 run log
                       cesm2             named in the spreadsheet; only the old
                                         CESM2-seeded data/<comp>.yaml has it
                       spreadsheet-only  named in the spreadsheet; in no log and
                                         not in the catalogue
                       (missing)         no CESM name in the row -> `tokens: []`
    component_source   log | catalogue | realm-fallback (REALM_FALLBACK below)

The input CSVs and reference/log_files/extracted_fields.yaml are local-only
(see reference/.gitignore) and not committed. Missing any of them is not an
error: this script prints why and leaves data/cmip7_request.yaml untouched,
so `make build`/`make test` work for anyone without the reference data.
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
LOG_FIELDS_YAML = ROOT / "reference" / "log_files" / "extracted_fields.yaml"
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

# Primary realm -> the single component a token is filed under when neither a
# log nor the catalogue says where it lives. Draft, for review: every
# token placed this way is flagged `component_source: realm-fallback`. Known
# weak spots: `land` can't tell lnd from rof (rof-only names are caught by the
# log first), and `landIce` is mostly CISM (glc) names no log covers, though
# ~70 landIce tokens turn out to be CTSM (lnd) fields -- those resolve by log.
REALM_FALLBACK = {
    "atmos": "atm",
    "aerosol": "atm",
    "atmosChem": "atm",
    "land": "lnd",
    "ocean": "ocn",
    "ocnBgchem": "ocn",
    "seaIce": "ice",
    "landIce": "glc",
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

# CMIP7 time method (the first dash-separated piece of a compound name's
# branding, e.g. `tavg` in `atmos.tas.tavg-h2m-hxy-u.day.glb`) -> CESM history
# averaging flag, the `:X` in a CAM/CTSM `fincl` entry. Each CESM flag is a
# separate output field, so the same native variable requested as a mean and as
# a maximum is two lines. The second element is a caveat shown in the audit view
# where CESM cannot write the requested quantity directly.
TIME_METHODS = {
    "tavg": ("A", None),
    "tpt": ("I", None),
    "tmax": ("X", None),
    "tmin": ("M", None),
    "tsum": ("SUM", None),
    "ti": (None, "time-invariant: no averaging flag"),
    "tclm": ("A", "climatology: written as a mean; the climatology is formed in post-processing"),
    "tclmdc": ("A", "diurnal-cycle climatology: written as a mean; formed in post-processing"),
    "tmaxavg": ("X", "monthly mean of the daily maximum: CESM writes the daily maximum (X); "
                     "averaging to monthly is post-processing, and the frequency here is the requested one"),
    "tminavg": ("M", "monthly mean of the daily minimum: CESM writes the daily minimum (M); "
                     "averaging to monthly is post-processing, and the frequency here is the requested one"),
}


def time_method(compound_name):
    """(prefix, flag, note) from a compound name's branding piece."""
    prefix = compound_name.split(".")[2].split("-")[0]
    flag, note = TIME_METHODS[prefix]
    return prefix, flag, note


_BRACKET_TAG = re.compile(r"\[[^\]]*\]")
_AVGFLAG_SUFFIX = re.compile(r":[A-Za-z]$")


def split_tokens(raw):
    """`CESM Variable Name` -> [(native field, explicit avgflag or None)]."""
    if not raw or not raw.strip() or raw.strip().upper() == "N/A":
        return []
    cleaned = _BRACKET_TAG.sub("", raw)
    out = []
    for part in re.split(r"[,+]", cleaned):
        part = part.strip()
        flag = _AVGFLAG_SUFFIX.search(part)
        name = _AVGFLAG_SUFFIX.sub("", part).strip()
        if name:
            out.append((name, flag.group()[1:].upper() if flag else None))
    return out


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
    return [name for name, _ in split_tokens(raw)]


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


def load_log_index():
    """{component: {field names registered in that component's real log}}.
    extracted_fields.yaml splits names into `matched`/`new` by whether the
    old catalogue had them -- irrelevant here, so they're re-joined."""
    with LOG_FIELDS_YAML.open() as fh:
        extracted = yaml.safe_load(fh)
    return {component: {f["name"] for f in entry.get("matched", []) + entry.get("new", [])}
            for component, entry in extracted.items()}


def resolve_mapping(name, realm, log_index, cat_index):
    """Everything known about where one native field comes from.

    Log evidence beats the realm: if the log registers `name` in some
    component, that is the component, and `realm_mismatch` records when the
    realm would have pointed elsewhere. A field several components register
    (TSA-style collisions) goes to the first realm-preferred one;
    `log_components` keeps the full list so the ambiguity is auditable.
    """
    preferred = REALM_COMPONENTS.get(realm, [])
    log_components = sorted(c for c, names in log_index.items() if name in names)
    cat_component, cat_state = resolve_token(name, realm, cat_index)
    in_realm = [c for c in preferred if c in log_components]
    if log_components:
        component = (in_realm or log_components)[0]
        source, status = "log", "verified"
    elif cat_component:
        component, source, status = cat_component, "catalogue", "cesm2"
    else:
        component = REALM_FALLBACK.get(realm)
        source, status = "realm-fallback", "spreadsheet-only"
    return {
        "name": name,
        "status": status,
        "component": component,
        "component_source": source,
        "log_components": log_components,
        "catalogue_state": cat_state,
        "realm_mismatch": bool(log_components and not in_realm and preferred),
    }


def split_list(cell):
    """Comma-separated CSV cell -> de-duplicated list, first-seen order."""
    return list(dict.fromkeys(p.strip() for p in cell.split(",") if p.strip()))


def build_requests():
    """(requests, experiments): one record per CSV row, plus
    {experiment: [indices into requests]} for the experiment filter."""
    catalogue, _ = estimator.load_catalogue()
    cat_index = index_catalogue(catalogue)
    log_index = load_log_index()
    group_priorities = load_group_priorities()
    requests = []
    experiments = {}
    with CESM3_CSV.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames                          # read the header first
        while True:
            start_line = reader.line_num + 1       # records can span lines
            row = next(reader, None)
            if row is None:
                break
            realm = row.get("Modelling Realm - Primary", "")
            frequency = row.get("CMIP7 Frequency", "")
            raw = row.get("CESM Variable Name", "")
            prefix, flag, note = time_method(row["CMIP7 Compound Name"])
            tokens = []
            for n, explicit in split_tokens(raw):
                token = resolve_mapping(n, realm, log_index, cat_index)
                # An explicit suffix in the spreadsheet's CESM name (O3:i) wins.
                token["method"] = explicit or flag
                token["method_source"] = ("cesm-name" if explicit
                                          else "compound-name" if flag else None)
                tokens.append(token)
            groups = split_list(row.get("CMIP7 Variable Groups", ""))
            requests.append({
                "name": row["CMIP7 Compound Name"],
                "uid": row.get("UID", ""),
                "source_line": start_line,
                "raw_cesm_name": raw,
                "realm": realm,
                "frequency": frequency,
                "stream": FREQUENCY_STREAMS.get(frequency),
                "priority": row_priority(row, group_priorities),
                "groups": groups,
                # Where a row with no tokens at all would be filed.
                "fallback_component": REALM_FALLBACK.get(realm),
                "time_method": prefix,
                "method_note": note,
                "tokens": tokens,
            })
            for experiment in split_list(row.get("List of Experiments", "")):
                experiments.setdefault(experiment, []).append(len(requests) - 1)
    return requests, dict(sorted(experiments.items()))


def render(requests, experiments):
    return HEADER + yaml.safe_dump(
        {"requests": requests, "experiments": experiments}, sort_keys=False,
        default_flow_style=False, allow_unicode=True, width=1000)


HEADER = """\
# GENERATED by `tools/import_cmip7.py` from reference/CESM3_current.csv +
# reference/cmip7-data-request/{Variable Group,Priority Level}-MASTER.csv +
# reference/log_files/extracted_fields.yaml.
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
    missing = [p for p in (CESM3_CSV, VARIABLE_GROUP_CSV, PRIORITY_LEVEL_CSV,
                           LOG_FIELDS_YAML) if not p.exists()]
    if missing:
        names = ", ".join(rel(p) for p in missing)
        print(f"skipping: missing {names} (local-only, not committed -- see "
              f"reference/.gitignore). {rel(OUTPUT)} left as-is.")
        return
    requests, experiments = build_requests()
    OUTPUT.write_text(render(requests, experiments))
    by_status = {}
    for r in requests:
        for t in r["tokens"]:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    no_name = sum(1 for r in requests if not r["tokens"])
    print(f"{rel(OUTPUT)}: {len(requests)} requests, {len(experiments)} "
          f"experiments; tokens by status {by_status}; "
          f"{no_name} requests with no CESM name (missing)")


if __name__ == "__main__":
    main()
