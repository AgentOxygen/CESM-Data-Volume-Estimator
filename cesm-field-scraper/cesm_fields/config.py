"""Which build/run configuration registers a field.

The source registers more than any one case writes: other dycores, every
chemistry package (each `pp_*` directory carries its own copy of the same 84
registrations), SCAM, debug code, FATES. Each record gets `requires`, a map of
axis -> allowed values, from where in the tree it was found. A record with no
`requires` is registered in every configuration. Conditions inside a file (an
`if (use_cn)` around a call) are not read; see the plan notes.

`active(record, config)` says whether a configuration (axis -> value) registers it.
"""

import re

# (regex on the source path, axis, value) -- first match per axis wins.
RULES = [
    (r"^src/dynamics/se/", "dycore", "se"),
    (r"^src/dynamics/fv/", "dycore", "fv"),
    (r"^src/dynamics/fv3/", "dycore", "fv3"),
    (r"^src/dynamics/mpas/", "dycore", "mpas"),
    (r"^src/chemistry/pp_([A-Za-z0-9_]+)/", "chem", None),          # None: take group 1
    (r"^src/chemistry/(geoschem|carma_aero)/|^src/hemco/", "chem", "geoschem-or-carma"),
    # bld/configure write_filepath: modal_aero for `-chem *_mam*`, carma_aero for trop_strat carma, else bulk_aero.
    (r"^src/chemistry/(modal_aero|bulk_aero)/", "aerosol", None),
    (r"^src/unit_drivers/", "unit_driver", True),                   # offline test drivers, not in a model build
    (r"/nudging\.F90", "optional_physics", "nudging"),
    (r"/subcol_SILHS", "optional_physics", "silhs"),
    (r"^src/physics/cam7/", "physics", "cam7"),
    (r"^src/physics/simple/", "physics", "simple"),
    (r"^src/physics/ali_arms/", "physics", "ali_arms"),
    (r"^src/physics/waccm/", "waccm_phys", True),
    (r"^src/(physics|ionosphere)/waccmx/", "waccmx", True),
    (r"^src/physics/carma/", "carma", True),
    (r"^src/physics/rrtmgp/", "radiation", "rrtmgp"),
    (r"^src/physics/rrtmg/", "radiation", "rrtmg"),
    (r"^src/physics/(cosp2/|cam/cospsimulator)", "cosp", True),
    # Scheme modules that are compiled in every CAM build but only called for one namelist choice
    # (macrop_scheme / shallow_scheme / eddy_scheme; cam7 sets all three to clubb_sgs).
    (r"/rk_stratiform_cam\.F90|/rk_stratiform_diagnostics", "macrop", "rk"),
    (r"/uwshcu\.F90", "shallow", "uw"),
    (r"/hk_conv\.F90", "shallow", "hack"),
    (r"/eddy_diff_cam\.F90", "eddy", "diag_tke"),
    (r"scam|(^|/)iop|history_scam", "scam", True),
    (r"(^|/)[^/]*(debug|snapshot)[^/]*\.F90$", "debug", True),
    (r"^source_(cism|glc)/", "cism", True),                       # absent under DGLC (data ice sheet) compsets
    (r"/fates/", "use_fates", True),
    (r"/MARBL(/|_scripts)|diagnostics_latest\.yaml", "marbl", True),
]


def requires(source):
    """{axis: [values]} for a `path:line` source string."""
    path, out = source.rsplit(":", 1)[0], {}
    for pattern, axis, value in RULES:
        if axis in out or not (m := re.search(pattern, path, re.I)):
            continue
        out[axis] = [m.group(1) if value is None else value]
    return out


def load(path, name):
    """The configuration `name` from configurations.yaml, with `_name` set for `active`."""
    import yaml
    from pathlib import Path
    return {**yaml.safe_load(Path(path).read_text())[name], "_name": name}


def active(record, config):
    """True if every axis the record requires matches `config` (axis -> value)."""
    def has(axis, allowed):
        v = config.get(axis)
        return any(x in allowed for x in v) if isinstance(v, list) else v in allowed
    if config.get("_name") in (record.get("inactive_in") or ()):     # the namelist rules its registration out
        return False
    return all(has(axis, allowed) for axis, allowed in (record.get("requires") or {}).items())
