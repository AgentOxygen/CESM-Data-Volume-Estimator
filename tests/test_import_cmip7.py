"""Tests for tools/import_cmip7.py.

Runs entirely against tiny, inline, synthetic CSVs/YAML written to tmp_path
-- never against the real (local-only, not committed) reference/ data, so
these pass on a fresh clone with none of it present. See
notes/cmip7-request-tool-plan.md for the join rules being tested here.
"""

import csv
import textwrap

import pytest
import yaml

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


# --- resolve_mapping: status + component_source -----------------------------

def mini_indexes(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    catalogue, _ = estimator.load_catalogue()
    return import_cmip7.index_catalogue(catalogue)


LOG_INDEX = {"atm": {"TREFHT", "LOGGED_ONLY"}, "lnd": {"TREFHT", "TSA"}}


def test_logged_name_is_verified_and_component_comes_from_log(tmp_path, monkeypatch):
    cat = mini_indexes(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("LOGGED_ONLY", "atmos", LOG_INDEX, cat)
    assert (m["status"], m["component"], m["component_source"]) == ("verified", "atm", "log")
    assert m["realm_mismatch"] is False


def test_log_collision_prefers_the_realm_component_and_keeps_both(tmp_path, monkeypatch):
    cat = mini_indexes(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("TREFHT", "land", LOG_INDEX, cat)
    assert m["component"] == "lnd" and m["log_components"] == ["atm", "lnd"]


def test_log_beats_realm_and_flags_the_mismatch(tmp_path, monkeypatch):
    cat = mini_indexes(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("TSA", "atmos", LOG_INDEX, cat)
    assert (m["component"], m["component_source"]) == ("lnd", "log")
    assert m["realm_mismatch"] is True


def test_catalogue_only_match_is_cesm2(tmp_path, monkeypatch):
    cat = mini_indexes(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("SST", "ocean", LOG_INDEX, cat)
    assert (m["status"], m["component"], m["component_source"], m["catalogue_state"]) == \
        ("cesm2", "ocn", "catalogue", "cesm2-only")


def test_unknown_name_is_spreadsheet_only_with_realm_fallback(tmp_path, monkeypatch):
    cat = mini_indexes(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("GHOST", "landIce", LOG_INDEX, cat)
    assert (m["status"], m["component"], m["component_source"]) == \
        ("spreadsheet-only", "glc", "realm-fallback")


def test_every_realm_has_a_fallback_component():
    assert set(import_cmip7.REALM_FALLBACK) == set(import_cmip7.REALM_COMPONENTS)


# --- build_requests: end to end ---------------------------------------------

CESM3_FIELDS = ["CMIP7 Compound Name", "CESM Variable Name",
                "Modelling Realm - Primary", "CMIP7 Frequency",
                "CMIP7 Variable Groups", "List of Experiments", "UID"]


def write_cesm3_csv(tmp_path, rows):
    path = tmp_path / "CESM3_current.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CESM3_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_log_yaml(tmp_path, monkeypatch):
    path = tmp_path / "extracted_fields.yaml"
    path.write_text(yaml.safe_dump({
        "atm": {"matched": [{"name": "TREFHT"}], "new": [{"name": "LOGGED_ONLY"}]}}))
    monkeypatch.setattr(import_cmip7, "LOG_FIELDS_YAML", path)


def row(name, raw, realm="atmos", freq="mon", groups="grp_high",
        experiments="historical,piControl", uid="u"):
    return {"CMIP7 Compound Name": name, "CESM Variable Name": raw,
            "Modelling Realm - Primary": realm, "CMIP7 Frequency": freq,
            "CMIP7 Variable Groups": groups, "List of Experiments": experiments,
            "UID": uid}


def test_build_requests_end_to_end(tmp_path, monkeypatch):
    write_mini_catalogue(tmp_path, monkeypatch)
    write_priority_csvs(tmp_path, monkeypatch)
    write_log_yaml(tmp_path, monkeypatch)
    monkeypatch.setattr(import_cmip7, "CESM3_CSV", write_cesm3_csv(tmp_path, [
        row("a.trefht", "TREFHT", experiments="historical, piControl, historical"),
        row("a.partial", "TREFHT, GHOST_VAR", groups="grp_low", experiments="amip"),
        row("o.sst", "SST", realm="ocean", groups="", experiments="historical"),
        row("l.none", "N/A", realm="land"),
        row("a.fixed", "TREFHT", freq="fx"),
    ]))

    requests, experiments = import_cmip7.build_requests()
    by_name = {r["name"]: r for r in requests}

    trefht = by_name["a.trefht"]
    assert trefht["stream"] == "month_1" and trefht["priority"] == 2
    assert trefht["raw_cesm_name"] == "TREFHT" and trefht["groups"] == ["grp_high"]
    assert trefht["source_line"] == 2 and by_name["a.partial"]["source_line"] == 3
    assert [(t["name"], t["status"]) for t in trefht["tokens"]] == [("TREFHT", "verified")]

    partial = by_name["a.partial"]
    assert [(t["name"], t["status"], t["component_source"]) for t in partial["tokens"]] == [
        ("TREFHT", "verified", "log"), ("GHOST_VAR", "spreadsheet-only", "realm-fallback")]
    assert partial["priority"] == 4

    sst = by_name["o.sst"]
    assert sst["tokens"][0]["status"] == "cesm2" and sst["priority"] is None

    none = by_name["l.none"]
    assert none["tokens"] == [] and none["fallback_component"] == "lnd"

    assert by_name["a.fixed"]["stream"] is None      # fx isn't modeled

    # experiment -> request indices, de-duplicated per request
    assert experiments["historical"] == [0, 2, 3, 4]
    assert experiments["piControl"] == [0, 3, 4]
    assert experiments["amip"] == [1]


# --- main(): skip gracefully, never error, when inputs are absent ----------

def test_main_skips_without_erroring_when_inputs_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(import_cmip7, "CESM3_CSV", tmp_path / "missing.csv")
    monkeypatch.setattr(import_cmip7, "VARIABLE_GROUP_CSV", tmp_path / "missing2.csv")
    monkeypatch.setattr(import_cmip7, "PRIORITY_LEVEL_CSV", tmp_path / "missing3.csv")
    monkeypatch.setattr(import_cmip7, "LOG_FIELDS_YAML", tmp_path / "missing4.yaml")
    output = tmp_path / "cmip7_request.yaml"
    monkeypatch.setattr(import_cmip7, "OUTPUT", output)

    import_cmip7.main()

    assert not output.exists()
    assert "skipping" in capsys.readouterr().out


# --- the committed data/cmip7_request.yaml must match its real inputs ------

@pytest.mark.skipif(
    not (import_cmip7.CESM3_CSV.exists() and import_cmip7.VARIABLE_GROUP_CSV.exists()
         and import_cmip7.PRIORITY_LEVEL_CSV.exists()
         and import_cmip7.LOG_FIELDS_YAML.exists()),
    reason="reference/ CMIP7 CSVs are local-only -- skip where they're absent")
def test_committed_bundle_is_not_stale():
    """Catches "the catalogue's verified: tags changed, forgot to
    regenerate" -- same failure mode `estimator.py`'s own
    test_bundle_is_not_stale guards against for docs/data.json. This is
    exactly how data/cmip7_request.yaml went stale once already: applying
    tools/apply_verified_tags.py changed data/*.yaml without re-running
    `make import-cmip7`."""
    current = import_cmip7.render(*import_cmip7.build_requests())
    assert current == import_cmip7.OUTPUT.read_text(), (
        "data/cmip7_request.yaml is out of date -- run `make import-cmip7` "
        "and commit the result.")
