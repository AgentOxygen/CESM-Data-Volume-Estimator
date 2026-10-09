"""reference/CESM3_current.csv (+ Variable Group-MASTER.csv, Priority
Level-MASTER.csv) -> data/cmip7_request.yaml

Resolves the CMIP7 data request against CESM3: for each requested CMIP7
variable, which native CESM history field(s) does it need, does a real run
log or the CESM3 source register them, and at what priority. The rules,
in short: `Formula`/`Scale` are never read (this prices CESM history output, not the
CMIP-side computed value), and a comma-separated `CESM Variable Name` is a
list of native fields CESM must write separately, not a formula to
evaluate.

    python tools/import_cmip7.py

Every token gets a mapping `status` and a `component_source`, so the web app
can show how each mapping was derived:

    status             verified          named in CESM3_current.csv AND registered
                                         in a real CESM3 run log
                       source            not in the log, but the CESM3 source registers
                                         it for SOURCE_CONFIG (cesm-field-scraper); the
                                         token's `source_certainty` says how firmly
                                         (literal name / expanded from a loop / pattern)
                       spreadsheet-only  named in the spreadsheet; in no log and not in
                                         the source
                       (missing)         no CESM name in the row -> `tokens: []`
    component_source   log | source | realm-fallback (REALM_FALLBACK below)

The input CSVs and reference/log_files/extracted_fields.yaml are local-only
(see reference/.gitignore) and not committed. Missing any of them is not an
error: this script prints why and leaves data/cmip7_request.yaml untouched,
so `make build`/`make test` work for anyone without the reference data.
"""

import csv
import fnmatch
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent



class DataError(Exception):
    """A problem in the input CSVs."""


CESM3_CSV = ROOT / "reference" / "CESM3_current.csv"
VARIABLE_GROUP_CSV = ROOT / "reference" / "cmip7-data-request" / "Variable Group-MASTER.csv"
PRIORITY_LEVEL_CSV = ROOT / "reference" / "cmip7-data-request" / "Priority Level-MASTER.csv"
LOG_FIELDS_YAML = ROOT / "reference" / "log_files" / "extracted_fields.yaml"
OUTPUT = ROOT / "data" / "cmip7_request.yaml"
ALIASES_YAML = ROOT / "data" / "aliases.yaml"

# The CESM3 source catalogue (local-only output of cesm-field-scraper, like reference/) and the
# configuration of it that decides which registrations count. Absent => no source evidence, and
# statuses rest on the run log alone.
SCRAPER = ROOT / "cesm-field-scraper"
SOURCE_CONFIG = "BHISTE_MTt4s"
SOURCE_COMPONENTS = ["atm", "lnd", "ice", "ocn", "glc", "rof"]

