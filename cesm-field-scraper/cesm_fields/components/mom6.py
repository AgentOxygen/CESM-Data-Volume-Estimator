"""ocn: MOM6. `register_diag_field`, `register_static_field`, `register_scalar_field`.

    CS%id_temp = register_diag_field('ocean_model', 'temp', diag%axesTL, Time,
                 'Potential Temperature', 'degC', cmor_field_name='thetao')

The axes argument is a handle; `AXES` is the handle -> (staggering, dims)
table built by the `define_axes_group` calls in
src/framework/MOM_diag_mediator.F90 (ncdump order, z only; Fortran case-blind).
Handles passed in from a caller don't resolve and get `dims_expr`.

`cmor_field_name=` registers a second, separately requestable name; it
becomes its own record with `alias_of`, inheriting units and long name
unless `cmor_units`/`cmor_long_name` are given.
"""

import re

from .. import fortran
from ..common import calls, records

COMPONENT, MODEL, REPO_PATH = "ocn", "MOM6", "components/mom"

HORIZONTAL = ("MOM6 staggering: T [yh, xh], Cu [yh, xq], Cv [yq, xh], B [yq, xq]; "
              "null means no horizontal dims.")

AXES = {
    "axestl": ("T", ["zl"]), "axesbl": ("B", ["zl"]), "axescul": ("Cu", ["zl"]), "axescvl": ("Cv", ["zl"]),
    "axesti": ("T", ["zi"]), "axesbi": ("B", ["zi"]), "axescui": ("Cu", ["zi"]), "axescvi": ("Cv", ["zi"]),
    "axest1": ("T", []), "axesb1": ("B", []), "axescu1": ("Cu", []), "axescv1": ("Cv", []),
    "axeszl": (None, ["zl"]), "axeszi": (None, ["zi"]), "axesnull": (None, []),
}

# routine -> (axes position, long_name position, units position, has time)
SIGNATURES = {
    "register_diag_field": (2, 4, 5, True),
    "register_static_field": (2, 3, 4, False),
    "register_scalar_field": (None, 4, 5, True),
}


def scrape(root):
    for rel, routine, call, env in calls(root, "MOM6", list(SIGNATURES)):
        ax, ln, un, time = SIGNATURES[routine]
        if ax is None:
            horizontal, dims = None, []
        else:
            handle = re.sub(r".*%", "", fortran.arg(call, ax, "axes_in") or fortran.arg(call, ax, "axes")).strip()
            horizontal, dims = AXES.get(handle.lower(), (None, fortran.Expr(handle)))
        native = fortran.name(call.args[1])
        units = fortran.literal(fortran.arg(call, un, "units"))
        long_name = fortran.literal(fortran.arg(call, ln, "long_name"))
        common = dict(dims=dims, horizontal=horizontal, time=time, env=env,
                      registrar=routine, source=f"{rel}:{call.line}")
        yield from records(name=native, units=units, long_name=long_name, **common)
        if "cmor_field_name" in call.kw:
            yield from records(
                name=fortran.name(call.kw["cmor_field_name"]), alias_of=native,
                units=fortran.literal(call.kw.get("cmor_units")) or units,
                long_name=fortran.literal(call.kw.get("cmor_long_name")) or long_name, **common)
