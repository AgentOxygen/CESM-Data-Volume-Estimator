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
    with pytest.raises(import_cmip7.DataError, match="Nonexistent"):
        import_cmip7.load_group_priorities()


# --- resolve_mapping: status + component_source -----------------------------

LOG_INDEX = {"atm": {"TREFHT", "LOGGED_ONLY"}, "lnd": {"TREFHT", "TSA"}}


def test_logged_name_is_verified_and_component_comes_from_log():
    m = import_cmip7.resolve_mapping("LOGGED_ONLY", "atmos", LOG_INDEX)
    assert (m["status"], m["component"], m["component_source"]) == ("verified", "atm", "log")
    assert m["realm_mismatch"] is False


def test_log_collision_prefers_the_realm_component_and_keeps_both():
    m = import_cmip7.resolve_mapping("TREFHT", "land", LOG_INDEX)
    assert m["component"] == "lnd" and m["log_components"] == ["atm", "lnd"]


def test_log_beats_realm_and_flags_the_mismatch():
    m = import_cmip7.resolve_mapping("TSA", "atmos", LOG_INDEX)
    assert (m["component"], m["component_source"]) == ("lnd", "log")
    assert m["realm_mismatch"] is True


def test_unknown_name_is_spreadsheet_only_with_realm_fallback():
    m = import_cmip7.resolve_mapping("GHOST", "landIce", LOG_INDEX)
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
        "atm": {"fields": [{"name": "TREFHT"}, {"name": "LOGGED_ONLY"}]}}))
    monkeypatch.setattr(import_cmip7, "LOG_FIELDS_YAML", path)


def row(name, raw, realm="atmos", freq="mon", groups="grp_high",
        experiments="historical,piControl", uid="u", branding="tavg"):
    return {"CMIP7 Compound Name": f"{realm}.{name}.{branding}-u-hxy-u.{freq}.glb", "CESM Variable Name": raw,
            "Modelling Realm - Primary": realm, "CMIP7 Frequency": freq,
            "CMIP7 Variable Groups": groups, "List of Experiments": experiments,
            "UID": uid}


def test_build_requests_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(import_cmip7, "SCRAPER", tmp_path / "no-scraper")      # statuses from the log alone
    monkeypatch.setattr(import_cmip7, "ALIASES_YAML", tmp_path / "no-aliases.yaml")
    write_priority_csvs(tmp_path, monkeypatch)
    write_log_yaml(tmp_path, monkeypatch)
    monkeypatch.setattr(import_cmip7, "CESM3_CSV", write_cesm3_csv(tmp_path, [
        row("trefht", "TREFHT", branding="tpt", experiments="historical, piControl, historical"),
        row("partial", "TREFHT, GHOST_VAR", groups="grp_low", experiments="amip"),
        row("sst", "SST", realm="ocean", groups="", experiments="historical"),
        row("none", "N/A", realm="land"),
        row("fixed", "TREFHT", freq="fx"),
    ]))

    requests, experiments = import_cmip7.build_requests()
    by_name = {r["name"].split(".")[1]: r for r in requests}

    trefht = by_name["trefht"]
    assert trefht["stream"] == "month_1" and trefht["priority"] == 2
    assert trefht["raw_cesm_name"] == "TREFHT" and trefht["groups"] == ["grp_high"]
    assert trefht["source_line"] == 2 and by_name["partial"]["source_line"] == 3
    assert [(t["name"], t["status"]) for t in trefht["tokens"]] == [("TREFHT", "verified")]

    partial = by_name["partial"]
    assert [(t["name"], t["status"], t["component_source"]) for t in partial["tokens"]] == [
        ("TREFHT", "verified", "log"), ("GHOST_VAR", "spreadsheet-only", "realm-fallback")]
    assert partial["priority"] == 4

    sst = by_name["sst"]
    assert sst["tokens"][0]["status"] == "spreadsheet-only" and sst["priority"] is None

    none = by_name["none"]
    assert none["tokens"] == [] and none["fallback_component"] == "lnd"

    assert by_name["fixed"]["stream"] is None      # fx isn't modeled

    # experiment -> request indices, de-duplicated per request
    assert trefht["time_method"] == "tpt"
    assert [(t["method"], t["method_source"]) for t in trefht["tokens"]] == [("I", "compound-name")]
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
    """Catches "the evidence the statuses rest on changed (logs, aliases, source
    catalogue), forgot to regenerate" -- the same failure mode
    test_bundle_is_not_stale guards against for docs/data.json."""
    current = import_cmip7.render(*import_cmip7.build_requests(), import_cmip7.source_configuration())
    assert current == import_cmip7.OUTPUT.read_text(), (
        "data/cmip7_request.yaml is out of date -- run `make import-cmip7` "
        "and commit the result.")


# --- time method: CMIP7 branding -> CESM averaging flag -----------------------

@pytest.mark.parametrize("branding,flag", [
    ("tavg", "A"), ("tpt", "I"), ("tmax", "X"), ("tmin", "M"), ("tsum", "SUM"),
    ("ti", None), ("tclm", "A"), ("tmaxavg", "X"), ("tminavg", "M")])
