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
            # a catalogue-derived mapping must carry the catalogue state; a
            # log-derived one must name the logs that justify it
            assert (t["cs"] != "catalogue") or t["cat"]
            assert (t["st"] != "verified") == (not t["log"])


def test_dump_is_one_request_per_line():
    text = build.BUNDLE.read_text()
    assert text.count("\n") > len(json.loads(text)["requests"])


def test_sizes_cover_exactly_the_catalogue_matches_and_span_every_config():
    b = json.loads(build.BUNDLE.read_text())
    n = len(b["configs"])
    assert n == 12 and b["configs"][b["default_config"]]["key"] == build.DEFAULT_CONFIG
    assert b["sizes"]
    for key, s in b["sizes"].items():
        assert len(s["b"]) == n and any(x is not None for x in s["b"]), key
    # every priced line's key is a real component|name from the request
    used = {f"{t['c']}|{t['n']}" for r in b["requests"] for t in r["t"] if t["c"]}
    assert set(b["sizes"]) <= used


def test_known_answer_trefht_on_ne30pg3():
    """48,600 columns x 4 bytes. [time, lat, lon] -> [time, ncol] on SE grids."""
    b = json.loads(build.BUNDLE.read_text())
    keys = [c["key"] for c in b["configs"]]
    assert b["sizes"]["atm|TREFHT"]["b"][keys.index("ne30pg3_g17|cam7-lt")] == 48600 * 4


def test_per_year_leaves_fx_and_subhr_unpriced():
    assert "fx" not in build.PER_YEAR and "subhr" not in build.PER_YEAR
    assert build.PER_YEAR["mon"] == 12 and build.PER_YEAR["1hr"] == 8760


def test_pick_variant_prefers_the_gridded_record():
    gridded = {"dims": ["time", "lat", "lon"]}
    vector = {"dims": ["time", "pft"]}
    assert build.pick_variant([vector, gridded], ["lat", "lon"]) is gridded
    assert build.pick_variant([vector], ["lat", "lon"]) is vector
