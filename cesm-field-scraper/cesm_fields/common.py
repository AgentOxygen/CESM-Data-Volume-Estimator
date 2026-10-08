"""Walking source and building records -- shared by every component."""

from pathlib import Path

from . import fortran
from .fortran import Expr


def read(path):
    return Path(path).read_text(errors="replace")


def calls(root, under, names):
    """(path relative to root, routine, Call, env) for each call to one of `names`."""
    for path in sorted((root / under).rglob("*.[Ff]90")):
        stmts = list(fortran.statements(read(path)))
        env = fortran.assignments(stmts)
        rel = path.relative_to(root).as_posix()
        for line, text in stmts:
            for name in names:
                for call in fortran.find_calls(line, text, name):
                    yield rel, name, call, env


def records(*, name, dims, horizontal, registrar, source, time=True,
            env=None, known=None, patterns=None, **attrs):
    """The record(s) for one call site.

    A literal name gives one record. A runtime-built name is expanded
    (`fortran.expand`, or `patterns` if the caller already knows them):
    every fully-resolved alternative becomes its own record, keeping
    `name_expr` so it's visibly derived, and anything left with a `*` goes
    on one `name: null` record as `name_patterns`.
    """
    body = {"dims": None, "dims_expr": dims.text} if isinstance(dims, Expr) else {"dims": list(dims)}
    body["horizontal"] = None if isinstance(horizontal, Expr) else horizontal
    body["time"] = time
    body.update({k: " ".join(v.split()) for k, v in attrs.items() if isinstance(v, str)})
    body.update(registrar=registrar, source=source)
    if isinstance(name, str):
        return [{"name": name, **body}]
    alts = patterns if patterns is not None else fortran.expand(name.text, env, known)
    out = [{"name": n, "name_expr": name.text, **body} for n in alts if "*" not in n]
    globs = [g for g in alts if "*" in g and g != "*"]
    if globs or not out:
        out.append({"name": None, "name_expr": name.text, **({"name_patterns": globs} if globs else {}), **body})
    return out
