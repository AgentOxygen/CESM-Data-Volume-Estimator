"""cesm_fields.flow: namelist defaults, guard evaluation, and which registrations are dead."""

import textwrap

from cesm_fields import flow

VALUES = {"macrop_scheme": "clubb_sgs", "do_clubb_sgs": True, "n": 3}


def test_evaluate_is_three_valued_and_case_blind():
    ev = lambda t: flow.evaluate(t, VALUES)
    assert ev("macrop_scheme == 'CLUBB_SGS'") is True
    assert ev("macrop_scheme /= 'rk' .and. do_clubb_sgs") is True
    assert ev(".not. do_clubb_sgs") is False
    assert ev("mystery_flag") is flow.UNKNOWN
    assert ev("mystery_flag .and. .not. do_clubb_sgs") is False      # False wins
    assert ev("mystery_flag .or. do_clubb_sgs") is True              # True wins
    assert ev("trim(macrop_scheme) == 'clubb_sgs'") is True
    assert ev("f(x) > 2") is flow.UNKNOWN


def test_namelist_values_most_specific_entry_wins(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text("""<namelist_defaults>
        <macrop_scheme                      >none</macrop_scheme>
        <macrop_scheme macrophys="rk"       >rk</macrop_scheme>
        <macrop_scheme macrophys="clubb_sgs">CLUBB_SGS</macrop_scheme>
        <do_clubb_sgs clubb_sgs="1"         >.true.</do_clubb_sgs>
        <n_steps                            > 5 </n_steps>
        </namelist_defaults>""")
    v = flow.namelist_values(xml, {"macrophys": "clubb_sgs", "clubb_sgs": "1"})
    assert v == {"macrop_scheme": "clubb_sgs", "do_clubb_sgs": True, "n_steps": 5}
    assert flow.namelist_values(xml, {})["macrop_scheme"] == "none"


def test_dead_lines_guards_calls_and_derived_flags(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.F90").write_text(textwrap.dedent("""
        subroutine top_init()
          is_clubb = macrop_scheme == 'CLUBB_SGS'
          use_default = .false.
          call live_init()
          if (macrop_scheme == 'rk') call rk_init()
          if (.not. is_clubb) then
             call addfld('NOT_CLUBB', horiz_only, 'A', 'x', 'y')
          else
             call addfld('CLUBB_ONLY', horiz_only, 'A', 'x', 'y')
          end if
          if (use_default) call addfld('DEFAULT_FLAG', horiz_only, 'A', 'x', 'y')   ! a namelist read may set it: stays live
          select case (macrop_scheme)
          case ('park')
             call addfld('PARK', horiz_only, 'A', 'x', 'y')
          case default
             call addfld('OTHER', horiz_only, 'A', 'x', 'y')
          end select
        end subroutine top_init
        subroutine live_init()
          call addfld('LIVE', horiz_only, 'A', 'x', 'y')
        end subroutine live_init
        subroutine rk_init()
          call addfld('RK', horiz_only, 'A', 'x', 'y')
        end subroutine rk_init
        """))
    dead = flow.dead_lines(tmp_path, ["src/a.F90"], VALUES | {"macrop_scheme": "clubb_sgs"})["src/a.F90"]
    text = (src / "a.F90").read_text().splitlines()
    gone = {l.split("'")[1] for n, l in enumerate(text, 1) if "addfld" in l and n in dead}
    assert gone == {"NOT_CLUBB", "PARK", "RK"}                       # CLUBB_ONLY, OTHER, LIVE, DEFAULT_FLAG stay


def test_ccpp_scheme_not_in_suite_is_off(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "suite.xml").write_text("<suite><scheme>zm_diagnostics</scheme></suite>")
    for stem in ("zm_diagnostics", "rk_diagnostics"):
        (tmp_path / "s" / f"{stem}.F90").write_text("")
        (tmp_path / "s" / f"{stem}.meta").write_text(f"[ccpp-table-properties]\n  name = {stem}\n")
    assert flow.ccpp_schemes_off(tmp_path, ["s/zm_diagnostics.F90", "s/rk_diagnostics.F90"], "suite.xml") == {"s/rk_diagnostics.F90"}
