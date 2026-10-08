"""atm: CAM. `addfld` (legacy physics) and `history_add_field` (CCPP schemes).

    call addfld('T', (/ 'lev' /), 'A', 'K', 'Temperature', gridname='physgrid')
    call history_add_field('HR', 'Heating rate ...', 'lev', 'avg', 'K s-1')

The dims argument names only non-horizontal dims; `horizontal` is the
`gridname` (default `physgrid`, per addfld_nd in src/control/cam_history.F90).

Constituent fields (`Q`, `O3`, `SFso4_a1`, `so4_a1_SRF`, ...) are registered
in loops over `cnst_name(m)`. Those loops are expanded with the constituents
a CAM7 build registers: `Q` (physics/cam/physpkg.F90), the PUMAS
`cnst_names` array, and the species of chemistry package `CHEM`, which
`bld/configure` defaults to for `-phys cam7`. A loop over a subset of
constituents still expands to all of them, so an expanded record can
over-claim; its `name_expr` says it was expanded.
"""

import re

from .. import fortran
from ..common import calls, read, records

COMPONENT, MODEL, REPO_PATH = "atm", "CAM", "components/cam"

HORIZONTAL = ("CAM grid name. physgrid is [ncol] on spectral-element grids and "
              "[lat, lon] on finite-volume; other names (GLL, fv_centers_zonal, ...) "
              "are CAM's other registered grids.")

CHEM = "ghg_mam4"
CONSTITUENT_ARRAYS = [
    ("src/physics/cam7/micro_pumas_cam.F90", "cnst_names"),
    (f"src/chemistry/pp_{CHEM}/mo_sim_dat.F90", "solsym"),
]


def known_names(root):
    """Variable -> the names it can hold, for expanding constituent loops."""
    cnst = ["Q"]
    for rel, var in CONSTITUENT_ARRAYS:
        for _, text in fortran.statements(read(root / rel)):
            if m := re.search(rf"\b{var}\s*(\([^=]*\))?\s*=\s*(\(/.*/\))$", text, re.I | re.S):
                cnst += fortran.literal_list(m.group(2))
    known = {"cnst_name": cnst, "solsym": cnst}
    # constituents.F90 builds public per-constituent name arrays used all over
    # CAM (`sflxnam(m) = 'SF'//cnst_name(m)`, ptendnam, tottnam, ...).
    env = fortran.assignments(fortran.statements(read(root / "src/physics/cam/constituents.F90")))
    for var, rhs in env.items():
        if any("cnst_name" in r for r in rhs):
            known[var] = sorted({n for r in rhs for n in fortran.expand(r, {}, known)})
    return known


def _dims(text):
    if text.strip().lower() == "horiz_only":
        return []
    one = fortran.literal(text)
    return [one.strip()] if isinstance(one, str) else fortran.literal_list(text)


def scrape(root):
    known = known_names(root)
    for rel, routine, call, env in calls(root, "src", ["addfld", "history_add_field"]):
        common = dict(env=env, known=known, registrar=routine, source=f"{rel}:{call.line}")
        if routine == "addfld":
            grid = call.kw.get("gridname")
            yield from records(
                name=fortran.name(call.args[0]), dims=_dims(call.args[1]),
                horizontal="physgrid" if grid is None else fortran.literal(grid),
                units=fortran.literal(call.args[3]), long_name=fortran.literal(fortran.arg(call, 4, "long_name")),
                avgflag=fortran.literal(call.args[2]), **common)
        else:
            yield from records(
                name=fortran.name(call.args[0]), dims=_dims(call.args[2]), horizontal="physgrid",
                units=fortran.literal(call.args[4]), long_name=fortran.literal(call.args[1]),
                avgflag=fortran.literal(call.args[3]), **common)
