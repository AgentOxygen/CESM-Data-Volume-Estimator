# CMIP7 → CESM3 variable lists

A scientist is handed the full CMIP7 data request and has to work out which
CESM3 history variables to put in each component's namelist. This tool answers,
in order:

1. **Which variables does my experiment need?** Pick an experiment (and a
   priority cutoff) to get the matching CMIP7 compound names.
2. **Which CESM3 variables is that, by model component?** Each component
   (atm, lnd, ocn, ice, rof, glc) needs its own namelist.
3. **At which frequencies?** Every frequency needs its own entry, even for the
   same variable.
4. **Save the list.** One plain-text file per component, one `VARIABLE
   FREQUENCY` line each. Namelist formatting is a later step.

It is a static page (no server), published from `docs/` via GitHub Pages.

## Reading the mapping

The CMIP7 → CESM3 mapping comes from a spreadsheet, and it is not equally
trustworthy everywhere. Every variable shows how its mapping was derived, so the
page can be audited against the source data:

| Symbol | Status | Meaning |
|---|---|---|
| ✓ | verified | named in `CESM3_current.csv` **and** registered by a real CESM3 run's log |
| ◐ | spreadsheet only | named in the spreadsheet, not seen in any log |
| ↺ | old CESM2 mapping | only the CESM2/LENS2-era catalogue has it |
| ⚠ | missing | the spreadsheet row gives no CESM variable name (listed, never exported) |

A second marker says where the **component** came from: the run `log`, the old
`catalogue`, or a `realm` guess from the CMIP7 realm column
(`REALM_FALLBACK` in `tools/import_cmip7.py`). `≠realm` flags a variable the
log put in a different component than its realm implies.

Click any row for its audit trail: the raw spreadsheet cell, UID, CSV line,
priority groups and the logs involved. Each component's **audit .csv** carries
the same trail for every exported line; the `.txt` itself holds CESM3 names
only, never compound names.

## How the data is made

```
reference/CESM3_current.csv            the CMIP7 request joined to CESM variable names
reference/cmip7-data-request/*.csv     priority levels, variable groups
reference/log_files/                   real CESM3 run logs
        │  tools/extract_log_fields.py   → reference/log_files/extracted_fields.yaml
        │  tools/import_cmip7.py         (make import-cmip7)
        ▼
data/cmip7_request.yaml                 committed; every status/component decision lives here
        │  build.py                      (make build)
        ▼
docs/data.json                          committed; what the page loads
```

`reference/` is local-only and not committed, so a fresh clone can build and
test without it; the importer skips itself when its inputs are missing. All
judgement happens in Python at build time; the page only filters and groups.

`data/{atm,lnd,ocn,ice,rof,glc}.yaml` and `streams.yaml` are the frozen
CESM2/LENS2 catalogue. Nothing is priced from them any more; they exist only so
the importer can mark a mapping `↺ old CESM2`. Requests at `fx`, `subhr` and
`dec` frequencies are listed with their CMIP7 label like any other.

## Limitations

- One experiment at a time; no ensemble or multi-experiment arithmetic.
- The log evidence is per component, not per line, and the MOM6 (ocn) log has no
  field list, so most ocean variables are `◐` with a `realm` component.
- No data-volume estimate (the old tool's purpose); it may return as a
  secondary figure.

## Development

Everything runs in Docker.

```
make test          # pytest
make build         # regenerate docs/data.json from data/cmip7_request.yaml
make import-cmip7  # regenerate data/cmip7_request.yaml (needs reference/)
make dev           # http://localhost:8000, rebuilds and reloads on save
make shell
```

Commit `data/cmip7_request.yaml` and `docs/data.json` together; tests fail if
either is stale.

```
build.py             data/cmip7_request.yaml → docs/data.json
estimator.py         legacy-catalogue loader (used only by the importer)
tools/               importer, log extractor, dev server, screenshot helper — see tools/README.md
tests/               pytest suite
docs/index.html      the page: one file, vanilla JS
cesm-field-scraper/  standalone scraper of CESM3 source for registerable fields
```

## License

See [LICENSE](LICENSE).