# CMIP7's 8 "Modelling Realm - Primary" values -> the component(s) that could
# register a matching native field, in preference order. A realm-restricted
# lookup is required, not optional: names such as FLDS, FSDS, NO3, Q, SST,
# TAUX, TAUY and U10 exist in more than one component under different
# physical meanings, and only the realm says which one a row means.
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
# log nor the source says where it lives. Draft, for review: every
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
# a model timestep this tool has never had to track. Rows at those
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
                raise DataError(
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


def load_log_index():
    """{component: {field names registered in that component's real log}}."""
    with LOG_FIELDS_YAML.open() as fh:
        extracted = yaml.safe_load(fh)
    return {component: {f["name"] for f in entry.get("fields", [])}
            for component, entry in extracted.items()}


def load_source_index(scraper=None, config_name=None):
    """{component: {"exact": {name: (certainty, ref, dims, horizontal)}, "patterns": [(glob, ref)]}} of the
    registrations CESM3's source makes under one configuration, from cesm-field-scraper/out; None if absent.

    `certainty` is `literal` (a name in a registration call) or `expanded` (one of many a loop expands
    to, so the run decides). A literal record beats an expanded one for the same name, and one with a
    horizontal grid beats one without; `dims` are the non-horizontal dimension names (None if unresolved)."""
    scraper = Path(scraper or SCRAPER)
    configs, out = scraper / "configurations.yaml", scraper / "out"
    if not (configs.exists() and out.exists()):
        return None
    sys.path.insert(0, str(ROOT / "cesm-field-scraper"))       # its evaluator is the one source of truth for `requires`
    from cesm_fields.config import active, load
    config = load(configs, config_name or SOURCE_CONFIG)
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    index = {}
    for component in SOURCE_COMPONENTS:
        path = out / f"{component}.yaml"
        if not path.exists():
            continue
        exact, patterns = {}, []
        for r in yaml.load(path.read_text(), Loader=loader)["fields"]:
            if not active(r, config):
                continue
            if r["name"]:
                certainty = "expanded" if "alternatives" in r else "literal"
                entry = (certainty, r["source"], r.get("dims"), r.get("horizontal"))
                rank = lambda e: (e[0] == "literal", e[3] is not None)
                if r["name"] not in exact or rank(entry) > rank(exact[r["name"]]):
                    exact[r["name"]] = entry
            else:
                patterns += [(g, r["source"]) for g in r.get("name_patterns") or []]
        index[component] = {"exact": exact, "patterns": patterns}
    return index


def source_configuration():
    """Name of the source configuration the statuses were derived from, or None when no scraper output exists."""
    return SOURCE_CONFIG if (SCRAPER / "out").exists() and (SCRAPER / "configurations.yaml").exists() else None


def load_aliases(path=None):
    """{spreadsheet CESM name: catalogue name} from the hand-reviewed data/aliases.yaml."""
    path = Path(path or ALIASES_YAML)
    return (yaml.safe_load(path.read_text()) or {}).get("aliases", {}) if path.exists() else {}


def source_hits(name, src_index):
    """[(component, "exact"|"pattern", certainty, ref, dims, horizontal)] for the components whose source registers `name`."""
    hits = []
    for component, entry in (src_index or {}).items():
        if name in entry["exact"]:
            certainty, ref, dims, horizontal = entry["exact"][name]
            hits.append((component, "exact", certainty, ref, dims, horizontal))
        else:
            ref = next((r for g, r in entry["patterns"] if fnmatch.fnmatchcase(name, g)), None)
            if ref:
                hits.append((component, "pattern", "pattern", ref, None, None))
    return hits


def alias_candidates(name, aliases):
    """Names to try for a spreadsheet name, in order: itself, a reviewed alias, then the daily-variant rule.

    The spreadsheet writes a daily CICE field as `siage_d` where CICE has one switch, `f_siage`, that
    covers every stream; the generic `_d` strip is only used if it finds evidence (the caller checks)."""
    out = [name]
    if name in aliases:
        out.append(aliases[name])
    if name.endswith("_d"):
        out.append(name[:-2])
    return list(dict.fromkeys(out))


def resolve_mapping(name, realm, log_index, src_index=None, aliases=None):
    """Everything known about where one native field comes from.

    Evidence, strongest first: the CESM3 run log (`verified`), the CESM3 source (`source`), nothing
    (`spreadsheet-only`). Log evidence beats the realm: if the log registers `name` in some
    component, that is the component, and `realm_mismatch` records when the realm would have
    pointed elsewhere. A field several components register (TSA-style collisions) goes to the first
    realm-preferred one; `log_components` keeps the full list so the ambiguity is auditable. If
    `name` itself has no evidence, `alias_candidates` are tried and the first with evidence is used
    (`alias_of` records which). Source facts about the chosen component (`source_*`, `dims`,
    `horizontal`) are kept whatever the status, since pricing needs the dims of a logged field too.
    """
    preferred = REALM_COMPONENTS.get(realm, [])

    def evidence(n):
        return sorted(c for c, names in log_index.items() if n in names), source_hits(n, src_index)

    alias_of, (log_components, hits) = None, evidence(name)
    if not (log_components or hits):
        for candidate in alias_candidates(name, aliases or {})[1:]:
            found = evidence(candidate)
            if found[0] or found[1]:
                alias_of, (log_components, hits) = candidate, found
                break
    in_realm = [c for c in preferred if c in log_components]
    src_components = [h[0] for h in sorted(hits, key=lambda h: (h[0] not in preferred, h[1] != "exact"))]
    if log_components:
        component = (in_realm or log_components)[0]
        source, status = "log", "verified"
    elif hits:
        component, source, status = src_components[0], "source", "source"
    else:
        component = REALM_FALLBACK.get(realm)
        source, status = "realm-fallback", "spreadsheet-only"
    best = next((h for h in sorted(hits, key=lambda h: h[1] != "exact") if h[0] == component), None)
    return {
        "name": name,
        "status": status,
        "component": component,
        "component_source": source,
        "log_components": log_components,
        "realm_mismatch": bool(log_components and not in_realm and preferred),
        "alias_of": alias_of,
        "source_certainty": best[2] if best else None,
        "source_ref": best[3] if best else None,
        "dims": best[4] if best else None,
        "horizontal": best[5] if best else None,
    }


def split_list(cell):
    """Comma-separated CSV cell -> de-duplicated list, first-seen order."""
    return list(dict.fromkeys(p.strip() for p in cell.split(",") if p.strip()))


def build_requests():
    """(requests, experiments): one record per CSV row, plus
    {experiment: [indices into requests]} for the experiment filter."""
    log_index = load_log_index()
    src_index, aliases = load_source_index(), load_aliases()
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
                token = resolve_mapping(n, realm, log_index, src_index, aliases)
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


def render(requests, experiments, source_configuration=None):
    return HEADER + yaml.safe_dump(
        {"source_configuration": source_configuration, "requests": requests, "experiments": experiments}, sort_keys=False,
        default_flow_style=False, allow_unicode=True, width=1000)


HEADER = """\
# GENERATED by `tools/import_cmip7.py` from reference/CESM3_current.csv +
# reference/cmip7-data-request/{Variable Group,Priority Level}-MASTER.csv +
# reference/log_files/extracted_fields.yaml + cesm-field-scraper/out (CESM3 source).
# Do not hand-edit -- regenerate with `make import-cmip7` whenever the CMIP7
# request CSVs change. The join rules are in that script's docstring.

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
    OUTPUT.write_text(render(requests, experiments, source_configuration()))
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
