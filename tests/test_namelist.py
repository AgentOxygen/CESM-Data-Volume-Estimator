"""Drives docs/namelist.js under node (skipped where node is absent)."""
import json, shutil, subprocess
from pathlib import Path
import pytest

JS = Path(__file__).resolve().parents[1] / "docs" / "namelist.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def build(comp, rows):
    rows = [{"items": [], "method": None, **r} for r in rows]
    code = f"console.log(JSON.stringify(require({json.dumps(str(JS))}).build({json.dumps(comp)}, {json.dumps(rows)})))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


def test_cam_tapes_ordered_and_flagged():
    out = build("atm", [{"name": "T", "freq": "day", "method": "A"},
                        {"name": "PRECT", "freq": "mon", "method": "A"},
                        {"name": "TREFHTMX", "freq": "day", "method": "X"}])
    t = out["text"]
    assert " empty_htapes = .true." in t and " nhtfrq = 0, -24\n" in t and " mfilt = 1, 30\n" in t
    assert " fincl1 = 'PRECT:A'\n" in t
    assert " fincl2 = 'T:A',\n    'TREFHTMX:X'\n" in t


def test_same_name_two_methods_split_tapes():
    out = build("atm", [{"name": "T", "freq": "day", "method": "A"}, {"name": "T", "freq": "day", "method": "X"}])
    assert len(out["tapes"]) == 2 and " nhtfrq = -24, -24\n" in out["text"]


def test_ctsm_prefix_sum_and_dov2xy():
    out = build("lnd", [{"name": "QFLX", "freq": "mon", "method": "SUM"}])
    t = out["text"]
    assert " hist_empty_htapes = .true." in t and " hist_dov2xy = .true.\n" in t and " hist_fincl1 = 'QFLX:SUM'\n" in t


def test_dropped_not_exported():
    out = build("atm", [{"name": "T", "freq": "mon", "method": "SUM"},        # SUM invalid in CAM
                        {"name": "X" * 33, "freq": "mon"},                    # too long
                        {"name": "AREA", "freq": "fx"}])                      # no history setting
    assert len(out["dropped"]) == 3 and "(nothing to export)" in out["text"]


def test_tape_budget_refused():
    rows = [{"name": "T", "freq": "mon", "method": m} for m in "AIMXBLNS"] + \
           [{"name": "T", "freq": "day", "method": m} for m in "AIM"]
    assert "allows 10" in build("atm", rows)["error"]


def test_header_carries_generation_date():
    import re
    assert re.match(r"! Generated \d{4}-\d{2}-\d{2} by the CESM Data Volume Estimator", build("atm", [])["text"])


def run(expr):
    code = f"const N=require({json.dumps(str(JS))}); console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


def test_mosart_additive_and_three_tape_limit():
    out = build("rof", [{"name": "RIVER_DISCHARGE_OVER_LAND_LIQ", "freq": "day", "method": "A"}])
    assert "ADDED to the model's default" in out["text"] and "empty_htapes = .true." not in out["text"]
    assert " fincl1 = 'RIVER_DISCHARGE_OVER_LAND_LIQ:A'\n" in out["text"]
    many = [{"name": "Q", "freq": f} for f in ("mon", "day", "6hr", "3hr")]
    assert "allows 3" in build("rof", many)["error"]


def test_cism_coarsest_default_and_variants():
    out = build("glc", [{"name": "thk", "freq": "yr"}, {"name": "topg", "freq": "dec"}, {"name": "smb", "freq": "mon"}])
    assert " esm_history_vars = 'topg'\n" in out["text"] and " history_frequency = 10\n" in out["text"]
    assert [v["freq"] for v in out["variants"]] == ["yr"] and " esm_history_vars = 'thk'\n" in out["variants"][0]["text"]
    assert [d["name"] for d in out["dropped"]] == ["smb"]            # monthly is not expressible


def test_zip_is_valid_and_round_trips(tmp_path):
    files = [{"name": "user_nl_cam", "text": "a = 1\n"}, {"name": "variants/x", "text": "é\n"}]
    data = bytes(run(f"Array.from(N.zip({json.dumps(files)}))"))
    import zipfile, io
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None and z.namelist() == ["user_nl_cam", "variants/x"]
    assert z.read("variants/x").decode() == "é\n"


ICE = ["aice", "siage", "sidconcdyn"]


def build_ice(rows):
    code = f"console.log(JSON.stringify(require({json.dumps(str(JS))}).build('ice', {json.dumps([{'items': [], 'method': None, **r} for r in rows])}, {{iceFields: {json.dumps(ICE)}}})))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


def test_cice_masks_streams_and_alias():
    t = build_ice([{"name": "aice", "freq": "mon"}, {"name": "aice", "freq": "day"}, {"name": "siage_d", "freq": "day"},
                   {"name": "nonsense", "freq": "mon"}])["text"]
    assert " histfreq = 'm', 'd', 'x', 'x', 'x'\n" in t and " histfreq_n = 1, 1, 0, 0, 0\n" in t
    assert " f_aice = 'md'\n" in t and " f_siage = 'd'\n" in t
    assert "not exported: nonsense (mon)" in t


def test_cice_shared_letter_drops_finer_stream():
    out = build_ice([{"name": "aice", "freq": "6hr"}, {"name": "siage", "freq": "1hr"}])
    assert " histfreq = 'h', 'x'" in out["text"] and " histfreq_n = 6, 0" in out["text"]
    assert [d["name"] for d in out["dropped"]] == ["siage"]


def test_mom6_diag_table_modules_reductions_and_aliases():
    rows = [{"items": [], "method": m, "name": n, "freq": f} for n, f, m in
            [("thetao", "mon", "A"), ("tos", "mon", "A"), ("tos", "mon", "X"), ("so", "day", "I"), ("mystery", "mon", "A")]]
    meta = {"momFields": {"ocean_model": ["tos"], "ocean_model_z": ["thetao", "so"]}}
    code = f"console.log(JSON.stringify(require({json.dumps(str(JS))}).build('ocn', {json.dumps(rows)}, {json.dumps(meta)})))"
    t = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)["text"]
    assert '"ocean_model_z", "thetao", "thetao", "${CASE}.mom6.h.mon.z.%4yr-%2mo", "all", "mean", "none", 2' in t
    assert '"ocean_model", "tos", "tos_max", "${CASE}.mom6.h.mon.native.%4yr-%2mo", "all", "max", "none", 2' in t
    assert '"ocean_model_z", "so", "so_inst"' in t and '"ocean_model", "mystery", "mystery"' in t
    assert '"${CASE}.mom6.h.day.z.%4yr-%2mo", 1, "days", 1, "days", "time", 1, "months"' in t


def test_header_reports_source_only_and_unevidenced_lines():
    code = (f"console.log(JSON.stringify(require({json.dumps(str(JS))}).build('atm', "
            f"[{{name:'T',freq:'mon',method:'A',items:[]}}], {{unverified: 2, sourceOnly: 5, sourceConfiguration: 'CFG'}})))")
    t = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)["text"]
    assert "2 line(s) have no CESM3 source or run-log evidence" in t
    assert "5 line(s) are registered by the CESM3 source for CFG but were not seen in a run log" in t
