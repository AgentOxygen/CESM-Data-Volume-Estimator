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

MARBL biogeochemistry diagnostics (DIC, ALK, FG_CO2, ...) are not registered in
MOM6 Fortran. MARBL publishes them in externals/MARBL/defaults/diagnostics_latest.yaml
(name, longname, units, vertical_grid, frequency/operator lists, dependencies,
diag_mode). They become records here with `registrar: marbl_yaml`, the
yaml line as `source`, and the dependencies/diag_mode kept as `marbl_*` for
the configuration to evaluate.
"""

import re
from pathlib import Path

import yaml

from .. import fortran
from ..common import calls, read, records

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


MARBL_YAML = "externals/MARBL/defaults/diagnostics_latest.yaml"
MARBL_VERTICAL = {"none": [], "layer_avg": ["zl"]}       # MARBL's vertical_grid -> dims; anything else fails loudly
MARBL_OPERATOR = {"average": "A", "instantaneous": "I", "minimum": "M", "maximum": "X", "sum": "SUM"}


MARBL_SETTINGS = "externals/MARBL/defaults/settings_latest+4p2z.yaml"   # MARBL_CONFIG for MOM6%...MARBL compsets
FLUX_REF_DEPTH = "100m"                          # particulate_flux_ref_depth default (100.0 m) in the settings file
_FLAGS = {"Nfixer": "autotroph_Nfixer", "silicifier": "autotroph_silicifier", "is_carbon_limited": "autotroph_is_carbon_limited"}


def marbl_pfts(text):
    """{kind: {sname: {lname, flags}}} for autotrophs and zooplankton, read from the
    `((autotroph_sname)) == "x" : value` conditionals in the settings file's default_value blocks."""
    a0 = text.index("_array_shape : autotroph_cnt")
    z0 = text.index("zooplankton_settings :", a0)
    out = {}
    for kind, tmpl, section in [("autotroph", "autotroph_sname", text[a0:z0]), ("zooplankton", "zooplankton_sname", text[z0:])]:
        def prop(name):
            m = re.search(rf"\n {{9}}{name} :(.*?)(?=\n {{9}}\w+ ?:|\Z)", section, re.S)
            return dict(re.findall(rf'\(\({tmpl}\)\) == "(\w+)" : (.+)', m.group(1))) if m else {}
        snames, lnames = prop("sname"), prop("lname")
        out[kind] = {s: {"lname": lnames[s], "flags": {
            "autotroph_Nfixer": prop("Nfixer").get(s) == ".true.", "autotroph_silicifier": prop("silicifier").get(s) == ".true.",
            "autotroph_is_carbon_limited": prop("is_carbon_limited").get(s) == ".true.",
            "autotroph_calcifier": prop("imp_calcifier").get(s) == ".true." or prop("exp_calcifier").get(s) == ".true."}}
            for s in snames}
    return out


def marbl_expansions(name, deps, pfts):
    """[{template: text}] for a templated diagnostic name: one per autotroph and/or zooplankton it
    names, skipping autotrophs that lack a property the diagnostic depends on."""
    need = [k.strip("() ") for k, v in (deps or {}).items() if k.startswith("((autotroph_") and v is True]
    out = [{"((particulate_flux_ref_depth_str))": FLUX_REF_DEPTH}]
    for kind in ("autotroph", "zooplankton"):
        if f"(({kind}_sname))" not in name:
            continue
        out = [{**sub, f"(({kind}_sname))": s, f"(({kind}_lname))": d["lname"]}
               for sub in out for s, d in pfts[kind].items()
               if kind != "autotroph" or all(d["flags"].get(n) for n in need)]
    return out


