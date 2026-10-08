"""Tests for tools/extract_log_fields.py.

Every case here is a regression test for a real parsing bug found against
the actual logs in reference/log_files/ (not committed, not depended on
here): a component's units column containing a space, which breaks a
naive single-token split, and a component's table continuing to match
unrelated text later in a multi-megabyte log because nothing bounded where
the table ends. Both are expressed as tiny inline fixtures so they don't
need the real (local-only) log files to catch a regression.
"""

import textwrap

import tools.extract_log_fields as extract


# --- parse_master_field_list: atm's 5-column (rich) shape -------------------

def test_rich_entry_with_units():
    text = "  ******* MASTER FIELD LIST *******\n" + textwrap.dedent("""\
            1 PS                               Pa                  1 A  Surface pressure
        """)
    fields, names = extract.parse_master_field_list(text, "MASTER FIELD LIST")
    assert names == ["PS"]
    assert fields[0] == {"units": "Pa", "numlev": 1, "avgflag": "A",
                          "long_name": "Surface pressure"}


def test_rich_entry_without_units():
    """A field like `nu_kmvis` prints with an empty units column -- the
    units group must come back empty, not swallow the numlev digits."""
    text = "  ******* MASTER FIELD LIST *******\n" + textwrap.dedent("""\
            1 nu_kmvis                                            93 A  Molecular viscosity Laplacian coefficient
        """)
    fields, names = extract.parse_master_field_list(text, "MASTER FIELD LIST")
    assert names == ["nu_kmvis"]
    assert fields[0]["units"] == ""
    assert fields[0]["numlev"] == 93


def test_rich_entry_single_char_name_is_not_mistaken_for_numlev():
    """Regression: a one-character name like `T` followed by a wide units
    gap used to let the leading record index get matched as if it were the
    numlev/avgflag pair. Real line from atm.log.*."""
    text = "  ******* MASTER FIELD LIST *******\n" + \
        "  147 T                                K                  93 A  Temperature\n"
    fields, names = extract.parse_master_field_list(text, "MASTER FIELD LIST")
    assert names == ["T"]
    assert fields[0] == {"units": "K", "numlev": 93, "avgflag": "A",
                          "long_name": "Temperature"}


def test_rich_list_stops_at_first_blank_line():
    """Regression: without a stopping condition, unrelated text later in a
    multi-megabyte log that happens to fit the same shape gets counted as
    more fields."""
    text = "  ******* MASTER FIELD LIST *******\n" + textwrap.dedent("""\
            1 PS                               Pa                  1 A  Surface pressure

         some unrelated later diagnostic line that is not part of the table
        """)
    fields, names = extract.parse_master_field_list(text, "MASTER FIELD LIST")
    assert names == ["PS"]


# --- parse_master_field_list: lnd/rof's 2-column (plain) shape -------------

def test_plain_entry():
    text = "  ******* LIST OF ALL HISTORY FIELDS *******\n" + \
        "    1 LEAFCN                           gC/gN           \n"
    fields, names = extract.parse_master_field_list(
        text, "LIST OF ALL HISTORY FIELDS")
    assert names == ["LEAFCN"]
    assert fields[0]["units"] == "gC/gN"


def test_plain_entry_with_multiword_units():
    """Regression: CTSM's `P_AC` entry uses free text ("a fraction betwe...",
    itself truncated) in the units column instead of a real unit. A
    single-token split used to treat this as "doesn't match", which (via
    the stop-at-first-non-match rule) truncated the whole 1922-field list
    down to the first 20 entries."""
    text = "  ******* LIST OF ALL HISTORY FIELDS *******\n" + textwrap.dedent("""\
           20 TBUILD_MAX                       K
           21 P_AC                             a fraction betwe
           22 WIND                             m/s
        """)
    fields, names = extract.parse_master_field_list(
        text, "LIST OF ALL HISTORY FIELDS")
    assert names == ["TBUILD_MAX", "P_AC", "WIND"]
    assert fields[1]["units"] == "a fraction betwe"


def test_plain_list_marker_not_found_returns_empty():
    fields, names = extract.parse_master_field_list("no marker here", "MASTER FIELD LIST")
    assert fields == [] and names == []


# --- parse_cice_active_fields: fixed-width, not whitespace-delimited -------

def _cice_row(desc, units, name, freq="m"):
    """Build one 83-char fixed-width CICE table row the way the real log
    does, so tests exercise the same column boundaries the parser does."""
    return f"{desc:<43}{units:<18}{name:<13}{freq}       1"


def test_cice_table_basic():
    text = "will be written to the history tape: \n" + \
        "          description                     units             variable  frequency   x\n" + \
        _cice_row("grid cell mean ice thickness", "m", "hi") + "\n"
    fields, names = extract.parse_cice_active_fields(text)
    assert names == ["hi"]
    assert fields[0] == {"units": "m", "long_name": "grid cell mean ice thickness", "freq": "m"}


def test_cice_table_units_with_embedded_space():
    """Regression: `10^-6 m` as a unit has an internal space, which a
    whitespace-split (rather than fixed-width-column) parser cannot
    distinguish from the column boundary -- it silently dropped every row
    with this unit (23 of the real table's 122)."""
    text = "will be written to the history tape: \n" + \
        "          description                     units             variable  frequency   x\n" + \
        _cice_row("average snow grain radius, category", "10^-6 m", "rsnwn") + "\n"
    fields, names = extract.parse_cice_active_fields(text)
    assert names == ["rsnwn"]
    assert fields[0]["units"] == "10^-6 m"


def test_cice_table_stops_at_blank_line():
    """Regression: without this, per-timestep output elsewhere in a
    multi-megabyte ice.log that happens to look like a table row (it
    doesn't match this fixed-width shape, but a looser parser matched it
    anyway) got counted as history fields -- including literal date stamps."""
    text = "will be written to the history tape: \n" + \
        "          description                     units             variable  frequency   x\n" + \
        _cice_row("grid cell mean ice thickness", "m", "hi") + "\n" + \
        "\n" + \
        " dt  =    1800.00000000000\n"
    fields, names = extract.parse_cice_active_fields(text)
    assert names == ["hi"]


def test_cice_marker_not_found_returns_empty():
    fields, names = extract.parse_cice_active_fields("nothing relevant here")
    assert fields == [] and names == []


# --- flag_truncated ----------------------------------------------------------

def test_flag_truncated():
    names = ["SHORT", "A" * (extract.TRUNCATION_SUSPECT_LEN - 1),
              "B" * extract.TRUNCATION_SUSPECT_LEN]
    assert extract.flag_truncated(names) == ["B" * extract.TRUNCATION_SUSPECT_LEN]


# --- harvest_ocn_field_mentions ----------------------------------------------

def test_harvest_ocn_field_mentions_dedupes_and_matches_both_shapes():
    text = textwrap.dedent("""\
        WARNING from PE 0: diag_manager_mod::register_static_field: module/field ocean_model/geolat is STATIC.
        WARNING from PE 0: diag_manager_mod::register_static_field: module/field ocean_model/geolat is STATIC.
        WARNING from PE 0: diag_manager_mod::closing_file: module/output_field ocean_model/ALK_RIV_FLUX, skip.
        """)
    pairs = extract.harvest_ocn_field_mentions(text)
    assert pairs == [("ocean_model", "geolat"), ("ocean_model", "ALK_RIV_FLUX")]
