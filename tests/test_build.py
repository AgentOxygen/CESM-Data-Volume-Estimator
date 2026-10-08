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
