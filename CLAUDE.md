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

A static web page that turns the CMIP7 data request into per-component lists
of CESM3 history variables: pick an experiment, see which variables and
frequencies each component needs, download one text file per component. Goal
and workflow: `GOAL.md`. Every mapping carries a status (verified / spreadsheet
only / old CESM2 / missing) and a component source (log / catalogue / realm
guess) so it can be audited from the page. Full detail in `README.md`.

```
make test           # pytest, in Docker
make import-cmip7   # regenerate data/cmip7_request.yaml (needs local reference/)
make build          # regenerate docs/data.json
make dev            # http://localhost:8000, rebuilds + live-reloads on save
make shell          # shell in the dev container
```

- `reference/` is local-only and not committed. Code that reads it must skip
  gracefully when it is absent.
- `data/cmip7_request.yaml` and `docs/data.json` are generated and committed;
  regenerate both after changing the importer.
- `data/{atm,...}.yaml` is the frozen CESM2/LENS2 catalogue, kept only to
  label mappings as old-CESM2. Do not extend it.
- Plan and design history: `notes/cmip7-namelist-lists-plan.md` (current),
  `notes/cmip7-request-tool-plan.md` (earlier, partly superseded). Decisions
  go in the plan doc, not chat history.
- The LENS2 volume estimator that this replaced is at `main` 2f771c2 /
  `cmip7-request-tool` 12ed4dc.
- Open: log evidence is per component, not per line; the ocn (MOM6) log has no
  field list; optional data-volume figure not built.
