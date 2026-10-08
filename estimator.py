"""Load and validate the legacy CESM2/LENS2-seeded history-field catalogue.

The CMIP7 tool no longer prices anything from it. It survives only as the
`cesm2` provenance source for tools/import_cmip7.py: "this name exists in the
old catalogue, so a spreadsheet mapping to it is a CESM2 carry-over". The web
bundle is built by build.py.
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
