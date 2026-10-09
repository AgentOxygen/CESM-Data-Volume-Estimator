"""Which registrations can run, given the namelist values of one configuration.

A history field is registered when its `addfld` executes. Whether it does depends on
(1) `if`/`select case` guards around it, and (2) the guards on every call on the way
down from a routine nothing calls. This reads both from the Fortran, evaluates the
guards against the configuration's namelist values (`namelist_defaults_cam.xml`
resolved for its `cam_config` attributes), and reports which source lines are dead.

Deliberately permissive: a guard that mentions a variable we have no value for (a run
time flag, a derived logical) is treated as possibly true. So this only removes
registrations the namelist rules out; it never invents one. Routines are matched by
name alone, across modules, and calls through generic interfaces or CCPP-generated code
are invisible (their routines look uncalled, which keeps them live).
"""

import re
from collections import defaultdict
from pathlib import Path

from . import fortran
from .common import read

UNKNOWN = None


# --- namelist defaults -----------------------------------------------------

def namelist_values(xml_path, attrs):
    """{lower-case name: value} from namelist_defaults_cam.xml for configure attributes `attrs`.

    Like build-namelist, the matching entry with the most attributes wins; an entry whose
    attribute disagrees with `attrs` (or names one we don't define) does not match.
    """
    best = {}
    for m in re.finditer(r"<(\w+)((?:\s+\w+=\"[^\"]*\")*)\s*>\s*([^<]*?)\s*</\1>", read(xml_path)):
        name, raw, value = m.group(1).lower(), m.group(2), m.group(3)
        entry = dict(re.findall(r"(\w+)=\"([^\"]*)\"", raw))
        if all(attrs.get(k) == v for k, v in entry.items()) and len(entry) >= best.get(name, (-1, None))[0]:
            best[name] = (len(entry), value)
    return {k: _value(v) for k, (_, v) in best.items()}


def _value(text):
    t = text.strip()
    low = t.lower()
    if low in (".true.", ".false."):
        return low == ".true."
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    return t.strip("'\"").lower()


# --- guard expressions (three-valued: True / False / UNKNOWN) --------------

TOKEN = re.compile(r"""\s*(?:(?P<str>'[^']*'|"[^"]*")|(?P<op>\.\w+\.|==|/=|<=|>=|<|>|\(|\)|,)|(?P<num>-?\d+(?:\.\d*)?)|(?P<id>[A-Za-z_][\w%]*))""")


def _tokens(text):
    pos, out = 0, []
    while pos < len(text.rstrip()):
        m = TOKEN.match(text, pos)
        if not m:
            return None
        pos = m.end()
        out.append((m.lastgroup, m.group(m.lastgroup)))
    return out