def test_time_method_flags(branding, flag):
    name = f"atmos.tas.{branding}-h2m-hxy-u.day.glb"
    assert import_cmip7.time_method(name)[1] == flag


def test_every_derived_method_carries_its_caveat():
    for prefix in ("tclm", "tclmdc", "tmaxavg", "tminavg", "ti"):
        assert import_cmip7.TIME_METHODS[prefix][1]
    for prefix in ("tavg", "tpt", "tmax", "tmin", "tsum"):
        assert import_cmip7.TIME_METHODS[prefix][1] is None


def test_explicit_cesm_name_suffix_overrides_the_derived_method():
    assert import_cmip7.split_tokens("O3:i, T") == [("O3", "I"), ("T", None)]


# --- source evidence + aliases -------------------------------------------------

def write_scraper(tmp_path):
    """A tiny cesm-field-scraper tree: one configuration, atm + ice records of every kind."""
    root = tmp_path / "scraper"
    (root / "out").mkdir(parents=True)
    (root / "configurations.yaml").write_text(yaml.safe_dump({"CFG": {"scam": False, "cism": False}}))
    def rec(name, **kw):
        return {"name": name, "dims": ["lev"], "horizontal": "physgrid", "source": f"src/x.F90:{kw.pop('line', 1)}", **kw}
    (root / "out" / "atm.yaml").write_text(yaml.safe_dump({"fields": [
        rec("LITERAL_SRC"), rec("LOOP_SRC", alternatives=154), rec("LOOP_SRC", line=9),
        rec("SCAM_ONLY", requires={"scam": [True]}), rec(None, name_patterns=["AOD*"]),
        rec("IN_BOTH")]}))
    (root / "out" / "ice.yaml").write_text(yaml.safe_dump({"fields": [rec("siage")]}))
    return root


def source_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(import_cmip7, "SCRAPER", write_scraper(tmp_path))
    monkeypatch.setattr(import_cmip7, "SOURCE_CONFIG", "CFG")
    return import_cmip7.load_source_index()


def test_source_index_applies_configuration_and_prefers_literal(tmp_path, monkeypatch):
    idx = source_setup(tmp_path, monkeypatch)["atm"]
    assert "SCAM_ONLY" not in idx["exact"]                              # needs scam; the configuration has it off
    assert idx["exact"]["LOOP_SRC"] == ("literal", "src/x.F90:9", ["lev"], "physgrid")   # the literal record beats the expanded one
    assert idx["patterns"] == [("AOD*", "src/x.F90:1")]


def test_source_index_is_none_without_scraper_output(tmp_path, monkeypatch):
    monkeypatch.setattr(import_cmip7, "SCRAPER", tmp_path / "nothing")
    assert import_cmip7.load_source_index() is None and import_cmip7.source_configuration() is None


def test_status_source_sits_between_verified_and_spreadsheet_only(tmp_path, monkeypatch):
    idx = source_setup(tmp_path, monkeypatch)
    log = {"atm": {"IN_BOTH"}}
    r = lambda n: import_cmip7.resolve_mapping(n, "atmos", log, idx)
    assert r("IN_BOTH")["status"] == "verified" and r("IN_BOTH")["component_source"] == "log"
    lit, loop, pat = r("LITERAL_SRC"), r("LOOP_SRC"), r("AODDUST01")
    assert (lit["status"], lit["component_source"], lit["source_certainty"], lit["source_ref"]) == ("source", "source", "literal", "src/x.F90:1")
    assert loop["source_certainty"] == "literal"                          # via the literal record
    assert (pat["status"], pat["source_certainty"]) == ("source", "pattern")
    assert r("NOWHERE")["status"] == "spreadsheet-only"


def test_daily_suffix_and_reviewed_aliases(tmp_path, monkeypatch):
    idx = source_setup(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("siage_d", "seaIce", {}, idx)
    assert (m["status"], m["alias_of"], m["component"]) == ("source", "siage", "ice")
    m = import_cmip7.resolve_mapping("renamed", "seaIce", {}, idx, aliases={"renamed": "siage"})
    assert (m["status"], m["alias_of"]) == ("source", "siage")
    # a name with its own evidence is never aliased
    assert import_cmip7.resolve_mapping("siage", "seaIce", {}, idx)["alias_of"] is None
    # nothing found anywhere stays spreadsheet-only
    assert import_cmip7.resolve_mapping("nope_d", "seaIce", {}, idx)["status"] == "spreadsheet-only"


def test_token_carries_the_source_dims_even_when_the_log_decides_the_status(tmp_path, monkeypatch):
    idx = source_setup(tmp_path, monkeypatch)
    m = import_cmip7.resolve_mapping("IN_BOTH", "atmos", {"atm": {"IN_BOTH"}}, idx)
    assert m["status"] == "verified" and (m["dims"], m["horizontal"]) == (["lev"], "physgrid")
