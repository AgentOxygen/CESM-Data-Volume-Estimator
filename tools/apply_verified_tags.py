"""reference/log_files/extracted_fields.yaml's "matched" names -> a
`verified: cesm3` override on that variable in data/<component>.yaml.

A name matching `tools/extract_log_fields.py`'s output means: this exact
name was registered by a real CESM3 run of this component, not just
carried over from the LENS2 (CESM2) seed. That's real evidence, so this
writes the override -- but only for atm/lnd/rof/ice. **ocn is deliberately
excluded**: `data/ocn.yaml` is POP2, CESM3's ocean is MOM6, and a POP2 name
incidentally matching something in an MOM6 run's log is far more likely a
coincidence (shared physical-quantity naming, e.g. `SST`) than a real
confirmation -- that file's `verified: cesm2-only` default stays as-is
regardless of what's in `extracted_fields.yaml`.

    python tools/apply_verified_tags.py

Edits data/<component>.yaml with a targeted text insertion -- not a
parse-and-redump -- so the diff is exactly the `verified: cesm3` lines
added and nothing else: no reordering, no incidental reflow of existing
`dims:`/`streams:` formatting. A variable that already carries its own
`verified:` override (none do today, but this stays idempotent if run
again later) is left alone, never clobbered.

Prints a sample of what it's about to add before writing, so there's
something concrete to spot-check -- this changes the hand-maintained
catalogue, unlike every other tool in this directory, which only ever
writes a generated file.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import estimator  # noqa: E402  (needs ROOT on sys.path first)

EXTRACTED = ROOT / "reference" / "log_files" / "extracted_fields.yaml"

# ocn is never included -- see module docstring.
COMPONENTS = ("atm", "lnd", "rof", "ice")

_NAME_LINE = re.compile(r"^- name: (\S+)\s*$")


def matched_names(extracted, component):
    entry = extracted.get(component)
    if not entry:
        return set()
    return {rec["name"] for rec in entry.get("matched", [])}


def add_verified_cesm3(path, names):
    """Insert `  verified: cesm3` right after every `- name: <X>` line
    where X is in `names`, unless that record already has its own
    `verified:` line. Returns the list of (name, dims_index) touched, for
    reporting -- a name with two dims-variants (CTSM's gridded/subgrid
    pairs) gets both, since the log confirms the *name* exists in CESM3,
    not a specific dims form of it.
    """
    lines = path.read_text().splitlines(keepends=True)
    out = []
    touched = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _NAME_LINE.match(line)
        if m and m.group(1) in names:
            j = i + 1
            has_verified = False
            while j < len(lines) and not _NAME_LINE.match(lines[j]):
                if re.match(r"^\s*verified:", lines[j]):
                    has_verified = True
                j += 1
            if not has_verified:
                out.append("  verified: cesm3\n")
                touched.append(m.group(1))
        i += 1
    path.write_text("".join(out))
    return touched


def main():
    if not EXTRACTED.exists():
        print(f"skipping: {EXTRACTED.relative_to(ROOT)} not found -- run "
              f"tools/extract_log_fields.py first.")
        return
    extracted = yaml.safe_load(EXTRACTED.read_text())

    print("Sample of what would be added (first 5 per component):")
    plan = {}
    for component in COMPONENTS:
        names = matched_names(extracted, component)
        plan[component] = names
        print(f"  {component}: {len(names)} names, e.g. {sorted(names)[:5]}")

    total = 0
    for component, names in plan.items():
        if not names:
            continue
        touched = add_verified_cesm3(ROOT / "data" / f"{component}.yaml", names)
        print(f"data/{component}.yaml: added verified: cesm3 to {len(touched)} records")
        total += len(touched)
    print(f"\n{total} records updated. Run `make test` before committing.")


if __name__ == "__main__":
    main()