def fill(text, subs):
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def scrape_marbl(root):
    path = root / MARBL_YAML
    if not path.exists():
        return
    text = read(path)
    pfts = marbl_pfts(read(root / MARBL_SETTINGS))
    lines = {m.group(1): n for n, line in enumerate(text.splitlines(), 1) if (m := re.match(r"(\S+) :", line))}
    for tmpl, d in yaml.safe_load(text).items():
        ops = d.get("operator") or []
        common = dict(dims=MARBL_VERTICAL[d["vertical_grid"]], horizontal="T", env=None, units=d.get("units"),
                      avgflag=MARBL_OPERATOR.get(ops[0]) if ops else None, registrar="marbl_yaml",
                      source=f"{MARBL_YAML}:{lines[tmpl]}", marbl_frequency=d.get("frequency"), marbl_operator=ops,
                      marbl_diag_mode=d.get("diag_mode"), marbl_dependencies=d.get("dependencies"))
        if "((" not in tmpl:
            yield from records(name=tmpl, long_name=d.get("longname"), **common)
            continue
        subs = marbl_expansions(tmpl, d.get("dependencies"), pfts)
        for sub in subs:
            if "((" not in (name := fill(tmpl, sub)):
                yield from records(name=name, name_expr=tmpl, long_name=fill(d.get("longname") or "", sub), **common)
        if not subs or "((" in fill(tmpl, subs[0]):                  # tracer-templated: pattern only
            yield from records(name=fortran.Expr(tmpl), patterns=[re.sub(r"\(\(\w+\)\)", "*", tmpl)],
                               long_name=d.get("longname"), **common)


# MARBL switches that gate tracers, at their defaults in MARBL_SETTINGS (ciso_on and abio_dic_on default off).
MARBL_FLAGS = {"base_bio_on": True, "ciso_on": False, "abio_dic_on": False, "lvariable_PtoC": True, "lvariable_NtoC": True}
MOM_MARBL_PY = "cime_config/MARBL_scripts/MOM_MARBL_diagnostics.py"


def marbl_tracers(settings, pfts):
    """Short names of the tracers MARBL provides under MARBL_FLAGS (templated tracers expanded per PFT)."""
    out = []
    for tmpl, d in yaml.safe_load(settings)["_tracer_list"].items():
        deps = {k: v for k, v in (d.get("dependencies") or {}).items()}
        if any(MARBL_FLAGS.get(k) is not (v == ".true.") for k, v in deps.items() if not k.startswith("((")):
            continue
        deps = {k: v for k, v in deps.items() if k.startswith("((")}
        for sub in marbl_expansions(tmpl, deps, pfts):
            out.append(fill(tmpl, sub))
    return sorted(set(out))


def scrape_marbl_mom(root):
    """The diagnostics MOM adds around MARBL (tracer state `DIC`, `Jint_100m_*`, `STF_*`, forcing, ...), by running
    CESM's own generator, MOM_MARBL_diagnostics.py, for the tracers/PFTs above. Names only: that file carries no units."""
    import importlib.util
    import tempfile
    path = root / MOM_MARBL_PY
    if not path.exists():
        return
    pfts = marbl_pfts(read(root / MARBL_SETTINGS))
    tracers = marbl_tracers(read(root / MARBL_SETTINGS), pfts)
    spec = importlib.util.spec_from_file_location("mom_marbl_diagnostics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "diags"
        mod.write_MARBL_diagnostics_file(
            tracers, list(pfts["autotroph"]), list(pfts["zooplankton"]),
            [s for s, d in pfts["autotroph"].items() if d["flags"]["autotroph_calcifier"]],
            False, str(out), 0, "full")
        lines = [l.strip() for l in out.read_text().splitlines() if l.strip() and not l.startswith("#")]
    for line in lines:
        name, _, rest = line.partition(":")
        freq_ops = [x.strip() for x in rest.split(",")]
        yield from records(
            name=name.strip(), dims=[], dims_expr=None, horizontal=None, env=None, registrar="marbl_mom_py",
            source=f"{MOM_MARBL_PY}:1", marbl_frequency=[f.partition("_")[0] for f in freq_ops],
            marbl_operator=[f.partition("_")[2] for f in freq_ops])


def scrape(root):
    yield from scrape_marbl(root)
    yield from scrape_marbl_mom(root)
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