def evaluate(text, values):
    """True / False / UNKNOWN for a Fortran logical expression over namelist `values`."""
    toks = _tokens(text.strip())
    if toks is None:
        return UNKNOWN
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else (None, None)

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def land(a, b):
        return False if a is False or b is False else (UNKNOWN if a is UNKNOWN or b is UNKNOWN else True)

    def lor(a, b):
        return True if a is True or b is True else (UNKNOWN if a is UNKNOWN or b is UNKNOWN else False)

    def expr():
        a = term()
        while peek()[1] in (".or.", ".eqv.", ".neqv."):
            op = take()[1]
            b = term()
            a = lor(a, b) if op == ".or." else (UNKNOWN if a is UNKNOWN or b is UNKNOWN else (a == b) == (op == ".eqv."))
        return a

    def term():
        a = factor()
        while peek()[1] == ".and.":
            take()
            a = land(a, factor())
        return a

    def factor():
        if peek()[1] == ".not.":
            take()
            v = factor()
            return UNKNOWN if v is UNKNOWN else not v
        return comparison()

    def comparison():
        a = atom()
        if peek()[1] in ("==", "/=", "<", ">", "<=", ">=", ".eq.", ".ne.", ".lt.", ".gt.", ".le.", ".ge."):
            op = {".eq.": "==", ".ne.": "/=", ".lt.": "<", ".gt.": ">", ".le.": "<=", ".ge.": ">="}.get(peek()[1], peek()[1])
            take()
            b = atom()
            if a is UNKNOWN or b is UNKNOWN:
                return UNKNOWN
            a, b = (a.lower(), b.lower()) if isinstance(a, str) and isinstance(b, str) else (a, b)
            try:
                return {"==": a == b, "/=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
            except TypeError:
                return UNKNOWN
        return a

    def atom():
        kind, tok = take() if peek()[0] else (None, None)
        if kind == "str":
            return tok[1:-1]
        if kind == "num":
            return int(float(tok)) if re.fullmatch(r"-?\d+", tok) else float(tok)
        if tok == "(":
            v = expr()
            if peek()[1] == ")":
                take()
            return v
        if tok in (".true.", ".false."):
            return tok == ".true."
        if kind == "id":
            name = tok.lower()
            if peek()[1] == "(":                       # call or array reference: a pass-through function or unknown
                depth, args = 0, []
                while peek()[0]:
                    k, t = take()
                    depth += (t == "(") - (t == ")")
                    if depth == 0:
                        break
                    args.append((k, t))
                if name == "cam_physpkg_is" and len(args) == 2 and args[1][0] == "str" and "__phys__" in values:
                    return values["__phys__"] == args[1][1][1:-1].lower()
                if name in ("trim", "adjustl", "adjustr") and len(args) == 2 and args[1][0] in ("str", "id"):
                    return values.get(args[1][1].lower(), UNKNOWN) if args[1][0] == "id" else args[1][1][1:-1]
                return UNKNOWN
            return values.get(name, UNKNOWN)
        return UNKNOWN

    try:
        result = expr()
    except (IndexError, TypeError):
        return UNKNOWN
    return result if isinstance(result, bool) else UNKNOWN


# --- structure: routines, guards, calls -----------------------------------

ROUTINE = re.compile(r"^(?:[\w\s\(\)=\*,:]*?\s)?(?:subroutine|function)\s+(\w+)", re.I)
END_ROUTINE = re.compile(r"^end\s*(?:subroutine|function)\b", re.I)


def _paren_split(text):
    """('cond', rest) for `(cond) rest`, balancing parentheses."""
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            return text[1:i], text[i + 1:].strip()
    return None, ""


def analyse(text):
    """([(line, routine, [guard texts], statement)], [(caller, callee, line, [guards])]) for one source file."""
    stmts, edges, routine = [], [], None
    blocks = []                                   # open if/select blocks: [kind, [guards active in this arm], [negations so far], selector]
    for line, stmt in fortran.statements(text):
        s = stmt.strip()
        low = s.lower()
        if END_ROUTINE.match(low):
            routine, blocks = None, []
            continue
        if not routine and (m := ROUTINE.match(s)) and not low.startswith(("end", "call", "use")) and "=" not in low.split("(")[0]:
            routine = m.group(1).lower()
        guards = [g for b in blocks for g in b[1]]
        if m := re.match(r"^if\s*\(", low):
            cond, rest = _paren_split(s[2:].strip())
            if cond is not None and rest.lower() == "then":
                blocks.append(["if", [cond], [cond], None])
                continue
            if cond is not None and rest:                # one-line `if (cond) stmt`
                guards, s, low = guards + [cond], rest, rest.lower()
        elif m := re.match(r"^else\s*if\s*\(", low):
            cond, _ = _paren_split(s[s.lower().index("if") + 2:].strip())
            if blocks and cond is not None:
                top = blocks[-1]
                top[1] = [f".not.({c})" for c in top[2]] + [cond]
                top[2].append(cond)
            continue
        elif re.match(r"^else$", low):
            if blocks:
                blocks[-1][1] = [f".not.({c})" for c in blocks[-1][2]]
            continue
        elif re.match(r"^end\s*if$", low) or re.match(r"^end\s*select$", low):
            if blocks:
                blocks.pop()
            continue
        elif m := re.match(r"^select\s*case\s*\(", low):
            sel, _ = _paren_split(s[s.lower().index("(") :])
            blocks.append(["select", [], [], sel])
            continue
        elif blocks and blocks[-1][0] == "select" and re.match(r"^case\b", low):
            top = blocks[-1]
            if "default" in low:
                top[1] = [f".not.({c})" for c in top[2]]
            else:
                vals, _ = _paren_split(s[s.lower().index("(") :])
                cond = " .or. ".join(f"({top[3]}) == {v.strip()}" for v in vals.split(","))
                top[1] = [cond]
                top[2].append(cond)
            continue
        stmts.append((line, routine, list(guards), s))
        if routine:
            for c in re.finditer(r"\bcall\s+(?:[\w]+%)*(\w+)", s, re.I):
                edges.append((routine, c.group(1).lower(), line, list(guards)))
    return stmts, edges


def ccpp_schemes_off(root, files, suite_xml):
    """Files that are CCPP schemes (a `.meta` file beside them names them) none of which is in the suite.

    CCPP calls its schemes from generated code, so there is no `call` to follow: the suite
    definition is what decides which schemes run."""
    suite = set(re.findall(r"<scheme>\s*([^<\s]+)\s*</scheme>", read(Path(root) / suite_xml)))
    off = set()
    for rel in files:
        meta = (Path(root) / rel).with_suffix(".meta")
        if meta.exists():
            names = set(re.findall(r"^\s*name\s*=\s*(\w+)", read(meta), re.M))
            if names and not names & suite:
                off.add(rel)
    return off


def derived_values(statements, values):
    """Add `flag = <logical expression of namelist values>` assignments that evaluate to one constant
    wherever they occur (`is_clubb_scheme = eddy_scheme == 'CLUBB_SGS'`)."""
    values = dict(values)
    seen = defaultdict(set)
    for _, _, _, s in statements:
        m = re.match(r"^(\w+)\s*=(?!=)\s*(.+)$", s)
        # A bare `.true.`/`.false.` is a default that a namelist read or other code may change: not a derivation.
        if m and m.group(1).lower() not in values and not re.fullmatch(r"\s*\.(true|false)\.\s*", m.group(2), re.I):
            seen[m.group(1).lower()].add(m.group(2))
    for _ in range(3):                                   # a derived flag may use another
        for var, rhss in seen.items():
            if var in values:
                continue
            results = {evaluate(r, values) for r in rhss}
            if len(results) == 1 and results <= {True, False}:
                values[var] = results.pop()
    return values


def mark_inactive(records, root, name, config):
    """Set `inactive_in` on every record whose registration the configuration's namelist rules out.

    `config` has `cam_config` (configure attributes) and `ccpp_suite` (a suites/ file under src/atmos_phys)."""
    root = Path(root)
    values = namelist_values(root / "bld/namelist_files/namelist_defaults_cam.xml", config["cam_config"])
    values["__phys__"] = config["cam_config"]["phys"]
    files = sorted({r["source"].rsplit(":", 1)[0] for r in records if r["source"].startswith("src/")})
    dead = dead_lines(root, files, values, ccpp_schemes_off(root, files, f"src/atmos_phys/suites/suite_{config['ccpp_suite']}.xml"))
    for r in records:
        path, _, line = r["source"].rpartition(":")
        if line.isdigit() and int(line) in dead.get(path, ()):
            r.setdefault("inactive_in", []).append(name)


def dead_lines(root, files, values, ccpp_off=()):
    """{relative path: set of dead line numbers} among `files` (paths under `root`)."""
    info, edges, defined, parsed = {}, [], defaultdict(set), {}
    for rel in files:
        parsed[rel] = analyse(read(Path(root) / rel))
    values = derived_values([st for stmts, _ in parsed.values() for st in stmts], values)
    for rel in files:
        stmts, es = parsed[rel]
        info[rel] = {line: (routine, guards) for line, routine, guards, _ in stmts}
        edges += [(a, b, g) for a, b, _, g in es]
        for _, routine, _, _ in stmts:
            if routine:
                defined[routine].add(rel)
    live = defaultdict(list)                      # callee -> live callers
    called = set()
    for caller, callee, guards in edges:
        called.add(callee)
        if all(evaluate(g, values) is not False for g in guards):
            live[callee].append(caller)
    reachable = {r for r in defined if r not in called}      # nothing calls it: an entry point
    changed = True
    while changed:
        changed = False
        for callee, callers in live.items():
            if callee in defined and callee not in reachable and any(c in reachable for c in callers):
                reachable.add(callee)
                changed = True
    dead = defaultdict(set)
    for rel, lines in info.items():
        for line, (routine, guards) in lines.items():
            if rel in ccpp_off or (routine and routine not in reachable) or any(evaluate(g, values) is False for g in guards):
                dead[rel].add(line)
    return dead
