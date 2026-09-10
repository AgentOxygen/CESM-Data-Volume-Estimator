"""Load the YAML catalogue, resolve every dimension, and build docs/data.json.

This module holds all the judgement. The frontend does one multiplication and a
sum, so there is nothing in JavaScript that can drift away from what is tested
here.

    python estimator.py build     # regenerate docs/data.json

Volumes are RAW UNCOMPRESSED bytes -- see README.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BUNDLE = ROOT / "docs" / "data.json"

COMPONENTS = ("atm", "lnd", "ocn", "ice", "rof", "glc")
VAR_KEYS = {"name", "dims", "streams", "long_name", "units", "dtype_bytes"}
FILE_KEYS = {"horiz_dims", "dtype_bytes", "variables"}


class DataError(Exception):
    """A problem in data/*.yaml. Always names the file, variable and dimension."""


def load(name):
    return yaml.safe_load((DATA / name).read_text())


def replace_subsequence(seq, old, new):
    """Replace the first contiguous run of `old` in `seq` with `new`.

    This is how [time, lev, lat, lon] becomes [time, lev, ncol] on a spectral
    element grid. Variables that don't carry the component's horizontal dims --
    CTSM's [time, pft], or the zonal-mean [time, ilev, lat, zlon] -- contain no
    match and pass through untouched, which is exactly what we want.
    """
    n = len(old)
    for i in range(len(seq) - n + 1):
        if seq[i:i + n] == old:
            return seq[:i] + list(new) + seq[i + n:]
    return list(seq)


def load_catalogue():
    """Return {component: (horiz_dims, [variable, ...])}, validating as we go."""
    streams = load("streams.yaml")
    catalogue = {}
    for component in COMPONENTS:
        path = f"{component}.yaml"
        doc = load(path)
        unknown = set(doc) - FILE_KEYS
        if unknown:
            raise DataError(f"{path}: unknown top-level key(s) {sorted(unknown)}")
        default_bytes = doc.get("dtype_bytes", 4)
        horiz_dims = doc["horiz_dims"]
        seen = {}
        variables = []
        for var in doc["variables"]:
            unknown = set(var) - VAR_KEYS
            if unknown:
                raise DataError(
                    f"{path}: {var.get('name', '?')}: unknown key(s) "
                    f"{sorted(unknown)}. Allowed: {sorted(VAR_KEYS)}")
            key = (var["name"], tuple(var["dims"]))
            if key in seen:
                raise DataError(
                    f"{path}: {var['name']} appears twice with identical dims "
                    f"{list(var['dims'])}. Merge the two records' streams.")
            seen[key] = True
            for stream in var["streams"]:
                if stream not in streams:
                    raise DataError(
                        f"{path}: {var['name']}: stream {stream!r} is not in "
                        f"streams.yaml (have {sorted(streams)})")
            variables.append({
                "name": var["name"],
                "dims": list(var["dims"]),
                "streams": var["streams"],
                "long_name": var.get("long_name", ""),
                "units": var.get("units", ""),
                "dtype_bytes": var.get("dtype_bytes", default_bytes),
            })
        catalogue[component] = (horiz_dims, variables)
    return catalogue, streams


def resolve_sizes(grid, vertical):
    """Flatten one grid x vertical config into {component: (horiz, sizes)}."""
    out = {}
    for component in COMPONENTS:
        spec = grid[component]
        # Vertical sizes (lev/ilev) are merged into every component; a grid's
        # own sizes win. Only CAM fields use them in practice.
        sizes = {**vertical["sizes"], **spec["sizes"]}
        out[component] = (spec.get("horiz"), sizes)
    return out


def bytes_per_sample(var, horiz_dims, horiz, sizes, where):
    """Bytes for one time sample, or None if the variable can't exist here.

    A dimension present but set to null means "does not exist on this grid" ->
    the variable is excluded. A dimension missing entirely is a data error.
    """
    dims = replace_subsequence(var["dims"], horiz_dims, horiz) if horiz else var["dims"]
    total = var["dtype_bytes"]
    for dim in dims:
        if dim == "time":
            continue
        if dim not in sizes:
            raise DataError(
                f"{where}: {var['name']} needs dimension {dim!r} but it has no "
                f"size there.\n  variable dims: {var['dims']}\n"
                f"  Add {dim!r} to that component's `sizes` in data/grids.yaml "
                f"(or set it to null if it does not exist on that grid).")
        size = sizes[dim]
        if size is None:
            return None
        total *= size
    return total


def build_bundle():
    """Return the full bundle dict. Pure -- writes nothing."""
    catalogue, streams = load_catalogue()
    grids_doc = load("grids.yaml")
    verticals = load("vertical.yaml")
    grids = grids_doc["grids"]
    approx_dims = set(grids_doc.get("approximate_dims", []))

    # Flatten grid x vertical into an ordered list of configurations, resolving
    # each one's dimension sizes exactly once.
    configs, resolved = [], []
    for gname, grid in grids.items():
        for vname, vert in verticals.items():
            configs.append({"key": f"{gname}|{vname}",
                            "label": f"{grid['label']}  -  {vert['label']}"})
            resolved.append((f"{gname}|{vname}", resolve_sizes(grid, vert)))

    variables = []
    for component in COMPONENTS:
        horiz_dims, entries = catalogue[component]
        for var in entries:
            sizes_by_config = []
            for key, by_component in resolved:
                horiz, sizes = by_component[component]
                sizes_by_config.append(bytes_per_sample(
                    var, horiz_dims, horiz, sizes,
                    f"grid {key}, component {component}"))
            if all(b is None for b in sizes_by_config):
                raise DataError(
                    f"data/{component}.yaml: {var['name']} {var['dims']} is "
                    f"excluded on every configuration -- check its dims.")
            entry = {
                "c": component,
                "n": var["name"],
                # Dims are shown in the UI: without them the gridded and
                # subgrid-vector forms of a CTSM variable look identical.
                "d": var["dims"],
                "ln": var["long_name"],
                "u": var["units"],
                "s": var["streams"],
                "b": sizes_by_config,
            }
            if approx_dims.intersection(var["dims"]):
                entry["a"] = 1      # size depends on the surface dataset
            variables.append(entry)

    return {
        "configs": configs,
        "streams": {k: {"per_year": v["samples_per_year"], "label": v["label"]}
                    for k, v in streams.items()},
        "components": list(COMPONENTS),
        "vars": variables,
    }


def dump_bundle(bundle):
    """Serialise with one variable per line, so adding a variable is a
    one-line diff in the committed JSON."""
    j = lambda o: json.dumps(o, separators=(",", ":"), sort_keys=False)
    head = {k: v for k, v in bundle.items() if k != "vars"}
    lines = [f"{j(head)[:-1]},"] if head else ["{"]
    lines.append('"vars":[')
    lines.append(",\n".join(j(v) for v in bundle["vars"]))
    lines.append("]}")
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "build":
        sys.exit(f"usage: python {Path(__file__).name} build")
    bundle = build_bundle()
    BUNDLE.parent.mkdir(exist_ok=True)
    BUNDLE.write_text(dump_bundle(bundle))
    size_kb = BUNDLE.stat().st_size / 1024
    print(f"{BUNDLE.relative_to(ROOT)}: {len(bundle['vars'])} variables, "
          f"{len(bundle['configs'])} configurations, {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
