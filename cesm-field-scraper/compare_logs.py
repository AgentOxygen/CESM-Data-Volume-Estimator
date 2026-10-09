"""python compare_logs.py OUT_DIR EXTRACTED_FIELDS.yaml CONFIGURATIONS.yaml CONFIG_NAME

Validation oracle: how well does the source catalogue, restricted to one configuration,
reproduce the field names a real run's log registered? Reports per component:
  recall    logged names found as an exact name among the configuration's records
  pattern   ... or matched only by a runtime-name pattern (glob) among them
  elsewhere ... or found only in records another configuration needs (a config-axis gap)
  missing   ... or nowhere (a source gap, a SourceMod, or a log-only name)
  extra     the configuration's exact names the log does not have (expected for other tapes/options)
  and, per certainty tier (literal name / expansion of <=12 / expansion of >12), the share found in the log
"""

import fnmatch
import sys
from pathlib import Path

import yaml

from cesm_fields.config import active, load


def main(out, logs, configs, name):
    config = load(configs, name)
    logged = yaml.safe_load(Path(logs).read_text())
    print(f"configuration {name}")
    for comp in ["atm", "lnd", "rof", "ice", "ocn"]:
        names = {r["name"] for sec in logged.get(comp, {}).values() if isinstance(sec, list) for r in sec if isinstance(r, dict) and r.get("name")}
        recs = yaml.safe_load(Path(out, f"{comp}.yaml").read_text())["fields"]
        on = [r for r in recs if active(r, config)]
        exact = {r["name"] for r in on if r["name"]}
        allnames = {r["name"] for r in recs if r["name"]}
        pats = [p for r in on if not r["name"] for p in r.get("name_patterns") or []]
        hit = names & exact
        pat = {n for n in names - exact if any(fnmatch.fnmatch(n, p) for p in pats)}
        elsewhere = (names - exact - pat) & allnames
        missing = names - exact - pat - elsewhere
        print(f"{comp}: logged {len(names)}  recall {len(hit)} ({len(hit)/max(len(names),1):.0%})  pattern {len(pat)}  "
              f"elsewhere {len(elsewhere)}  missing {len(missing)}  | config exact names {len(exact)}  extra {len(exact - names)}")
        # precision by how certain the source is: a literal name vs one expanded from a runtime-set loop
        tier = {}
        for r in on:
            if r["name"]:
                a = r.get("alternatives")
                t = "literal" if a is None else "expanded <=12" if a <= 12 else "expanded >12"
                tier[r["name"]] = min(tier.get(r["name"], t), t, key=["literal", "expanded <=12", "expanded >12"].index)
        for t in ["literal", "expanded <=12", "expanded >12"]:
            ns = [n for n, x in tier.items() if x == t]
            if ns:
                print(f"   {t:14} {len(ns):5} names, {sum(n in names for n in ns) / len(ns):.0%} in the log")
        if missing:
            print("   missing sample:", sorted(missing)[:12])
        if elsewhere:
            print("   elsewhere sample:", sorted(elsewhere)[:8])


if __name__ == "__main__":
    main(*sys.argv[1:])
