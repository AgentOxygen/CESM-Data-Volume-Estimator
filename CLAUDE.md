# Working in this repo

## Git — read this before touching git

- **Never commit without explicit review and approval first.** Make the
  change, show/describe it, and wait for the user to say to commit. This
  applies to every commit, not just large ones — there is no "small enough
  to just commit" exception.
- **Never push, and never open a PR, without being explicitly asked to in
  that moment.** A past approval does not carry forward to later changes.
- Do new work on a feature branch, not on `main`. The CMIP7 request-tool
  work (see below) lives on `cmip7-request-tool`.
- `notes/` and `reference/` each have their own `.gitignore` (a bare `*`),
  so everything inside them is untracked and local-only by design — this is
  intentional, not an oversight, and includes planning docs, not just data.

## What this project is

A static web page that estimates CESM output data volume: pick a grid and
vertical config, tick variables/frequencies, see the total. `estimator.py`
resolves `data/*.yaml` into `docs/data.json` at build time; the browser only
multiplies and sums. Full detail in `README.md`.

```
make test     # pytest, in Docker
make build    # regenerate docs/data.json
make dev      # http://localhost:8000, rebuilds + live-reloads on save
make shell    # shell in the dev container
```

## Active work: the CMIP7 data request tool

A second tool — start from the full CMIP7 data request, price it against a
CESM3 run, cut it down by priority level and by hand. **Plan and all design
decisions made so far live in `notes/cmip7-request-tool-plan.md` — read that
file before picking this work up or making further decisions about it.**
It is a living document: new decisions get written into it as they're made,
not left in chat history. If you're starting a fresh session on this work,
start there, not here.

Short version of where things stand (full reasoning and numbers are in the
plan doc, not repeated here):

- Source data: `reference/CESM3_current.csv` (the CMIP7 request joined to
  CESM variable names) and `reference/cmip7-data-request/*.csv` (Airtable
  export: priority levels, variable groups). Local-only, not committed
  (decided) — code that reads them must degrade gracefully, not error, when
  they're absent.
- Only `CESM Variable Name` is used for the join; `Formula`/`Scale` are
  ignored (those describe the CMIP-side computed value, not what CESM
  writes to history files).
- The catalogue (`data/*.yaml`) is CESM2/LENS2-pedigreed throughout, not
  just for ocean — a name match is not a confirmed CESM3 match. Needs a
  `verified: cesm3 | cesm2-only | unknown` tag per catalogue record/file
  before the CMIP7 join can be honest about it.
- Dedup the running total over `(CESM variable name, frequency)` pairs, not
  over request rows — the same native field is very often pulled in by
  multiple CMIP variables.
- v1 scope: single run (no ensemble/multi-experiment), priority-tier
  filtering only (no opportunity filtering), `fx`/`subhr`/`dec` frequencies
  deferred and marked unresolved rather than guessed at.
- Still genuinely open: where this lives in the UI (mode switch in
  `docs/index.html` vs. a separate page).

Don't re-derive any of the above from scratch — if something here looks
wrong or outdated, check the plan doc's history and ask rather than
silently overriding it.
