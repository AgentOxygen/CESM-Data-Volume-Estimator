"""reference/log_files/*.log.* -> the fields a real CESM3 run registered.

A CIME case's component logs each print their own field registry during
initialization -- independent of what a namelist chose to output, so this
is closer to "everything this component COULD write" than a history-file
header is. See notes/cesm-source-scraper-evaluation.md for why this is
preferable to parsing Fortran source, and the exact log markers each
component uses.

    python tools/extract_log_fields.py

Reads whatever `reference/log_files/<component>.log.*` files exist
(local-only, not committed -- same as every other reference/ input) and
prints a summary. The full lists behind it are written to
`reference/log_files/extracted_fields.yaml` (also local-only -- same
gitignore as everything else under reference/), which tools/import_cmip7.py
reads as the "verified" evidence. Missing log files for a component is not an
error: this is run against whatever logs happen to exist.

What this *can't* give you, by component:
  atm (CAM), lnd (CTSM), rof (MOSART)
      A genuine "MASTER FIELD LIST" -- every field registered, not just
      what this run's namelist chose to write. Treated as the complete
      universe for that component, in this CESM3 configuration.
  ice (CICE)
      No such list exists in the log. What's parsed here
      ("will be written to the history tape") is only the ACTIVE subset
      this run's namelist selected -- a verified subset, like a history
      file header, not a complete catalogue. Don't conflate the two.
  ocn (MOM6)
      No consolidated list at all. What's harvested is whatever field
      names happen to appear in passing NOTE/WARNING lines from the FMS
      diag_manager -- a lucky-dip partial list, not remotely complete.
  glc (CISM), wav
      Nothing extracted. CISM's real source (see
      notes/cesm-source-scraper-evaluation.md) is its declarative
      `*_vars.def` files, not this log; wav isn't one of our 6 components.
"""

import re
from collections import OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

LOG_DIR = ROOT / "reference" / "log_files"
OUTPUT = LOG_DIR / "extracted_fields.yaml"

# A name this long in a MASTER FIELD LIST entry may be silently truncated by
# the component's fixed-width write statement (confirmed for lnd/rof: CTSM's
# `M_LIVESTEMC_STORAGE_TO_LITTER_FI` is missing its trailing `RE`). Flag,
# don't trust, anything at or past this length.
TRUNCATION_SUSPECT_LEN = 32

_RICH_ENTRY = re.compile(
    r"^\s*\d+\s+(.*?)\s+(\d+)\s+([A-Z])\s\s(.*)$")           # atm: name[ units] numlev avgflag long_name
_PLAIN_ENTRY = re.compile(r"^\s*\d+\s+(\S+)\s+(.*?)\s*$")    # lnd/rof: name units
# `units` is everything after `name` to end of line, not just one token --
# a handful of CTSM entries use a free-text description there instead of a
# real unit (e.g. "a fraction betwe[en] ..."), itself truncated by the same
# fixed-width format.
# CICE's table is genuinely fixed-width (every one of 122 real rows is
# exactly 83 characters), not whitespace-delimited -- its `units` column
# can itself contain a space ("10^-6 m"), which a whitespace-split parser
# cannot tell apart from the column boundary. Measured directly against
# reference/log_files/ice.log.*; a differently-configured run (e.g. a wider
# frequency-mask field for a case with more active history streams) could
# shift these, so re-measure if a new log's rows aren't 83 chars.
_CICE_DESC, _CICE_UNITS, _CICE_NAME = slice(0, 43), slice(43, 61), slice(61, 74)

# \w+ (word chars only), not \S+ -- the real log sometimes runs a field
# name directly into trailing punctuation with no space ("ALK_RIV_FLUX,
# skip one time level"), which \S+ would capture as part of the name.
_OCN_FIELD = re.compile(r"module/(?:output_field|field)\s+(\w+)/(\w+)")


def find_logs(component):
    return sorted(LOG_DIR.glob(f"{component}.log.*"))


def parse_master_field_list(text, marker):
    """Entries after `marker` in an atm/lnd/rof-style log. Handles both the
    5-column (name, units, numlev, avgflag, long_name) and 2-column
    (name, units) shapes -- which one a given log uses is fixed per
    component, not per line, but trying the richer pattern first and
    falling back is simpler than threading that through as an argument.

    Stops at the first line that matches neither pattern, once at least one
    entry has matched. The table really does end at a blank line in these
    logs -- without this, a per-timestep line elsewhere in a multi-megabyte
    log that happens to fit the same shape gets treated as a 3246th field.
    """
    start = text.find(marker)
    if start == -1:
        return [], []
    fields = OrderedDict()
    for line in text[start + len(marker):].splitlines():
        m = _RICH_ENTRY.match(line)
        if m:
            rest, numlev, avgflag, long_name = m.groups()
            parts = rest.split()
            name, units = parts[0], (parts[1] if len(parts) > 1 else "")
            fields[name] = {"units": units, "numlev": int(numlev),
                             "avgflag": avgflag, "long_name": long_name}
            continue
        m = _PLAIN_ENTRY.match(line)
        if m:
            name, units = m.groups()
            fields.setdefault(name, {"units": units})
            continue
        if fields:
            break
    return list(fields.values()), list(fields.keys())


