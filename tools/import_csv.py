"""One-time seeder: reference/lens2output200129.csv -> data/<component>.yaml

Throwaway scaffolding. The YAML files are the source of truth once generated;
future imports from other sources (CAM addfld, CTSM hist_addfld, ncdump) will be
separate scripts. Don't invest here.

    python tools/import_csv.py    # overwrites data/*.yaml
"""

import csv
from collections import OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "reference" / "lens2output200129.csv"
FIELDS = ("component", "tier", "stream", "name", "cell_methods", "long_name",
          "units", "dims")

HORIZ_DIMS = {"atm": ["lat", "lon"], "lnd": ["lat", "lon"],
              "ocn": ["nlat", "nlon"], "ice": ["nj", "ni"],
              "rof": ["lat", "lon"], "glc": ["y1", "x1"]}

HEADER = """\
# {component} history fields. Seeded from reference/lens2output200129.csv, then
# maintained by hand. See README.md -> "Add or correct a variable".
#
#   dims    copy verbatim from `ncdump -h`, in order, including `time`.
#   streams <stream>: <tier>  -- which LENS2 preset the variable belongs to.
#
# A variable may appear twice with DIFFERENT dims (CTSM writes some fields
# gridded in one stream and as subgrid vectors in another). Keep them separate.
"""


class Flow(dict):
    pass


class FlowSeq(list):
    pass


yaml.add_representer(Flow, lambda d, v: d.represent_mapping(
    "tag:yaml.org,2002:map", v, flow_style=True))
yaml.add_representer(FlowSeq, lambda d, v: d.represent_sequence(
    "tag:yaml.org,2002:seq", v, flow_style=True))


def read_rows():
    """Yield row dicts. Raises on any row that isn't exactly 8 fields -- a
    silently dropped variable would understate every estimate using it."""
    for lineno, line in enumerate(CSV_PATH.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        row = next(csv.reader([line]))
        if len(row) != 8:
            raise ValueError(f"{CSV_PATH.name}:{lineno}: got {len(row)} fields, "
                             f"want 8: {line!r}")
        yield dict(zip(FIELDS, row))


def main():
    records = OrderedDict()
    for r in read_rows():
        key = (r["component"], r["name"], tuple(r["dims"].split()))
        rec = records.setdefault(key, {"streams": {}, "long_name": r["long_name"],
                                       "units": r["units"]})
        # 9 atm fields are listed under both tiers. Tiers are cumulative -- a
        # MOAR member writes everything a std member does, plus extras -- so
        # "both" means "in the base set".
        prior = rec["streams"].get(r["stream"])
        rec["streams"][r["stream"]] = "std" if "std" in (prior, r["tier"]) else r["tier"]

    for component, horiz in HORIZ_DIMS.items():
        rows = sorted(((n, d, rec) for (c, n, d), rec in records.items() if c == component),
                      key=lambda t: (t[0], t[1]))
        body = yaml.dump({"variables": [
            {"name": n, "dims": FlowSeq(d), "streams": Flow(sorted(rec["streams"].items())),
             "long_name": rec["long_name"], "units": rec["units"]}
            for n, d, rec in rows]},
            sort_keys=False, width=1000, allow_unicode=True)
        # The CSV has no datatype column; CESM history fields are float32.
        (ROOT / "data" / f"{component}.yaml").write_text(
            HEADER.format(component=component)
            + f"\nhoriz_dims: [{', '.join(horiz)}]\ndtype_bytes: 4\n\n" + body)
        print(f"data/{component}.yaml: {len(rows)} variables")


if __name__ == "__main__":
    main()
