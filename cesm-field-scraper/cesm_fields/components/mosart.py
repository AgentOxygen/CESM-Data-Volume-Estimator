"""rof: MOSART. `mosart_hist_addfld`, all 16 in src/riverroute/mosart_histflds.F90.

Most names are built from the runtime tracer list (`ctl%tracer_names`),
so they come out as `name_patterns`.
"""

from .. import fortran
from ..common import calls, records

COMPONENT, MODEL, REPO_PATH = "rof", "MOSART", "components/mosart"

HORIZONTAL = "The MOSART river grid: [lat, lon]."


def scrape(root):
    for rel, _, call, env in calls(root, "src", ["mosart_hist_addfld"]):
        yield from records(
            name=fortran.name(call.kw["fname"]), dims=[], horizontal="rof", env=env,
            units=fortran.literal(call.kw.get("units")), long_name=fortran.literal(call.kw.get("long_name")),
            avgflag=fortran.literal(call.kw.get("avgflag")), default=fortran.literal(call.kw.get("default")),
            registrar="mosart_hist_addfld", source=f"{rel}:{call.line}")
