"""Tests for build.py, the data/cmip7_request.yaml -> docs/data.json step."""

import json

import build


def test_bundle_is_not_stale():
    """Catches "regenerated the YAML, forgot `make build`" -- without this,
    GitHub Pages silently serves an old request."""
    assert build.dump_bundle(build.build_bundle()) == build.BUNDLE.read_text(), (
        "docs/data.json is out of date with data/cmip7_request.yaml -- run "
        "`make build` and commit the result.")


def test_bundle_is_valid_json_and_internally_consistent():
    b = json.loads(build.BUNDLE.read_text())
    n = len(b["requests"])
    assert n > 1000 and b["experiments"]
    for indices in b["experiments"].values():
        assert all(0 <= i < n for i in indices)
    for r in b["requests"]:
        assert r["fc"] in b["components"]
        for t in r["t"]:
            assert t["st"] in b["statuses"]
            assert t["cs"] in b["component_sources"]
            assert t["c"] in b["components"]
            # a log-derived mapping must name the logs that justify it; a source-derived one, where
            assert (t["st"] != "verified") == (not t["log"])
            assert (t["st"] != "source") or (t["sc"] and t["ref"])


def test_dump_is_one_request_per_line():
    text = build.BUNDLE.read_text()
    assert text.count("\n") > len(json.loads(text)["requests"])


def test_sizes_are_priced_lines_that_span_every_config():
    b = json.loads(build.BUNDLE.read_text())
    n = len(b["configs"])
    assert n == 3 and b["configs"][b["default_config"]]["key"] == build.DEFAULT_CONFIG
    assert b["sizes"]
    for key, s in b["sizes"].items():
        assert len(s["b"]) == n and any(x is not None for x in s["b"]), key
    # every priced line's key is a real component|name from the request
    used = {f"{t['c']}|{t['n']}" for r in b["requests"] for t in r["t"] if t["c"]}
    assert set(b["sizes"]) <= used


def test_known_answer_trefht_on_ne30pg3():
    """48,600 columns x 4 bytes, a 2-D field."""
    b = json.loads(build.BUNDLE.read_text())
    keys = [c["key"] for c in b["configs"]]
    assert b["sizes"]["atm|TREFHT"]["b"][keys.index("ne30pg3_t233|cam7-mt")] == 48600 * 4


def test_per_year_leaves_fx_and_subhr_unpriced():
    assert "fx" not in build.PER_YEAR and "subhr" not in build.PER_YEAR
    assert build.PER_YEAR["mon"] == 12 and build.PER_YEAR["1hr"] == 8760


GRID = {"atm": {"cells": 100}, "ocn": {"cells": 50, "sizes": {"zl": 10}}, "lnd": {"cells": 100, "sizes": {"levsoi": 3}},
        "glc": None}
VERT = {"sizes": {"lev": 4, "ilev": 5}}


def test_bytes_per_sample_cells_times_dims():
    size = lambda *a: build.bytes_per_sample(*a, GRID, VERT)
    assert size("atm", [], "physgrid") == (4 * 100, None)
    assert size("atm", ["lev"], "physgrid") == (4 * 100 * 4, None)          # vertical sizes come from the vertical config
    assert size("ocn", ["zl"], "T") == (4 * 50 * 10, None)
    assert size("ocn", ["zl"], None) == (4 * 10, None)                     # no horizontal dims: a profile or scalar
    assert size("lnd", ["levsoi"], "column") == (4 * 100 * 3, None)         # a subgrid field is priced as gridded output


def test_bytes_per_sample_leaves_out_what_it_cannot_size():
    size = lambda *a: build.bytes_per_sample(*a, GRID, VERT)
    assert size("atm", ["mystery"], "physgrid")[0] is None and "mystery" in size("atm", ["mystery"], "physgrid")[1]
    assert size("atm", [], "GLL")[0] is None                                # CAM's other grids have no cell count here
    assert size("atm", None, "physgrid")[0] is None                         # dims the source left unresolved
    assert size("glc", [], "x")[0] is None                                  # CISM does not run on this grid
