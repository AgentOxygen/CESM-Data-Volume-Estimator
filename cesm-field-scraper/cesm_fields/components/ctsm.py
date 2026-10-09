"""lnd: CTSM. `hist_addfld1d`, `hist_addfld2d`, `hist_addfld_decomp`.

    call hist_addfld2d(fname='SMP', units='mm', type2d='levgrnd',
         avgflag='A', long_name='soil matric potential', ptr_col=...)

Every call site uses keywords. The `ptr_*` argument gives the subgrid
level, which is `horizontal` here: the horizontal dim of vector output
(`hist_dov2xy = .false.`). Gridded output averages up to the land grid.
`dims` is `type2d` verbatim. `default='inactive'` means not on a tape
unless a namelist asks.

FATES (`use_fates`) registers through `set_history_var(vname=, units=, long=,
use_default=, avgflag=, vtype=, ...)` in FatesHistoryInterfaceMod.F90; every
name is a literal. `vtype` is a kind constant whose shape is documented by the
comment above its `dim_kinds(index)%Init(...)` call; that comment becomes
`dims` (FATES sizes those dims from runtime parameter files, so they are
names only), and `horizontal` is `site`.

Two name wrappers are unwrapped:
  this%info%fname('X')                  bulk water: exactly 'X' (tracers add '_<tracer>')
  this%species%hist_fname('X', suffix=S)   ['C13_'|'C14_'] // X // 'C'|'N' // S
"""

import re

from .. import fortran
from ..common import calls, read, records

COMPONENT, MODEL, REPO_PATH = "lnd", "CTSM", "components/clm"

HORIZONTAL = ("CTSM subgrid level (pft, column, landunit, gridcell): the horizontal "
              "dim of vector output. Gridded output (the default) is [lat, lon], "
              "or [lndgrid] on unstructured grids.")

POINTERS = {"ptr_patch": "pft", "ptr_col": "column", "ptr_lunit": "landunit",
            "ptr_gcell": "gridcell", "ptr_lnd": "gridcell"}

_STR = r"""('[^']*'|"[^"]*")"""


FATES = "src/fates/main/FatesHistoryInterfaceMod.F90"


def fates_dims(text):
    """vtype constant name -> dims, from `! site x size-class/pft` above each `Init(site_x_r8, n)`."""
    out = {}
    for m in re.finditer(r"!\s*([^\n]+)\n\s*(?:index = index \+ 1\s*)?call this%dim_kinds\(index\)%Init\((\w+)", text):
        parts = re.split(r"\s+x\s+|/", re.sub(r"^(1d )?[Ss]ite( x )?", "", m.group(1).strip()))
        out[m.group(2).lower()] = [p.strip() for p in parts if p.strip()]
    return out


def scrape_fates(root):
    path = root / FATES
    if not path.exists():
        return
    stmts = list(fortran.statements(read(path)))
    dims = fates_dims(read(path))
    for line, text in stmts:
        for call in fortran.find_calls(line, text, "this%set_history_var"):
            vtype = call.kw["vtype"].lower()
            yield from records(
                name=fortran.name(call.kw["vname"]), dims=dims.get(vtype, fortran.Expr(vtype)), horizontal="site",
                units=fortran.literal(call.kw.get("units")), long_name=fortran.literal(call.kw.get("long")),
                avgflag=fortran.literal(call.kw.get("avgflag")), default=fortran.literal(call.kw.get("use_default")),
                registrar="set_history_var", source=f"{FATES}:{call.line}")


def scrape(root):
    yield from scrape_fates(root)
    for rel, routine, call, env in calls(root, "src", ["hist_addfld1d", "hist_addfld2d", "hist_addfld_decomp"]):
        fname = " ".join(call.kw["fname"].split())
        variants, patterns = None, None
        if m := re.match(rf"^[\w%]+%fname\s*\(\s*{_STR}\s*\)$", fname):
            name, variants = fortran.name(m.group(1)), "water_tracers"
        elif m := re.match(rf"^[\w%]+%hist_fname\s*\(\s*{_STR}\s*(?:,\s*suffix\s*=\s*{_STR})?\s*\)$", fname):
            name = fortran.Expr(fname)
            patterns = [f"*{fortran.literal(m.group(1))}*{fortran.literal(m.group(2) or '')}"]
        else:
            name = fortran.name(fname)
        long_name = call.kw.get("long_name", "")
        if m := re.match(rf"^[\w%]+%lname\s*\(\s*{_STR}\s*\)$", long_name.strip()):
            long_name = m.group(1)
        level = fortran.literal(call.kw.get("type2d"))
        yield from records(
            name=name, patterns=patterns, env=env,
            dims=[] if level is None else [level] if isinstance(level, str) else level,
            horizontal=next(v for k, v in POINTERS.items() if k in call.kw),
            units=fortran.literal(call.kw.get("units")), long_name=fortran.literal(long_name),
            avgflag=fortran.literal(call.kw.get("avgflag")),
            default=fortran.literal(call.kw.get("default")), name_variants=variants,
            registrar=routine, source=f"{rel}:{call.line}")
