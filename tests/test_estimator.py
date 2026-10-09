"""Tests for the legacy catalogue loader/validator (see estimator.py)."""

import textwrap

import pytest
import yaml

import estimator
from estimator import DataError


# --- validation fails loudly ------------------------------------------------

def write_catalogue(tmp_path, monkeypatch, atm_body):
    """A minimal one-component catalogue, for testing the validator."""
    monkeypatch.setattr(estimator, "DATA", tmp_path)
    monkeypatch.setattr(estimator, "COMPONENTS", ("atm",))
    (tmp_path / "streams.yaml").write_text(
        "month_1: {samples_per_year: 12, label: monthly}\n")
    (tmp_path / "atm.yaml").write_text(textwrap.dedent(atm_body))


def test_unknown_variable_key_raises(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
          untis: K
        """)
    with pytest.raises(DataError, match="untis"):
        estimator.load_catalogue()


def test_duplicate_record_raises(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
        - name: T
          dims: [time, lat, lon]
          streams: {day_1: std}
        """)
    with pytest.raises(DataError, match="appears twice"):
        estimator.load_catalogue()


def test_undeclared_stream_raises(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {decade_1: std}
        """)
    with pytest.raises(DataError, match="decade_1"):
        estimator.load_catalogue()


# --- `verified` provenance ---------------------------------------------------

def test_verified_defaults_to_unknown(tmp_path, monkeypatch):
    """No `verified:` anywhere -> every variable is `unknown`, not silently
    trusted."""
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
        """)
    catalogue, _ = estimator.load_catalogue()
    assert catalogue["atm"][1][0]["verified"] == "unknown"


def test_verified_file_level_default_applies(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        verified: cesm2-only
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
        """)
    catalogue, _ = estimator.load_catalogue()
    assert catalogue["atm"][1][0]["verified"] == "cesm2-only"


def test_verified_per_variable_override(tmp_path, monkeypatch):
    """A variable can be confirmed against CESM3 without reclassifying the
    rest of its (still LENS2-seeded) file."""
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
          verified: cesm3
        - name: U
          dims: [time, lat, lon]
          streams: {month_1: std}
        """)
    catalogue, _ = estimator.load_catalogue()
    verified = {v["name"]: v["verified"] for v in catalogue["atm"][1]}
    assert verified == {"T": "cesm3", "U": "unknown"}


def test_invalid_file_level_verified_raises(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        verified: cesm2
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
        """)
    with pytest.raises(DataError, match="cesm2"):
        estimator.load_catalogue()


def test_invalid_variable_verified_raises(tmp_path, monkeypatch):
    write_catalogue(tmp_path, monkeypatch, """
        horiz_dims: [lat, lon]
        variables:
        - name: T
          dims: [time, lat, lon]
          streams: {month_1: std}
          verified: definitely
        """)
    with pytest.raises(DataError, match="definitely"):
        estimator.load_catalogue()


def test_ocn_catalogue_is_cesm2_only():
    """Regression test for the decision in notes/cmip7-request-tool-plan.md:
    CESM3's ocean is MOM6, data/ocn.yaml is POP2, and that is a confirmed
    mismatch, not an open question -- nobody should flip this file's default
    back to `unknown` without reading that doc."""
    catalogue, _ = estimator.load_catalogue()
    assert all(v["verified"] == "cesm2-only" for v in catalogue["ocn"][1])


def test_non_ocean_verified_states_are_only_unknown_or_cesm3():
    """atm/lnd/rof/ice have real per-variable `cesm3` overrides now --
    tools/apply_verified_tags.py, from a real CESM3 run's logs (see
    notes/cesm-source-scraper-evaluation.md) -- so this no longer asserts
    "everything is unknown". It still asserts nothing in these files is
    `cesm2-only`, which would mean someone mis-applied ocn.yaml's special
    case to a component that isn't a model-family swap."""
    catalogue, _ = estimator.load_catalogue()
    for component in ("atm", "lnd", "ice", "rof", "glc"):
        states = {v["verified"] for v in catalogue[component][1]}
        assert states <= {"unknown", "cesm3"}, (component, states)


def test_glc_has_no_cesm3_overrides_yet():
    """No CISM log/source evidence has been applied to data/glc.yaml --
    see notes/cesm-source-scraper-evaluation.md, which points at CISM's
    `*_vars.def` files as the route in, not yet taken."""
    catalogue, _ = estimator.load_catalogue()
    assert all(v["verified"] == "unknown" for v in catalogue["glc"][1])


def test_data_files_parse_as_yaml():
    """A syntax error in any data file should fail here with the filename."""
    for name in ("streams.yaml", "grids.yaml", "vertical.yaml",
                 *(f"{c}.yaml" for c in estimator.COMPONENTS)):
        assert yaml.safe_load((estimator.DATA / name).read_text())


# --- sizing helpers (restored for build.py) ---------------------------------

@pytest.mark.parametrize("dims,expected", [
    (["time", "lev", "lat", "lon"], ["time", "lev", "ncol"]),
    (["time", "pft"], ["time", "pft"]),                    # no match, untouched
])
def test_replace_subsequence(dims, expected):
    assert estimator.replace_subsequence(dims, ["lat", "lon"], ["ncol"]) == expected


def test_null_size_excludes_but_missing_size_raises():
    var = {"name": "X", "dims": ["time", "boom"], "dtype_bytes": 4}
    assert estimator.bytes_per_sample(var, ["lat", "lon"], None, {"boom": None}, "here") is None
    with pytest.raises(DataError, match="boom"):
        estimator.bytes_per_sample(var, ["lat", "lon"], None, {}, "here")
