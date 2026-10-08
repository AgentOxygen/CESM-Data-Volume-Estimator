"""Tests for tools/apply_verified_tags.py.

Everything here runs against a tiny synthetic data/atm.yaml written to
tmp_path -- never the real catalogue -- so these catch a regression
without risking a bad edit to the hand-maintained files.
"""

import textwrap

import tools.apply_verified_tags as apply_verified


ATM_YAML = textwrap.dedent("""\
    horiz_dims: [lat, lon]
    dtype_bytes: 4
    verified: unknown

    variables:
    - name: PS
      dims: [time, lat, lon]
      streams: {month_1: std}
      long_name: Surface pressure
      units: Pa
    - name: T
      dims: [time, lev, lat, lon]
      streams: {month_1: std}
      long_name: Temperature
      units: K
    - name: TSA
      dims: [time, lat, lon]
      streams: {month_1: std}
    - name: TSA
      dims: [time, pft]
      streams: {month_1: std}
    - name: ALREADY_TAGGED
      dims: [time, lat, lon]
      streams: {month_1: std}
      verified: cesm2-only
    """)


def write_atm(tmp_path, body=ATM_YAML):
    path = tmp_path / "atm.yaml"
    path.write_text(body)
    return path


def test_adds_verified_to_matching_record(tmp_path):
    path = write_atm(tmp_path)
    touched = apply_verified.add_verified_cesm3(path, {"PS"})
    assert touched == ["PS"]
    text = path.read_text()
    assert "- name: PS\n  verified: cesm3\n  dims:" in text
    # T wasn't in the requested set -- untouched.
    assert "- name: T\n  dims:" in text


def test_both_dims_variants_of_a_name_get_tagged(tmp_path):
    path = write_atm(tmp_path)
    touched = apply_verified.add_verified_cesm3(path, {"TSA"})
    assert touched == ["TSA", "TSA"]
    assert path.read_text().count("verified: cesm3") == 2


def test_existing_per_variable_override_is_never_clobbered(tmp_path):
    path = write_atm(tmp_path)
    touched = apply_verified.add_verified_cesm3(path, {"ALREADY_TAGGED"})
    assert touched == []
    text = path.read_text()
    assert "verified: cesm2-only" in text
    assert "verified: cesm3" not in text


def test_idempotent_on_a_second_run(tmp_path):
    path = write_atm(tmp_path)
    apply_verified.add_verified_cesm3(path, {"PS"})
    touched_again = apply_verified.add_verified_cesm3(path, {"PS"})
    assert touched_again == []
    assert path.read_text().count("verified: cesm3") == 1


def test_only_other_records_are_byte_for_byte_unchanged(tmp_path):
    path = write_atm(tmp_path)
    apply_verified.add_verified_cesm3(path, {"PS"})
    text = path.read_text()
    assert "- name: T\n  dims: [time, lev, lat, lon]\n  streams: {month_1: std}\n  long_name: Temperature\n  units: K\n" in text


# --- matched_names ------------------------------------------------------

def test_matched_names_reads_the_matched_list():
    extracted = {"atm": {"kind": "master_field_list",
                          "matched": [{"name": "PS", "units": "Pa"},
                                      {"name": "T", "units": "K"}],
                          "new": [{"name": "XYZ"}]}}
    assert apply_verified.matched_names(extracted, "atm") == {"PS", "T"}


def test_matched_names_missing_component_is_empty():
    assert apply_verified.matched_names({}, "atm") == set()


# --- ocn exclusion is a decision, not an accident ---------------------

def test_ocn_is_never_in_the_component_list():
    assert "ocn" not in apply_verified.COMPONENTS
