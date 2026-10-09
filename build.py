"""data/cmip7_request.yaml -> docs/data.json, the file the web page loads.

    python build.py        # regenerate docs/data.json

All judgement about the mapping (status, component, fallbacks) was made by
tools/import_cmip7.py and is already in the YAML. The one thing computed here is
the volume side: each mapped variable that exists in the (CESM2-era) catalogue
is sized on every grid x vertical configuration, using estimator.py's tested
arithmetic, so the page only multiplies by samples per year and adds.

Volumes are RAW UNCOMPRESSED bytes of one variable in one stream. A line the
catalogue cannot size (no entry, or an unmodeled frequency) is left out of
`sizes` / `per_year` and shown as unpriced -- never guessed.
"""

import json
import sys
from pathlib import Path

import yaml

import estimator

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "cmip7_request.yaml"
BUNDLE = ROOT / "docs" / "data.json"

COMPONENTS = ["atm", "lnd", "ocn", "ice", "rof", "glc"]
STATUSES = ["verified", "spreadsheet-only", "cesm2"]       # + "missing" (no tokens)
COMPONENT_SOURCES = ["log", "catalogue", "realm-fallback"]
# Components whose namelists take a `NAME:FLAG` averaging suffix (CAM `fincl`,
# CTSM `hist_fincl`). CICE, MOM6, MOSART and CISM choose time methods elsewhere.
COLON_COMPONENTS = ["atm", "lnd"]


# CMIP7 frequency -> samples per simulated year (365-day calendar). `fx` is a
# one-off file and `subhr` depends on a model timestep this tool does not know,
# so neither has a per-year volume; the page shows those lines as unpriced.
PER_YEAR = {"yr": 1, "dec": 0.1, "mon": 12, "day": 365,
            "6hr": 1460, "3hr": 2920, "1hr": 8760}
DEFAULT_CONFIG = "ne30pg3_g17|cam7-lt"        # CESM3's defaults


def pick_variant(variants, horiz_dims):
    """A catalogue name can have two records (CTSM gridded vs. subgrid vector).
    A CMIP7 request wants the gridded field, so prefer the record that carries
    the component's horizontal dims; otherwise the first."""
    for v in variants:
        if all(d in v["dims"] for d in horiz_dims):
            return v
    return variants[0]


def build_sizes(components_and_names):
    """({"comp|NAME": {b, d, w, a?}}, configs): bytes per time sample on each
    configuration (null = does not exist there) for every requested field the
    catalogue has."""
    catalogue, _ = estimator.load_catalogue()
    grids_doc = estimator.load("grids.yaml")
    verticals = estimator.load("vertical.yaml")
    approx_dims = set(grids_doc.get("approximate_dims", []))
    configs, resolved = [], []
    for gname, grid in grids_doc["grids"].items():
        for vname, vert in verticals.items():
            key = f"{gname}|{vname}"
            configs.append({"key": key, "label": f"{grid['label']}  -  {vert['label']}"})
            resolved.append((key, estimator.resolve_sizes(grid, vert)))
    sizes = {}
    for component, name in sorted(components_and_names):
        horiz_dims, variables = catalogue[component]
        variants = [v for v in variables if v["name"] == name]
        if not variants:
            continue
        var = pick_variant(variants, horiz_dims)
        by_config = []
        for key, by_component in resolved:
            horiz, dim_sizes = by_component[component]
            by_config.append(estimator.bytes_per_sample(
                var, horiz_dims, horiz, dim_sizes, f"config {key}, {component}"))
        entry = {"b": by_config, "d": [d for d in var["dims"] if d != "time"],
                 "w": var["dtype_bytes"]}
        if approx_dims.intersection(var["dims"]):
            entry["a"] = 1             # size depends on the surface dataset
        sizes[f"{component}|{name}"] = entry
    return sizes, configs


def build_bundle():
    doc = yaml.safe_load(SOURCE.read_text())
    wanted = {(t["component"], t["name"]) for r in doc["requests"] for t in r["tokens"]
              if t["component"]}
    sizes, configs = build_sizes(wanted)
    requests = [{
        "n": r["name"], "u": r["uid"], "l": r["source_line"], "raw": r["raw_cesm_name"],
        "realm": r["realm"], "f": r["frequency"], "p": r["priority"],
        "g": r["groups"], "fc": r["fallback_component"],
        "tm": r["time_method"], "mn": r["method_note"],
        "t": [{"n": t["name"], "st": t["status"], "c": t["component"],
               "cs": t["component_source"], "log": t["log_components"],
               "cat": t["catalogue_state"], "mm": t["realm_mismatch"],
               "m": t["method"], "ms": t["method_source"]}
              for t in r["tokens"]],
    } for r in doc["requests"]]
    return {"components": COMPONENTS, "statuses": STATUSES,
            "component_sources": COMPONENT_SOURCES,
            "colon_components": COLON_COMPONENTS,
            "configs": configs,
            "default_config": [c["key"] for c in configs].index(DEFAULT_CONFIG),
            "per_year": PER_YEAR, "sizes": sizes,
            "experiments": doc["experiments"], "requests": requests}


def dump_bundle(bundle):
    """One request / one experiment per line, so a regenerated bundle diffs
    readably."""
    j = lambda o: json.dumps(o, separators=(",", ":"))
    head = {k: v for k, v in bundle.items()
            if k not in ("experiments", "requests", "sizes")}
    lines = [j(head)[:-1] + ',', '"sizes":{',
             ",\n".join(f"{j(k)}:{j(v)}" for k, v in bundle["sizes"].items()),
             '},', '"experiments":{']
    lines.append(",\n".join(f"{j(k)}:{j(v)}" for k, v in bundle["experiments"].items()))
    lines += ['},', '"requests":[', ",\n".join(j(r) for r in bundle["requests"]), "]}"]
    return "\n".join(lines) + "\n"


def main():
    if not SOURCE.exists():
        sys.exit(f"{SOURCE.relative_to(ROOT)} is missing -- it is committed; "
                 f"restore it or run `make import-cmip7`.")
    bundle = build_bundle()
    BUNDLE.parent.mkdir(exist_ok=True)
    BUNDLE.write_text(dump_bundle(bundle))
    print(f"{BUNDLE.relative_to(ROOT)}: {len(bundle['requests'])} requests, "
          f"{len(bundle['experiments'])} experiments, "
          f"{BUNDLE.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
