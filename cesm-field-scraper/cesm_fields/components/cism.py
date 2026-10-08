"""glc: CISM. The declarative `lib*/*_vars.def` files, no Fortran.

    [thk]
    dimensions:    time, y1, x1
    units:         meter
    long_name:     ice thickness

`dimensions` is already ncdump order. Sections with `axis:` are
coordinates and are skipped, as is `[VARSET]`.
"""

import configparser

from ..common import read, records

COMPONENT, MODEL, REPO_PATH = "glc", "CISM", "components/cism"

HORIZONTAL = "CISM grid: x1y1 is the ice grid [y1, x1], x0y0 the staggered velocity grid [y0, x0]."


def scrape(root):
    for path in sorted(root.glob("source_cism/lib*/*_vars.def")):
        defs = configparser.ConfigParser(interpolation=None)
        defs.read_string(read(path))
        rel = path.relative_to(root).as_posix()
        for name, keys in defs.items():
            if "dimensions" not in keys or "axis" in keys:
                continue
            dims = [d.strip() for d in keys["dimensions"].split(",")]
            horizontal = "x1y1" if "x1" in dims else "x0y0" if "x0" in dims else None
            yield from records(
                name=name, dims=[d for d in dims if d not in ("time", "x1", "y1", "x0", "y0")],
                horizontal=horizontal, time="time" in dims,
                units=keys.get("units"), long_name=keys.get("long_name"),
                registrar="vars.def", source=rel)
