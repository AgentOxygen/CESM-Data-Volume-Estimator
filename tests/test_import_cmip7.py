"""Tests for tools/import_cmip7.py.

Runs entirely against tiny, inline, synthetic CSVs/YAML written to tmp_path
-- never against the real (local-only, not committed) reference/ data, so
these pass on a fresh clone with none of it present. See
notes/cmip7-request-tool-plan.md for the join rules being tested here.
"""

import csv
import textwrap

import pytest

import estimator
import tools.import_cmip7 as import_cmip7


# --- normalize_tokens: every shape seen in the real column ------------------

@pytest.mark.parametrize("raw,expected", [
    ("TREFHT", ["TREFHT"]),
    ("", []),
    ("N/A", []),
    ("n/a", []),
    ("num_a1, num_a2, num_a3", ["num_a1", "num_a2", "num_a3"]),
    ("CLD_CAL [COSP]", ["CLD_CAL"]),
    ("IWPMODIS [COSP]", ["IWPMODIS"]),
    ("O3:i", ["O3"]),
    ("O3:I", ["O3"]),
    ("SFbc_a4 + bc_a4_CLXF", ["SFbc_a4", "bc_a4_CLXF"]),
    ("A,,B", ["A", "B"]),            # a stray trailing comma, seen once in the real data
])
def test_normalize_tokens(raw, expected):
    assert import_cmip7.normalize_tokens(raw) == expected


# --- priority: Variable Group-MASTER joined to Priority Level-MASTER -------

def write_priority_csvs(tmp_path, monkeypatch):
    priority_csv = tmp_path / "Priority Level-MASTER.csv"
    priority_csv.write_text(textwrap.dedent("""\
        Name,Notes,Value,UID
        Core,,1,p1
        High,,2,p2
        Medium,,3,p3
        Low,,4,p4
        """))
    group_csv = tmp_path / "Variable Group-MASTER.csv"
    group_csv.write_text(textwrap.dedent("""\
        Name,Priority Level,UID
        grp_high,High,g1
        grp_low,Low,g2
        """))
    monkeypatch.setattr(import_cmip7, "PRIORITY_LEVEL_CSV", priority_csv)
    monkeypatch.setattr(import_cmip7, "VARIABLE_GROUP_CSV", group_csv)


def test_row_priority_takes_the_best_across_groups(tmp_path, monkeypatch):
    write_priority_csvs(tmp_path, monkeypatch)
    group_priorities = import_cmip7.load_group_priorities()
    assert group_priorities == {"grp_high": 2, "grp_low": 4}
    assert import_cmip7.row_priority(
        {"CMIP7 Variable Groups": "grp_low, grp_high"}, group_priorities) == 2
    assert import_cmip7.row_priority(
        {"CMIP7 Variable Groups": "grp_low"}, group_priorities) == 4
    assert import_cmip7.row_priority(
        {"CMIP7 Variable Groups": ""}, group_priorities) is None
    assert import_cmip7.row_priority(
        {"CMIP7 Variable Groups": "unknown_group"}, group_priorities) is None


def test_unknown_priority_level_raises(tmp_path, monkeypatch):
    (tmp_path / "Priority Level-MASTER.csv").write_text(
        "Name,Notes,Value,UID\nCore,,1,p1\n")
    (tmp_path / "Variable Group-MASTER.csv").write_text(
        "Name,Priority Level,UID\ngrp,Nonexistent,g1\n")
    monkeypatch.setattr(import_cmip7, "PRIORITY_LEVEL_CSV",
                         tmp_path / "Priority Level-MASTER.csv")
    monkeypatch.setattr(import_cmip7, "VARIABLE_GROUP_CSV",
                         tmp_path / "Variable Group-MASTER.csv")
    with pytest.raises(estimator.DataError, match="Nonexistent"):
        import_cmip7.load_group_priorities()


# --- realm-scoped catalogue lookup -------------------------------------------

def write_mini_catalogue(tmp_path, monkeypatch):
    """Six tiny component files, including a name (SST) that collides across
    atm and ocn under different physical meanings -- the real catalogue has
    8 of these, which is why the lookup must be realm-scoped, not global."""
    monkeypatch.setattr(estimator, "DATA", tmp_path)
    (tmp_path / "streams.yaml").write_text(
        "month_1: {samples_per_year: 12, label: monthly}\n")

    def write(name, horiz_dims, verified_default, variables):
        body = {"horiz_dims": horiz_dims, "verified": verified_default,
                "variables": variables}
        import yaml
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(body, sort_keys=False))

    write("atm", ["lat", "lon"], "unknown", [
        {"name": "TREFHT", "dims": ["time", "lat", "lon"], "streams": {"month_1": "std"}},
        {"name": "SST", "dims": ["time", "lat", "lon"], "streams": {"month_1": "std"}},
    ])
    write("lnd", ["lat", "lon"], "unknown", [
        {"name": "TSA", "dims": ["time", "lat", "lon"], "streams": {"month_1": "std"}},
    ])
    write("rof", ["lat", "lon"], "unknown", [
        {"name": "RIVER_DISCHARGE_OVER_LAND_LIQ", "dims": ["time", "lat", "lon"],
         "streams": {"month_1": "std"}},
    ])
    write("ocn", ["nlat", "nlon"], "cesm2-only", [
        {"name": "SST", "dims": ["time", "nlat", "nlon"], "streams": {"month_1": "std"}},
    ])
    write("ice", ["nj", "ni"], "unknown", [
        {"name": "aice", "dims": ["time", "nj", "ni"], "streams": {"month_1": "std"}},
    ])
    write("glc", ["y1", "x1"], "unknown", [
        {"name": "thickness", "dims": ["time", "y1", "x1"], "streams": {"month_1": "std"}},
    ])


