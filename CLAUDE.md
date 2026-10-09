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

**CESM3-CMIP7-output-planner** (renamed from CESM-Data-Volume-Estimator; the volume estimate is now a
secondary feature). A static web page that turns the CMIP7 data request into per-component lists
of CESM3 history variables: pick an experiment, see which variables and
frequencies each component needs, download the namelists. Workflow and
status meanings: `README.md`. Every mapping carries a status (verified = in a run log / source = registered by
the CESM3 source for the baseline configuration / spreadsheet only / missing)
and a component source (log / source / realm guess) so it can be audited from the page. Full detail in `README.md`.

```
make test           # pytest, in Docker
make import-cmip7   # regenerate data/cmip7_request.yaml (needs local reference/)
make build          # regenerate docs/data.json
make dev            # http://localhost:8000, rebuilds + live-reloads on save
make shell          # shell in the dev container
```

- `cesm-field-scraper/out/` (the CESM3 source catalogue, one YAML per component) is local-only
  and not committed until approved; `tools/import_cmip7.py` reads it like `reference/` and, when
  absent, statuses rest on the logs alone and no line is priced. `data/aliases.yaml` holds reviewed renames.
- `reference/` is local-only and not committed. Code that reads it must skip
  gracefully when it is absent.
- `data/cmip7_request.yaml` and `docs/data.json` are generated and committed;
  regenerate both after changing the importer.
- The GB/yr estimates price a variable as 4 bytes x the grid's cells x the dimensions its CESM3
  source record gives (`build.py` + `data/grids.yaml`/`vertical.yaml`); anything unresolved is
  shown unpriced, not guessed. The old CESM2/LENS2 catalogue (`data/{atm,...}.yaml`) is gone.
- Plan and design history (local-only, in `notes/`): `cesm3-source-catalogue-plan.md` and
  `cmip7-namelist-export-plan.md` are current; the rest is superseded history. Decisions
  go in the plan doc, not chat history.
- The LENS2 volume estimator and the CESM2 catalogue are at `main` 2f771c2 /
  `cmip7-request-tool` 12ed4dc / `cesm3-source-catalogue` 1d4f037.
- Open: log evidence is per component, not per line; the ocn (MOM6) log has no
  field list; the source catalogue is for one configuration (BHISTE_MTt4s); volume covers only
  source-resolved variables.
