"""Just enough free-form Fortran to read CESM's history-registration calls.

Not a Fortran parser: logical statements (comments stripped, `&`
continuations joined), call arguments split at top-level commas, and
literal evaluation. Anything that isn't a literal comes back as `Expr`.
`#ifdef` lines are dropped, so every preprocessor branch is read.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Expr:
    """A non-literal argument: its source text, whitespace-squashed."""
    text: str


@dataclass
class Call:
    line: int
    args: list   # positional argument text
    kw: dict     # lower-cased keyword -> argument text


def _split(text, sep):
    """Split on `sep` outside quotes and brackets."""
    parts, cur, depth, quote, i = [], [], 0, None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            quote = None if ch == quote else quote
        elif depth == 0 and text.startswith(sep, i):
            parts.append("".join(cur).strip())
            cur, i = [], i + len(sep)
            continue
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        cur.append(ch)
        i += 1
    parts.append("".join(cur).strip())
    return parts


def statements(source):
    """(starting line, text) for each logical statement."""
    buf, start = [], None
    for lineno, raw in enumerate(source.splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        line = re.match(r"""^((?:[^!'"]|'[^']*'?|"[^"]*"?)*)""", raw).group(1).strip()   # drop `! comment`
        if not line:
            continue
        if buf and line.startswith("&"):
            line = line[1:].lstrip()
        start = start or lineno
        if line.endswith("&"):
            buf.append(line[:-1].rstrip())
            continue
        yield start, " ".join(buf + [line])
        buf, start = [], None


def find_calls(line, text, name):
    """Every `name(...)` in a statement, as `call name(...)` or `x = name(...)`."""
    if re.search(rf"\b(subroutine|function)\s+{name}\s*\(", text, re.I):
        return []   # the definition, not a call site
    calls = []
    for m in re.finditer(rf"(?<![\w%]){name}\s*\(", text, re.I):
        args = _split(text[m.end():], ")")[0]   # up to the matching paren
        call = Call(line, [], {})
        for a in _split(args, ","):
            k = re.match(r"([A-Za-z_]\w*)\s*=(?!=)\s*(.*)$", a, re.S)
            if k:
                call.kw[k.group(1).lower()] = k.group(2)
            else:
                call.args.append(a)
        calls.append(call)
    return calls


def arg(call, position, keyword):
    """An argument by keyword, else by position, else None."""
    if keyword in call.kw:
        return call.kw[keyword]
    return call.args[position] if position is not None and position < len(call.args) else None


def _unwrap(text):
    while (m := re.match(r"^(?:trim|adjustl)\s*\((.*)\)$", text, re.I | re.S)):
        text = m.group(1).strip()
    return text


def _string(text):
    m = re.match(r"""^(?:'((?:[^']|'')*)'|"((?:[^"]|"")*)")$""", text, re.S)
    if m:
        return m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2).replace('""', '"')


def literal(text):
    """A string literal or `//` concatenation of them -> str, else Expr."""
    if text is None:
        return None
    parts = [_string(_unwrap(p)) for p in _split(text, "//")]
    return Expr(" ".join(text.split())) if None in parts else "".join(parts)


def name(text):
    """`literal()` with blanks dropped, as the registries do (`'AEROD_v '`)."""
    value = literal(text)
    return value.strip() if isinstance(value, str) else value


def literal_list(text):
    """`(/ 'a', 'b' /)` or `['a', 'b']` -> ['a', 'b'], else Expr."""
    m = re.match(r"^(?:\(/(.*)/\)|\[(.*)\])$", text.strip(), re.S)
    items = [literal(a) for a in _split(m.group(1) or m.group(2), ",")] if m else [Expr("")]
    if any(isinstance(i, Expr) for i in items):
        return Expr(" ".join(text.split()))
    return [i.strip() for i in items]


def assignments(stmts):
    """Variable -> right-hand sides assigned to it that contain a string.

    Covers `ptendnam(m) = 'PTE'//cnst_name(m)` and
    `character(len=*), parameter :: vr_suffix = "_vr"`. File-wide, blind to
    which subroutine an assignment is in.
    """
    env = {}
    for _, text in stmts:
        if "'" not in text and '"' not in text:
            continue
        m = re.match(r"^(?:[^'\"]*::\s*)?([A-Za-z_]\w*)\s*(?:\([^='\"]*\))?\s*=(?!=)\s*(.+)$", text, re.S)
        if m:
            env.setdefault(m.group(1).lower(), []).append(m.group(2))
    return env


MAX_ALTERNATIVES = 400   # the baseline chemistry has 154 constituents; one loop over them must expand


def expand(text, env, known=None, depth=0):
    """Every name a `//` expression can produce, with `*` for unknown pieces.

    A piece that is a variable assigned in the same file (`env`) expands
    through its assignments; a piece whose variable is in `known` (CAM's
    constituent arrays) expands to those names. `'SF'//cnst_name(m)` ->
    ['SFQ', 'SFO3', ...]; `'ABSORB'//diag(ilist)` -> ['ABSORB*'].
    """
    known = known or {}
    alts = [""]
    for part in _split(text, "//"):
        part = _unwrap(part)
        value = _string(part)
        if value is not None:
            options = [value]
        else:
            ref = re.match(r"^([A-Za-z_]\w*)\s*(\(.*\))?$", part, re.S)
            var = ref.group(1).lower() if ref else None
            index = ref.group(2)[1:-1].strip().lower() if ref and ref.group(2) else None
            fixed = known.get("__index__", {}).get(index)          # `cnst_name(ixcldice)`: one named constituent
            if var in known and fixed and var == "cnst_name":
                options = [fixed]
            elif var in known.get("__templates__", {}) and fixed:  # `ptendnam(ixcldice)`: its template at that constituent
                options = sorted({o for rhs in known["__templates__"][var] for o in expand(rhs, {}, {"cnst_name": [fixed]})})
            elif var in known:
                options = known[var]
            elif var in env and depth < 3:
                # a declaration with a list initialiser (`diag(0:9) = (/'', '_d1', ...)`) is its list of strings
                options = sorted({o for rhs in env[var] for o in
                                  (literal_list(rhs) if rhs.lstrip().startswith("(/") and not isinstance(literal_list(rhs), Expr)
                                   else expand(rhs, env, known, depth + 1))})
                if var == "diag" and index == "icall":
                    # radiation's extra diagnostic calls ('_d1'..'_d10') exist only if the namelist asks for them
                    options = [o for o in options if o == ""] or options
            else:
                options = ["*"]
        alts = [a + o for a in alts for o in options]
        if len(alts) > MAX_ALTERNATIVES:   # ponytail: give up rather than list hundreds of guesses
            return ["*"]
    return sorted({re.sub(r"\*+", "*", a).strip() for a in alts})
