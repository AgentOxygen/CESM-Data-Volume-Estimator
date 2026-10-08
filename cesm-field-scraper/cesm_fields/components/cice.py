"""ice: CICE. `define_hist_field`.

    call define_hist_field(n_aice, "aice", "1", tstr2D, tcstr,
         "ice area (aggregate)", "none", c1, c0, ns1, f_aice)

The 4th argument is a shape constant from
cicedyn/analysis/ice_history_shared.F90 (`tstr4Di = 'TLON TLAT VGRDi NCAT'`).
`SHAPES` maps each to the netCDF dims infrastructure/io/io_pio2/
ice_history_write.F90 writes, in ncdump order without time and [nj, ni].

At runtime CICE appends `_<freq letter>` for every history stream after
the first (`aice_d`); `name` is the base name.
"""

from .. import fortran
from ..common import calls, records

COMPONENT, MODEL, REPO_PATH = "ice", "CICE", "components/cice"

HORIZONTAL = "CICE grid point (T cell centre; U, N, E staggered). All are written on [nj, ni]."

SHAPES = {
    "tstr2d": ("T", []), "ustr2d": ("U", []), "nstr2d": ("N", []), "estr2d": ("E", []),
    "tstr3dc": ("T", ["nc"]), "tstr3da": ("T", ["nkaer"]), "tstr3db": ("T", ["nkbio"]),
    "tstr3df": ("T", ["nf"]), "tstr4di": ("T", ["nc", "nkice"]),
    "tstr4ds": ("T", ["nc", "nksnow"]), "tstr4df": ("T", ["nc", "nf"]),
}


def scrape(root):
    for rel, _, call, env in calls(root, "src", ["define_hist_field"]):
        shape = call.args[3].strip().lower()
        horizontal, dims = SHAPES.get(shape, (None, fortran.Expr(shape)))
        yield from records(
            name=fortran.name(call.args[1]), dims=dims, horizontal=horizontal, env=env,
            units=fortran.literal(call.args[2]), long_name=fortran.literal(call.args[5]),
            registrar="define_hist_field", source=f"{rel}:{call.line}")