def parse_cice_active_fields(text):
    """The CICE "will be written to the history tape" table -- the ACTIVE
    subset for this run's namelist, not a master list. See module
    docstring: don't treat this the same as the other three."""
    marker = "will be written to the history tape:"
    start = text.find(marker)
    if start == -1:
        return [], []
    lines = iter(text[start + len(marker):].splitlines())
    for line in lines:
        if line.strip().startswith("description"):
            break
    else:
        return [], []
    fields = OrderedDict()
    for line in lines:
        if not line.strip():
            break
        name = line[_CICE_NAME].strip()
        if not name:
            continue
        freq = line[74:].split()[0] if line[74:].split() else ""
        fields[name] = {"units": line[_CICE_UNITS].strip(),
                         "long_name": line[_CICE_DESC].strip(), "freq": freq}
    return list(fields.values()), list(fields.keys())


def harvest_ocn_field_mentions(text):
    """Whatever field names happen to appear in FMS diag_manager NOTE/WARNING
    lines. Not a list of anything in particular -- see module docstring."""
    seen = OrderedDict()
    for module, name in _OCN_FIELD.findall(text):
        seen.setdefault((module, name), None)
    return list(seen.keys())


def flag_truncated(names):
    return [n for n in names if len(n) >= TRUNCATION_SUSPECT_LEN]


def report(component, fields, names, extra=""):
    """Print the summary and return {"fields": [...]} -- the full field dicts
    (with `name` merged in), sorted by name, so the caller can persist them."""
    by_name = dict(zip(names, fields))
    print(f"\n{component}: {len(names)} names found{extra}")
    suspect = flag_truncated(names)
    if suspect:
        print(f"  {len(suspect)} names >= {TRUNCATION_SUSPECT_LEN} chars, "
              f"possibly truncated by the log's fixed-width format: "
              f"{suspect[:3]}")
    return {"fields": [{"name": n, **by_name[n]} for n in sorted(names)]}


def main():
    result = {}

    for component, marker in (("atm", "MASTER FIELD LIST"),
                               ("lnd", "LIST OF ALL HISTORY FIELDS"),
                               ("rof", "MASTER FIELD LIST")):
        logs = find_logs(component)
        if not logs:
            print(f"\n{component}: no reference/log_files/{component}.log.* found, skipping")
            continue
        all_fields = OrderedDict()
        for log in logs:
            fields, names = parse_master_field_list(log.read_text(errors="replace"), marker)
            all_fields.update(zip(names, fields))
        names = list(all_fields)
        found = report(component, list(all_fields.values()), names)
        result[component] = {"kind": "master_field_list", **found}

    logs = find_logs("ice")
    if logs:
        all_fields = OrderedDict()
        for log in logs:
            fields, names = parse_cice_active_fields(log.read_text(errors="replace"))
            all_fields.update(zip(names, fields))
        names = list(all_fields)
        found = report("ice", list(all_fields.values()), names,
                        extra=" (ACTIVE subset for this run's namelist only -- not a master list)")
        result["ice"] = {"kind": "active_subset", **found}
    else:
        print("\nice: no reference/log_files/ice.log.* found, skipping")

    logs = find_logs("ocn")
    if logs:
        all_pairs = OrderedDict()
        for log in logs:
            for pair in harvest_ocn_field_mentions(log.read_text(errors="replace")):
                all_pairs[pair] = None
        pairs = list(all_pairs)
        print(f"\nocn: {len(pairs)} (module, field) mentions harvested from "
              f"NOTE/WARNING lines -- a partial, lucky-dip list, not a "
              f"master field list (MOM6 has none in its log; see "
              f"notes/cesm-source-scraper-evaluation.md)")
        fields = sorted(({"name": f, "module": m} for m, f in pairs), key=lambda d: d["name"])
        result["ocn"] = {"kind": "partial_log_mentions", "fields": fields}
    else:
        print("\nocn: no reference/log_files/ocn.log.* found, skipping")

    print("\nglc: not extracted from logs -- use CISM's *_vars.def files instead "
          "(see notes/cesm-source-scraper-evaluation.md)")

    if result:
        OUTPUT.parent.mkdir(exist_ok=True)
        OUTPUT.write_text(
            "# GENERATED by tools/extract_log_fields.py from reference/log_files.\n"
            "# Read by tools/import_cmip7.py as the run-log evidence.\n\n"
            + yaml.safe_dump(result, sort_keys=False, default_flow_style=False,
                              allow_unicode=True, width=1000))
        print(f"\nfull lists written to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
