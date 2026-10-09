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

**This exists so an AI coding agent can see the page it just changed.** A human
maintainer should just open `make dev` in a browser; that is faster and
better. The script is here because an agent has no browser, and without it an
agent editing `docs/index.html` is working blind — it can verify the arithmetic
with `make test` but cannot tell whether the page actually renders, whether a
column overflows, or whether a selector silently matched nothing.

It drives headless Chromium over the DevTools Protocol and writes a PNG, and it
prints the browser console alongside it, so one run reports both the picture and
any JavaScript error. No Python dependencies — the WebSocket client is inlined.
A capture takes well under a second.

With no Chromium on `PATH` it falls back to Docker: it runs the public
`chromedp/headless-shell` image with host networking (DevTools on port 9222, so
nothing else may be using it), captures, and removes the container. The first run
pulls the image; later runs add about a second. Pages on the host, such as
`make dev`'s `http://localhost:8000/`, are reached as `localhost` unchanged.

```bash
make dev    # in another terminal

python3 tools/shot.py http://localhost:8000/ -o /tmp/check.png \
    --wait 'document.querySelector("tr.item")'
```

`--wait` polls a JS expression until it is truthy, then captures. **Use it** —
the page builds itself from `data.json` asynchronously, so a capture without it
photographs "Loading…". The expression may return anything, including a DOM
element; it is coerced to a boolean inside the browser.

Wait on the DOM rather than on a page variable: top-level `let`/`const` are not
properties of `window`, so `window.B !== undefined` never becomes true no matter
how loaded the page is.

`--eval` runs JS once before capture, which is how you photograph a specific
state rather than the default one. The page reads `?exp=<experiment>` from the
URL, so most states need no script at all:

```bash
python3 tools/shot.py 'http://localhost:8000/?exp=historical' -o /tmp/check.png \
    --wait 'document.querySelector("tr.item")'
```

Checkbox changes need an explicit `change` event, since setting `.checked` from
script does not fire one.

Other flags: `-s WIDTHxHEIGHT` (default 1280x800), `--settle` for extra seconds
of run time before capture (default 0.3), `--quiet` to drop the console output.

The console shows page errors and failed resource loads — a missing `data.json`
is the usual failure. Requests for `favicon.ico` are filtered out, so anything
you see is real.

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
