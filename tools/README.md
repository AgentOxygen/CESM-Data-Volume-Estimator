# tools/

Development scripts. Neither is needed to run or deploy the site.

## shot.py — primarily for LLM agents

**This exists so an AI coding agent can see the page it just changed.** A human
maintainer should just open `make serve` in a browser; that is faster and
better. The script is here because an agent has no browser, and without it an
agent editing `docs/index.html` is working blind — it can verify the arithmetic
with `make test` but cannot tell whether the page actually renders, whether a
column overflows, or whether a selector silently matched nothing.

It drives headless Chromium over the DevTools Protocol and writes a PNG, and it
prints the browser console alongside it, so one run reports both the picture and
any JavaScript error. No Python dependencies — the WebSocket client is inlined.
A capture takes well under a second.

```bash
make serve    # in another terminal

python3 tools/shot.py http://localhost:8000/ -o /tmp/check.png \
    --wait 'document.querySelector("tr[data-i]")'
```

`--wait` polls a JS expression until it is truthy, then captures. **Use it** —
the page builds itself from `data.json` asynchronously, so a capture without it
photographs "Loading…". The expression may return anything, including a DOM
element; it is coerced to a boolean inside the browser.

Wait on the DOM rather than on a page variable: top-level `let`/`const` are not
properties of `window`, so `window.B !== undefined` never becomes true no matter
how loaded the page is.

`--eval` runs JS once before capture, which is how you photograph a specific
state rather than the default one:

```bash
# The LENS2 std preset, filtered to one variable, all sections expanded
python3 tools/shot.py http://localhost:8000/ -o /tmp/check.png \
    --wait 'document.querySelector("tr[data-i]")' \
    --eval 'document.querySelector("[data-preset=std]").click();
            const f = document.getElementById("filter");
            f.value = "TSA"; f.dispatchEvent(new Event("input"));
            for (const d of document.querySelectorAll("details")) d.open = true;'
```

Changing the configuration dropdown needs an explicit `change` event, since
setting `selectedIndex` from script does not fire one:

```js
const c = document.getElementById("config");
c.selectedIndex = [...c.options].findIndex(o => o.text.includes("ne30pg3"));
c.dispatchEvent(new Event("change"));
```

Other flags: `-s WIDTHxHEIGHT` (default 1280x800), `--settle` for extra seconds
of run time before capture (default 0.3), `--quiet` to drop the console output.

The console shows page errors and failed resource loads — a missing `data.json`
is the usual failure. Requests for `favicon.ico` are filtered out, so anything
you see is real.

## import_csv.py — one-time seeder, kept for provenance

Regenerates every `data/<component>.yaml` from
`reference/lens2output200129.csv`. It has already been run; the YAML files it
produced are now the source of truth and are **maintained by hand**.

```bash
make import    # overwrites data/*.yaml — you almost never want this
```

Run it only to re-derive the seed from scratch. Anything you hand-edited in
`data/*.yaml` will be lost.

Future imports from other sources (CAM `addfld`, CTSM `hist_addfld`, `ncdump`
headers) should be separate scripts emitting the same schema, not extensions of
this one. Don't invest in it.
