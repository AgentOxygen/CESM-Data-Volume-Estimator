"""cesm_fields.fortran: statements, call arguments, literals, name expansion."""

import textwrap

import pytest

from cesm_fields import fortran
from cesm_fields.fortran import Expr


def stmts(src):
    return list(fortran.statements(textwrap.dedent(src)))


def one_call(src, name):
    (call,) = [c for line, text in stmts(src) for c in fortran.find_calls(line, text, name)]
    return call


def test_continuations_comments_and_ifdefs():
    s = stmts("""
        #ifdef FOO
        call addfld('T', (/ 'lev' /), &   ! comment after an unclosed paren
             & 'A!', 'K', &
             'Temperature')
        #endif
        """)
    assert s == [(3, "call addfld('T', (/ 'lev' /), 'A!', 'K', 'Temperature')")]


def test_call_arguments():
    c = one_call("call addfld(trim(btndname(i, j))//'ND', (/'lev'/), 'A', type1d_out==namel, GridName='GLL')", "addfld")
    assert c.args == ["trim(btndname(i, j))//'ND'", "(/'lev'/)", "'A'", "type1d_out==namel"]
    assert c.kw == {"gridname": "'GLL'"}


def test_function_form_found_definitions_and_suffixes_skipped():
    assert one_call("id = register_diag_field('ocean_model', 'u', axes)", "register_diag_field").args[1] == "'u'"
    for src in ["integer function register_diag_field(a, b)", "call myaddfld('x')", "call obj%addfld('x')"]:
        name = "register_diag_field" if "register" in src else "addfld"
        assert [c for line, text in stmts(src) for c in fortran.find_calls(line, text, name)] == []


@pytest.mark.parametrize("text,expected", [
    ("'T'", "T"), ("'it''s'", "it's"), ("'ABC'//'_D'", "ABC_D"), ("trim('X')", "X"),
    ("cnst_name(m)", Expr("cnst_name(m)")),
])
def test_literal(text, expected):
    assert fortran.literal(text) == expected


def test_name_and_lists():
    assert fortran.name("'AEROD_v '") == "AEROD_v"
    assert fortran.literal_list("(/ 'lev' /)") == ["lev"]
    assert fortran.literal_list("['cosp_tau', 'cosp_prs']") == ["cosp_tau", "cosp_prs"]
    assert fortran.literal_list("dimnames") == Expr("dimnames")


def test_expand():
    env = fortran.assignments(stmts("""
        character(len=*), parameter :: vr_suffix = "_vr"
        sfx = "_1m"
        """))
    known = {"cnst_name": ["Q", "O3"]}
    assert fortran.expand("'ABSORB'//diag(ilist)", env) == ["ABSORB*"]
    assert fortran.expand("trim(fieldname)//trim(vr_suffix)", env) == ["*_vr"]
    assert fortran.expand("'SOIL'//sfx", env) == ["SOIL_1m"]
    assert fortran.expand("'SF'//trim(cnst_name(m))", env, known) == ["SFO3", "SFQ"]
    assert fortran.expand("cnst_name(m)//x", env) == ["*"]
