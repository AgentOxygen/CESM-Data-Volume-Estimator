"""Load and validate the CESM2/LENS2-seeded history-field catalogue, and size
its variables on a grid.

Two jobs: the `cesm2` provenance source for tools/import_cmip7.py ("this name
exists in the old catalogue, so a spreadsheet mapping to it is a CESM2
carry-over"), and the per-variable dimensions build.py prices CMIP7 requests
from. The web bundle itself is built by build.py.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

COMPONENTS = ("atm", "lnd", "ocn", "ice", "rof", "glc")
VAR_KEYS = {"name", "dims", "streams", "long_name", "units", "dtype_bytes", "verified"}
FILE_KEYS = {"horiz_dims", "dtype_bytes", "verified", "variables"}

# A variable's CESM3 provenance, independent of whether it prices correctly
# on any grid. Everything in data/*.yaml was seeded from a CESM2/LENS2 run
# (see README), so "this name exists in the catalogue" is not evidence it
# exists in CESM3 -- see notes/cmip7-request-tool-plan.md. Set file-wide with
# a top-level `verified:` key (default "unknown"), override per-variable.
#   cesm3      confirmed against a real CESM3 history file.
#   cesm2-only confirmed NOT to exist in CESM3 (a different model entirely,
#              e.g. ocn: POP2 vs. MOM6) -- stronger than "unknown".
#   unknown    carried over from LENS2; never checked against CESM3.
VERIFIED_STATES = {"cesm3", "cesm2-only", "unknown"}


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
        default_verified = doc.get("verified", "unknown")
        if default_verified not in VERIFIED_STATES:
            raise DataError(
                f"{path}: verified: {default_verified!r} is not one of "
                f"{sorted(VERIFIED_STATES)}")
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
            verified = var.get("verified", default_verified)
            if verified not in VERIFIED_STATES:
                raise DataError(
                    f"{path}: {var['name']}: verified: {verified!r} is not "
                    f"one of {sorted(VERIFIED_STATES)}")
            variables.append({
                "name": var["name"],
                "dims": list(var["dims"]),
                "streams": var["streams"],
                "long_name": var.get("long_name", ""),
                "units": var.get("units", ""),
                "dtype_bytes": var.get("dtype_bytes", default_bytes),
                "verified": verified,
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
