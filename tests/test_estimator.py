"""Tests for the data catalogue and the volume arithmetic.

The most valuable test here is test_every_dimension_resolves: it exercises every
dimension name in every data file against every configuration. That is what lets
the frontend be dumb -- it can never meet an unresolvable dimension at runtime.
"""

import json
import textwrap

import pytest
import yaml

import estimator
from estimator import DataError, bytes_per_sample, replace_subsequence


@pytest.fixture(scope="module")
def bundle():
    return estimator.build_bundle()


def find(bundle, component, name, dims=None):
    """The variable record, disambiguated by dims where a name has two forms."""
    hits = [v for v in bundle["vars"]
            if v["c"] == component and v["n"] == name
            and (dims is None or v["d"] == dims)]
    assert len(hits) == 1, f"{component}/{name} {dims or ''}: {len(hits)} matches"
    return hits[0]


def at(bundle, var, config_key):
    return var["b"][[c["key"] for c in bundle["configs"]].index(config_key)]


# --- the arithmetic ---------------------------------------------------------

def test_known_answer_3d_atmosphere(bundle):
    """atm/T on f09 with CAM6: 192 lat x 288 lon x 32 lev x 4 bytes."""
    assert at(bundle, find(bundle, "atm", "T"), "f09_g17|cam6") == 7_077_888


def test_known_answer_2d_atmosphere(bundle):
    """A 2-D field is the same minus the vertical dimension."""
    assert at(bundle, find(bundle, "atm", "PRECT"), "f09_g17|cam6") == 192 * 288 * 4


def test_vertical_config_is_independent_of_grid(bundle):
    """Switching CAM6 -> CAM7-LT scales a `lev` field by 58/32 and leaves a
    2-D field alone."""
    t = find(bundle, "atm", "T")
    assert at(bundle, t, "f09_g17|cam7-lt") == 192 * 288 * 58 * 4
    prect = find(bundle, "atm", "PRECT")
    assert at(bundle, prect, "f09_g17|cam6") == at(bundle, prect, "f09_g17|cam7-lt")


def test_ncol_swap_needs_no_variable_edit(bundle):
    """The CESM3 case: the same record resolves to lat*lon on an FV grid and to
    ncol on a spectral-element grid."""
    t = find(bundle, "atm", "T")
    assert at(bundle, t, "f09_g17|cam6") == 192 * 288 * 32 * 4
    assert at(bundle, t, "ne30pg3_g17|cam6") == 48_600 * 32 * 4


def test_ocean_and_ice_share_a_grid_under_different_dim_names(bundle):
    """ocn uses nlat/nlon and ice uses nj/ni for the same physical gx1v7 grid."""
    aice = find(bundle, "ice", "aice")
    assert at(bundle, aice, "f09_g17|cam6") == 384 * 320 * 4
    temp = find(bundle, "ocn", "TEMP")
    assert at(bundle, temp, "f09_g17|cam6") == 60 * 384 * 320 * 4


# --- the CTSM dual-form case ------------------------------------------------

def test_ctsm_variable_with_two_different_dims(bundle):
    """lnd/TSA is gridded in one stream and a per-patch vector in another. They
    are separate records with different sizes, and only the vector form is
    flagged approximate."""
    gridded = find(bundle, "lnd", "TSA", ["time", "lat", "lon"])
    vector = find(bundle, "lnd", "TSA", ["time", "pft"])
    assert at(bundle, gridded, "f09_g17|cam6") == 192 * 288 * 4
    assert at(bundle, vector, "f09_g17|cam6") == 623_910 * 4
    assert "a" not in gridded and vector["a"] == 1


def test_subgrid_variables_survive_the_horizontal_swap(bundle):
    """[time, pft] carries no lat/lon, so an SE grid must not alter it."""
    vector = find(bundle, "lnd", "TSA", ["time", "pft"])
    assert at(bundle, vector, "f09_g17|cam6") == at(bundle, vector, "ne30pg3_g17|cam6")


def test_zonal_mean_fields_are_excluded_on_se_grids(bundle):
    """Uzm is [time, ilev, lat, zlon] -- no [lat, lon] to swap, and its
    zonal-mean latitude axis is unknown on an SE grid, so it drops out."""
    uzm = find(bundle, "atm", "Uzm")
    assert at(bundle, uzm, "f09_g17|cam6") == 192 * 1 * 33 * 4
    assert at(bundle, uzm, "ne30pg3_g17|cam6") is None


# --- the catalogue as a whole -----------------------------------------------

def test_every_dimension_resolves(bundle):
    """Building at all proves every dim of every variable has a size on every
    configuration. This is what makes the frontend safe."""
    assert len(bundle["vars"]) > 2000
    assert len(bundle["configs"]) == 12
    for var in bundle["vars"]:
        assert len(var["b"]) == len(bundle["configs"])
        assert any(b is not None for b in var["b"]), var["n"]


def test_every_stream_is_declared(bundle):
    for var in bundle["vars"]:
        for stream in var["s"]:
            assert stream in bundle["streams"]


def test_bundle_is_not_stale():
    """Catches "edited the YAML, forgot `make build`" -- without this, GitHub
    Pages silently serves stale numbers."""
    current = estimator.dump_bundle(estimator.build_bundle())
    assert current == estimator.BUNDLE.read_text(), (
        "docs/data.json is out of date with data/*.yaml -- run `make build` "
        "and commit the result.")


def test_bundle_is_valid_json_one_variable_per_line():
    text = estimator.BUNDLE.read_text()
    assert json.loads(text)["vars"]
    # One variable per line keeps the committed diff readable.
    assert text.count("\n") > 2000


# --- pure helpers -----------------------------------------------------------

@pytest.mark.parametrize("dims,expected", [
    (["time", "lev", "lat", "lon"], ["time", "lev", "ncol"]),
    (["time", "lat", "lon"], ["time", "ncol"]),
    (["time", "pft"], ["time", "pft"]),                    # no match, untouched
    (["time", "ilev", "lat", "zlon"], ["time", "ilev", "lat", "zlon"]),
])
def test_replace_subsequence(dims, expected):
    assert replace_subsequence(dims, ["lat", "lon"], ["ncol"]) == expected


def test_null_size_excludes_but_missing_size_raises():
    var = {"name": "X", "dims": ["time", "boom"], "dtype_bytes": 4}
    assert bytes_per_sample(var, ["lat", "lon"], None, {"boom": None}, "here") is None
    with pytest.raises(DataError) as exc:
        bytes_per_sample(var, ["lat", "lon"], None, {}, "here")
    assert "boom" in str(exc.value) and "X" in str(exc.value)


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


def test_non_ocean_components_default_to_unknown():
    """Nobody has checked any of these against a real CESM3 history file
    yet. If this starts failing because a variable is now `cesm3`, that's
    good news -- update the assertion, don't revert it."""
    catalogue, _ = estimator.load_catalogue()
    for component in ("atm", "lnd", "ice", "rof", "glc"):
        assert all(v["verified"] == "unknown" for v in catalogue[component][1])


def test_data_files_parse_as_yaml():
    """A syntax error in any data file should fail here with the filename."""
    for name in ("grids.yaml", "vertical.yaml", "streams.yaml",
                 *(f"{c}.yaml" for c in estimator.COMPONENTS)):
        assert yaml.safe_load((estimator.DATA / name).read_text())
