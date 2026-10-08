"""data/cmip7_request.yaml -> docs/data.json, the file the web page loads.

    python build.py        # regenerate docs/data.json

All judgement (status, component, fallbacks) was made by tools/import_cmip7.py
and is already in the YAML. This only reshapes it for the browser: nothing is
re-derived here, and nothing is dropped that the audit view displays.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "cmip7_request.yaml"
BUNDLE = ROOT / "docs" / "data.json"

COMPONENTS = ["atm", "lnd", "ocn", "ice", "rof", "glc"]
STATUSES = ["verified", "spreadsheet-only", "cesm2"]       # + "missing" (no tokens)
COMPONENT_SOURCES = ["log", "catalogue", "realm-fallback"]


def build_bundle():
    doc = yaml.safe_load(SOURCE.read_text())
    requests = [{
        "n": r["name"], "u": r["uid"], "l": r["source_line"], "raw": r["raw_cesm_name"],
        "realm": r["realm"], "f": r["frequency"], "p": r["priority"],
        "g": r["groups"], "fc": r["fallback_component"],
        "t": [{"n": t["name"], "st": t["status"], "c": t["component"],
               "cs": t["component_source"], "log": t["log_components"],
               "cat": t["catalogue_state"], "mm": t["realm_mismatch"]}
              for t in r["tokens"]],
    } for r in doc["requests"]]
    return {"components": COMPONENTS, "statuses": STATUSES,
            "component_sources": COMPONENT_SOURCES,
            "experiments": doc["experiments"], "requests": requests}


def dump_bundle(bundle):
    """One request / one experiment per line, so a regenerated bundle diffs
    readably."""
    j = lambda o: json.dumps(o, separators=(",", ":"))
    head = {k: v for k, v in bundle.items() if k not in ("experiments", "requests")}
    lines = [j(head)[:-1] + ',', '"experiments":{']
    lines.append(",\n".join(f"{j(k)}:{j(v)}" for k, v in bundle["experiments"].items()))
    lines += ['},', '"requests":[', ",\n".join(j(r) for r in bundle["requests"]), "]}"]
    return "\n".join(lines) + "\n"


def main():
    if not SOURCE.exists():
        sys.exit(f"{SOURCE.relative_to(ROOT)} is missing -- it is committed; "
                 f"restore it or run `make import-cmip7`.")
    bundle = build_bundle()
    BUNDLE.parent.mkdir(exist_ok=True)
    BUNDLE.write_text(dump_bundle(bundle))
    print(f"{BUNDLE.relative_to(ROOT)}: {len(bundle['requests'])} requests, "
          f"{len(bundle['experiments'])} experiments, "
          f"{BUNDLE.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
