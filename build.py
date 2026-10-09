"""data/cmip7_request.yaml -> docs/data.json, the file the web page loads.

    python build.py        # regenerate docs/data.json

All judgement about the mapping (status, component, fallbacks, dimensions) was
made by tools/import_cmip7.py and is already in the YAML. The one thing computed
here is the volume side: each mapped variable whose CESM3 source record gave its
dimensions is sized on every grid x vertical configuration, so the page only
multiplies by samples per year and adds.

Volumes are RAW UNCOMPRESSED bytes of one variable in one stream. A line that
cannot be sized (no source record, an unresolved or unknown dimension, an
unmodeled frequency) is left out of `sizes` / `per_year` and shown as
unpriced -- never guessed.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "cmip7_request.yaml"
BUNDLE = ROOT / "docs" / "data.json"

COMPONENTS = ["atm", "lnd", "ocn", "ice", "rof", "glc"]
STATUSES = ["verified", "source", "spreadsheet-only"]       # + "missing" (no tokens)
COMPONENT_SOURCES = ["log", "source", "realm-fallback"]
# Components whose namelists take a `NAME:FLAG` averaging suffix (CAM `fincl`,
# CTSM `hist_fincl`). CICE, MOM6, MOSART and CISM choose time methods elsewhere.
COLON_COMPONENTS = ["atm", "lnd"]


# CMIP7 frequency -> samples per simulated year (365-day calendar). `fx` is a
# one-off file and `subhr` depends on a model timestep this tool does not know,
# so neither has a per-year volume; the page shows those lines as unpriced.
PER_YEAR = {"yr": 1, "dec": 0.1, "mon": 12, "day": 365,
            "6hr": 1460, "3hr": 2920, "1hr": 8760}
DEFAULT_CONFIG = "ne30pg3_t233|cam7-mt"        # the BHISTE_MTt4s baseline
BYTES = 4                                       # history files are written as 4-byte floats (ndens = 2)

# A source record's `horizontal` token -> whether it is a horizontal grid we can count cells for.
# CAM's other registered grids (GLL, zonal-mean) have no cell count here. CTSM subgrid levels
# (pft, column, ...) are priced as the gridded output, which is what the namelist export writes.
UNPRICED_HORIZONTAL = {"atm": lambda h: h != "physgrid"}


def read(name):
    return yaml.safe_load((ROOT / "data" / name).read_text())


def bytes_per_sample(component, dims, horizontal, grid, vertical):
    """(bytes, why): bytes for one time sample on one grid x vertical, or (None, reason)."""
    spec = grid.get(component)
    if not spec:
        return None, f"{component} does not run on this grid"
    if dims is None:
        return None, "its dimensions are not resolved in the source"
    if component in UNPRICED_HORIZONTAL and UNPRICED_HORIZONTAL[component](horizontal):
        return None, f"it is on the {horizontal} grid, which has no cell count here"
    sizes = {**vertical["sizes"], **spec.get("sizes", {})}
    cells = 1 if horizontal is None and component == "ocn" else spec["cells"]
    total = BYTES * cells
    for dim in dims:
        if sizes.get(dim) is None:
            return None, f"dimension {dim!r} has no size in data/grids.yaml"
        total *= sizes[dim]
    return total, None


def build_sizes(tokens):
    """({"comp|NAME": {b, d, x?}}, configs): bytes per time sample on each configuration (null = cannot be
    sized there) for every requested field whose source record resolved its dimensions."""
    grids, verticals = read("grids.yaml")["grids"], read("vertical.yaml")
    configs = [{"key": f"{g}|{v}", "label": f"{gs['label']}  -  {vs['label']}", "grid": g, "vertical": v}
               for g, gs in grids.items() for v, vs in verticals.items()]
    sizes = {}
    for component, name, dims, horizontal in sorted(tokens, key=lambda t: t[:2]):
        key = f"{component}|{name}"
        if key in sizes or dims is None and horizontal is None:
            continue
        by_config, why = [], set()
        for c in configs:
            b, w = bytes_per_sample(component, dims, horizontal, grids[c["grid"]], verticals[c["vertical"]])
            by_config.append(b)
            if w:
                why.add(w)
        if any(b is not None for b in by_config):
            sizes[key] = {"b": by_config, "d": list(dims or [])}
        elif why:
            sizes[key] = {"b": by_config, "d": list(dims or []), "x": sorted(why)[0]}
    return sizes, [{"key": c["key"], "label": c["label"]} for c in configs]


def build_bundle():
    doc = yaml.safe_load(SOURCE.read_text())
    wanted = {(t["component"], t["name"], tuple(t["dims"]) if t["dims"] is not None else None, t["horizontal"])
              for r in doc["requests"] for t in r["tokens"] if t["component"] and (t["dims"] is not None or t["horizontal"])}
    sizes, configs = build_sizes(wanted)
    requests = [{
        "n": r["name"], "u": r["uid"], "l": r["source_line"], "raw": r["raw_cesm_name"],
        "realm": r["realm"], "f": r["frequency"], "p": r["priority"],
        "g": r["groups"], "fc": r["fallback_component"],
        "tm": r["time_method"], "mn": r["method_note"],
        "t": [{"n": t["name"], "st": t["status"], "c": t["component"],
               "cs": t["component_source"], "log": t["log_components"],
               "mm": t["realm_mismatch"],
               "m": t["method"], "ms": t["method_source"],
               "sc": t["source_certainty"], "ref": t["source_ref"], "al": t["alias_of"]}
              for t in r["tokens"]],
    } for r in doc["requests"]]
    return {"components": COMPONENTS, "statuses": STATUSES,
            "component_sources": COMPONENT_SOURCES,
            "source_configuration": doc.get("source_configuration"),
            "colon_components": COLON_COMPONENTS,
            "configs": configs,
            "default_config": [c["key"] for c in configs].index(DEFAULT_CONFIG),
            "per_year": PER_YEAR, "sizes": sizes,
            "mom_fields": yaml.safe_load((ROOT / "data" / "mom_fields.yaml").read_text()),
            "cice_fields": yaml.safe_load((ROOT / "data" / "cice_fvars.yaml").read_text()),
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
