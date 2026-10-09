# tools/

Development scripts. None of them is needed to run or deploy the site.

## dev.py — the iteration loop

`make dev` runs this. It serves `docs/` on http://localhost:8000 and watches
`data/cmip7_request.yaml`, rebuilding `docs/data.json` on every save. The page reloads
itself when either it or the bundle changes, so editing `docs/index.html` or the
request YAML and saving is the whole loop.

The repo is bind-mounted into the container, so host edits are visible instantly
— what this adds is the rebuild and the reload.

- Files are served `Cache-Control: no-store`, so a reload always gets current
  bytes rather than a cached page.
- Live reload lives in `docs/index.html` and is guarded on
  `location.hostname === "localhost"`, so it is inert on GitHub Pages. It polls
  `Last-Modified` once every 700 ms.
- A reload discards whatever was selected on the page. That is usually what you
  want while iterating on layout.
- A build error prints `BUILD FAILED` with the parser message and leaves
  the server running on the last good bundle. Fix the file and the next save
  rebuilds.

Stdlib only — it polls mtimes rather than taking a dependency on a file-watching
library.

## shot.py — primarily for LLM agents

This exists so an AI coding agent can see the page it just changed; a human should
just open `make dev` in a browser. It drives headless Chromium over the DevTools
Protocol, writes a PNG and prints the browser console, so one run reports both the
picture and any JavaScript error. No Python dependencies. With no Chromium on `PATH`
it falls back to the public `chromedp/headless-shell` image (host networking, DevTools
on port 9222, so nothing else may be using it), pulled on first use and removed after
each capture; pages on the host, such as `make dev`'s `http://localhost:8000/`, are
reached as `localhost`.

```bash
make dev    # in another terminal
python3 tools/shot.py 'http://localhost:8000/?exp=historical' -o /tmp/check.png \
    --wait 'document.querySelector("tr.item")'
```

- `--wait JS` polls an expression until truthy before capturing. **Use it**: the page builds
  itself from `data.json` asynchronously, so a capture without it photographs "Loading…".
  Wait on the DOM, not on a page variable (top-level `let`/`const` are not `window` properties).
- `--eval JS` runs script once first, to photograph a specific state. The page reads
  `?exp=<experiment>` from the URL, so most states need none. Checkbox changes need an explicit
  `change` event; setting `.checked` does not fire one.
- `-s WIDTHxHEIGHT` (default 1280x800), `--settle` extra seconds (default 0.3), `--quiet` to drop the console.

The console shows page errors and failed resource loads (favicon requests are filtered out).

## import_cmip7.py — regenerates data/cmip7_request.yaml

`make import-cmip7`. Joins the CMIP7 request (`reference/CESM3_current.csv`,
priority CSVs) to CESM3 run-log field lists
(`reference/log_files/extracted_fields.yaml`) and the CESM3 source catalogue
(`cesm-field-scraper/out`), writing the committed `data/cmip7_request.yaml`. The inputs are local-only; without them
the script prints why and leaves the file alone. See its docstring for the
status and component-source rules.

## extract_log_fields.py — CESM3 run logs -> extracted_fields.yaml

Parses the field lists in a real CESM3 run's logs (`reference/log_files/`).
Run it, then `make import-cmip7`, whenever new logs arrive.