def test_realm_scoping_disambiguates_a_colliding_name(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    catalogue, _ = estimator.load_catalogue()
    index = import_cmip7.index_catalogue(catalogue)
    assert import_cmip7.resolve_token("SST", "atmos", index) == ("atm", "unknown")
    assert import_cmip7.resolve_token("SST", "ocean", index) == ("ocn", "cesm2-only")


def test_land_realm_falls_back_to_rof(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    catalogue, _ = estimator.load_catalogue()
    index = import_cmip7.index_catalogue(catalogue)
    assert import_cmip7.resolve_token(
        "RIVER_DISCHARGE_OVER_LAND_LIQ", "land", index) == ("rof", "unknown")
    # TSA exists only in lnd -- still found via the same "land" realm.
    assert import_cmip7.resolve_token("TSA", "land", index) == ("lnd", "unknown")


def test_unmapped_realm_resolves_nothing(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    catalogue, _ = estimator.load_catalogue()
    index = import_cmip7.index_catalogue(catalogue)
    assert import_cmip7.resolve_token("TREFHT", "nonsense-realm", index) == (None, None)


# --- build_requests: end to end ---------------------------------------------

CESM3_FIELDS = ["CMIP7 Compound Name", "CESM Variable Name",
                "Modelling Realm - Primary", "CMIP7 Frequency",
                "CMIP7 Variable Groups"]


def write_cesm3_csv(tmp_path, rows):
    path = tmp_path / "CESM3_current.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CESM3_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_build_requests_end_to_end(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    write_priority_csvs(tmp_path, monkeypatch)
    csv_path = write_cesm3_csv(tmp_path, [
        {"CMIP7 Compound Name": "atmos.trefht.mon.glb",
         "CESM Variable Name": "TREFHT", "Modelling Realm - Primary": "atmos",
         "CMIP7 Frequency": "mon", "CMIP7 Variable Groups": "grp_high"},
        {"CMIP7 Compound Name": "atmos.partial.mon.glb",
         "CESM Variable Name": "TREFHT, GHOST_VAR",
         "Modelling Realm - Primary": "atmos",
         "CMIP7 Frequency": "mon", "CMIP7 Variable Groups": "grp_low"},
        {"CMIP7 Compound Name": "ocean.sst.mon.glb",
         "CESM Variable Name": "SST", "Modelling Realm - Primary": "ocean",
         "CMIP7 Frequency": "mon", "CMIP7 Variable Groups": ""},
        {"CMIP7 Compound Name": "land.norequest.mon.glb",
         "CESM Variable Name": "N/A", "Modelling Realm - Primary": "land",
         "CMIP7 Frequency": "mon", "CMIP7 Variable Groups": "grp_high"},
        {"CMIP7 Compound Name": "atmos.fixedfield.fx.glb",
         "CESM Variable Name": "TREFHT", "Modelling Realm - Primary": "atmos",
         "CMIP7 Frequency": "fx", "CMIP7 Variable Groups": "grp_high"},
    ])
    monkeypatch.setattr(import_cmip7, "CESM3_CSV", csv_path)

    requests = {r["name"]: r for r in import_cmip7.build_requests()}

    trefht = requests["atmos.trefht.mon.glb"]
    assert trefht["stream"] == "month_1"
    assert trefht["priority"] == 2
    assert trefht["tokens"] == [{"name": "TREFHT", "component": "atm", "verified": "unknown"}]

    partial = requests["atmos.partial.mon.glb"]
    assert partial["tokens"] == [
        {"name": "TREFHT", "component": "atm", "verified": "unknown"},
        {"name": "GHOST_VAR", "component": None, "verified": None},
    ]
    assert partial["priority"] == 4

    sst = requests["ocean.sst.mon.glb"]
    assert sst["tokens"] == [{"name": "SST", "component": "ocn", "verified": "cesm2-only"}]
    assert sst["priority"] is None

    unresolved = requests["land.norequest.mon.glb"]
    assert unresolved["tokens"] == []

    fixed = requests["atmos.fixedfield.fx.glb"]
    assert fixed["stream"] is None            # fx isn't modeled -- see question 3
    assert fixed["tokens"] == [{"name": "TREFHT", "component": "atm", "verified": "unknown"}]


# --- main(): skip gracefully, never error, when inputs are absent ----------

def test_main_skips_without_erroring_when_inputs_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(import_cmip7, "CESM3_CSV", tmp_path / "missing.csv")
    monkeypatch.setattr(import_cmip7, "VARIABLE_GROUP_CSV", tmp_path / "missing2.csv")
    monkeypatch.setattr(import_cmip7, "PRIORITY_LEVEL_CSV", tmp_path / "missing3.csv")
    output = tmp_path / "cmip7_request.yaml"
    monkeypatch.setattr(import_cmip7, "OUTPUT", output)

    import_cmip7.main()

    assert not output.exists()
    assert "skipping" in capsys.readouterr().out
