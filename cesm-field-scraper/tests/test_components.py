"""Each component scraper against a tiny synthetic tree, copying real
cesm3_0_alpha09e call-site shapes."""

import textwrap

from cesm_fields.components import cam, cice, cism, ctsm, mom6, mosart


def write(root, rel, text):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(textwrap.dedent(text))


def by_name(records):
    return {r["name"] or r["name_expr"]: r for r in records}


def test_cam(tmp_path):
    root = tmp_path / cam.REPO_PATH
    write(root, cam.CONSTITUENT_ARRAYS[0][0], """
        character(len=8), parameter :: &
           cnst_names(2) = (/'CLDLIQ', 'CLDICE'/)
        """)
    write(root, cam.CONSTITUENT_ARRAYS[1][0], "solsym(: 1) = (/ 'SO2             ' /)\n")
    write(root, "src/physics/cam/constituents.F90", "sflxnam(m) = 'SF'//cnst_name(m)\n")
    write(root, "src/physics/cam/diag.F90", """
        call addfld('T', (/ 'lev' /), 'A', 'K', 'Temperature')
        call addfld ('PS', horiz_only, 'A', 'Pa', 'Surface pressure', gridname='GLL')
        call addfld('Z3', 'lev', 'A', 'm', 'Geopotential')
        call addfld('ABSORB'//diag(ilist), (/ 'lev' /), 'A', '/m', 'Aerosol absorption')
        call addfld('DIVT', (/ 'lev' /), 'A', 'K/s', 'x', gridname=trim(outgrid))
        call addfld(sflxnam(m), horiz_only, 'A', 'kg/m2/s', 'surface flux')
        call history_add_field('HR', 'Heating rate', 'lev', 'avg', 'K s-1')
        """)
    r = by_name(cam.scrape(root))
    assert r["T"]["dims"] == ["lev"] and r["T"]["horizontal"] == "physgrid"
    assert r["T"]["source"] == "src/physics/cam/diag.F90:2"
    assert r["PS"]["dims"] == [] and r["PS"]["horizontal"] == "GLL"
    assert r["Z3"]["dims"] == ["lev"]
    assert r["'ABSORB'//diag(ilist)"]["name_patterns"] == ["ABSORB*"]
    assert r["DIVT"]["horizontal"] is None
    assert {"SFQ", "SFCLDLIQ", "SFCLDICE", "SFSO2"} <= set(r)
    assert r["SFSO2"]["name_expr"] == "sflxnam(m)" and r["SFSO2"]["dims"] == []
    assert r["HR"]["registrar"] == "history_add_field"


def test_ctsm(tmp_path):
    root = tmp_path / ctsm.REPO_PATH
    write(root, "src/biogeophys/SoilStateType.F90", """
        call hist_addfld2d (fname='SMP',  units='mm', type2d='levgrnd',  &
             avgflag='A', long_name='soil matric potential', ptr_col=this%smp_l_col)
        call hist_addfld1d (fname='KROOT', units='1/s', avgflag='A', &
             long_name='x', ptr_lunit=this%x, default='inactive')
        call hist_addfld1d (fname=this%info%fname('H2OSNO'), units='mm', &
             avgflag='A', long_name=this%info%lname('snow depth'), ptr_col=this%h2osno)
        call hist_addfld1d (fname=this%species%hist_fname('CROPPROD1', suffix='_LOSS'), &
             units='g/m^2/s', avgflag='A', long_name='x', ptr_gcell=this%x)
        """)
    r = by_name(ctsm.scrape(root))
    assert r["SMP"]["dims"] == ["levgrnd"] and r["SMP"]["horizontal"] == "column"
    assert r["KROOT"]["horizontal"] == "landunit" and r["KROOT"]["default"] == "inactive"
    assert r["H2OSNO"]["name_variants"] == "water_tracers" and r["H2OSNO"]["long_name"] == "snow depth"
    loss = r["this%species%hist_fname('CROPPROD1', suffix='_LOSS')"]
    assert loss["name_patterns"] == ["*CROPPROD1*_LOSS"] and loss["horizontal"] == "gridcell"


def test_cice(tmp_path):
    root = tmp_path / cice.REPO_PATH
    write(root, "src/cicecore/cicedyn/analysis/ice_history.F90", """
        call define_hist_field(n_aice,"aice","1",tstr2D, tcstr, &
            "ice area  (aggregate)", "none", c1, c0, ns1, f_aice)
        call define_hist_field(n_Tinz,"Tinz","C",tstr4Di, tcstr, &
            "ice internal temperatures","none", c1, c0, ns1, f_Tinz)
        call define_hist_field(n_x,"xfld","1",mystery, tcstr, "x","none", c1, c0, ns1, f_x)
        """)
    r = by_name(cice.scrape(root))
    assert r["aice"]["dims"] == [] and r["aice"]["horizontal"] == "T"
    assert r["aice"]["long_name"] == "ice area (aggregate)"
    assert r["Tinz"]["dims"] == ["nc", "nkice"]
    assert r["xfld"]["dims"] is None and r["xfld"]["dims_expr"] == "mystery"


def test_mom6(tmp_path):
    root = tmp_path / mom6.REPO_PATH
    write(root, "MOM6/src/diagnostics/MOM_diagnostics.F90", """
        CS%id_temp = register_diag_field('ocean_model', 'temp', diag%axesTL, Time, &
             'Potential Temperature', 'degC', cmor_field_name='thetao')
        CS%id_taux = register_diag_field('ocean_model', 'taux', CS%diag%axesCu1, Time, 'Zonal wind stress', 'Pa')
        id_zi = register_static_field('ocean_model', 'zi_static', diag%axesZi, 'interfaces', 'm')
        CS%id_ssh_ga = register_scalar_field('ocean_model', 'ssh_ga', Time, diag, &
             long_name='Area averaged SSH', units='m')
        id = register_diag_field('ocean_model', 'local', axes, Time, 'x', 'y')
        """)
    r = by_name(mom6.scrape(root))
    assert r["temp"]["dims"] == ["zl"] and r["temp"]["horizontal"] == "T"
    assert r["thetao"]["alias_of"] == "temp" and r["thetao"]["units"] == "degC"
    assert r["taux"]["horizontal"] == "Cu"
    assert r["zi_static"]["time"] is False and r["zi_static"]["dims"] == ["zi"]
    assert r["ssh_ga"]["dims"] == [] and r["ssh_ga"]["units"] == "m"
    assert r["local"]["dims"] is None and r["local"]["dims_expr"] == "axes"


def test_cism(tmp_path):
    root = tmp_path / cism.REPO_PATH
    write(root, "source_cism/libglide/glide_vars.def", """
        [VARSET]
        name:     glide

        [x1]
        dimensions:    x1
        axis:          X

        [temp]
        dimensions:    time, level, y1, x1
        units:         degree_Celsius

        [uvel]
        dimensions:    time, level, y0, x0
        """)
    r = by_name(cism.scrape(root))
    assert set(r) == {"temp", "uvel"}
    assert r["temp"]["dims"] == ["level"] and r["temp"]["horizontal"] == "x1y1" and r["temp"]["time"]
    assert r["uvel"]["horizontal"] == "x0y0"


def test_mosart(tmp_path):
    root = tmp_path / mosart.REPO_PATH
    write(root, "src/riverroute/mosart_histflds.F90", """
        call mosart_hist_addfld (fname='RIVER_DISCHARGE_OVER_LAND'//'_'//trim(ctl%tracer_names(nt)), &
             units='m3/s', avgflag='A', long_name='flow', ptr_rof=x, default='active')
        """)
    (rec,) = mosart.scrape(root)
    assert rec["name"] is None and rec["name_patterns"] == ["RIVER_DISCHARGE_OVER_LAND_*"]



def test_config_requires_and_active():
    from cesm_fields.config import active, requires
    assert requires("src/physics/cam/diag.F90:10") == {}
    assert requires("src/dynamics/fv3/x.F90:1") == {"dycore": ["fv3"]}
    assert requires("src/chemistry/pp_trop_strat_mam5_t4s2/mo_sim_dat.F90:3") == {"chem": ["trop_strat_mam5_t4s2"]}
    assert requires("src/control/history_scam.F90:9") == {"scam": [True]}
    assert requires("src/physics/cam/phys_debug.F90:9") == {"debug": [True]}
    assert requires("src/fates/main/FatesHistoryInterfaceMod.F90:5") == {"use_fates": [True]}
    assert requires("source_cism/glc_x.F90:5") == {"cism": [True]}
    assert requires("src/physics/cam/uwshcu.F90:5") == {"shallow": ["uw"]}
    cfg = {"dycore": "se", "chem": "trop_strat_mam5_t4s2", "scam": False}
    assert active({"requires": {"dycore": ["se"]}}, cfg) and active({}, cfg)
    assert not active({"requires": {"dycore": ["fv3"]}}, cfg)
    assert not active({"requires": {"scam": [True]}}, cfg)
    assert not active({"requires": {"use_fates": [True]}}, cfg)          # axis unset = off


def test_ctsm_fates(tmp_path):
    root = tmp_path / ctsm.REPO_PATH
    write(root, ctsm.FATES, """
        ! site x size-class/pft
        index = index + 1
        call this%dim_kinds(index)%Init(site_size_pft_r8, 2)
        call this%set_history_var(vname='FATES_NPLANT_SZPF', units='m-2', &
             long='number of plants per m2 by size x pft', use_default='inactive', &
             avgflag='A', vtype=site_size_pft_r8, hlms='CLM:ALM', ivar=ivar)
        """)
    (r,) = list(ctsm.scrape_fates(root))
    assert r["name"] == "FATES_NPLANT_SZPF" and r["dims"] == ["size-class", "pft"] and r["horizontal"] == "site"
    assert r["default"] == "inactive" and r["requires"] == {"use_fates": [True]}


def test_mom6_marbl_templates():
    settings = '''
         _array_shape : autotroph_cnt
         sname :
            default_value :
               ((autotroph_sname)) == "sp" : sp
               ((autotroph_sname)) == "diaz" : diaz
         lname :
            default_value :
               ((autotroph_sname)) == "sp" : Small Phyto
               ((autotroph_sname)) == "diaz" : Diazotroph
         Nfixer :
            default_value :
               default : .false.
               ((autotroph_sname)) == "diaz" : .true.
         zooplankton_settings :
         sname :
            default_value :
               ((zooplankton_sname)) == "micro" : micro
         lname :
            default_value :
               ((zooplankton_sname)) == "micro" : Micro
    '''
    pfts = mom6.marbl_pfts(settings)
    assert set(pfts["autotroph"]) == {"sp", "diaz"} and pfts["autotroph"]["diaz"]["flags"]["autotroph_Nfixer"]
    subs = mom6.marbl_expansions("((autotroph_sname))_Nfix", {"((autotroph_Nfixer))": True}, pfts)
    assert [mom6.fill("((autotroph_sname))_Nfix", s) for s in subs] == ["diaz_Nfix"]        # only the Nfixer
    both = mom6.marbl_expansions("graze_((autotroph_sname))_((zooplankton_sname))", {}, pfts)
    assert sorted(mom6.fill("graze_((autotroph_sname))_((zooplankton_sname))", s) for s in both) == ["graze_diaz_micro", "graze_sp_micro"]
    assert mom6.fill("POC_FLUX_((particulate_flux_ref_depth_str))", mom6.marbl_expansions("POC_FLUX_((particulate_flux_ref_depth_str))", {}, pfts)[0]) == "POC_FLUX_100m"


def test_cam_named_constituent_index_and_list_initialiser(tmp_path):
    root = tmp_path / cam.REPO_PATH
    write(root, cam.CONSTITUENT_ARRAYS[0][0], "cnst_names(2) = (/'CLDLIQ', 'CLDICE'/)\n")
    write(root, cam.CONSTITUENT_ARRAYS[1][0], "solsym(: 1) = (/ 'SO2             ' /)\n")
    write(root, "src/physics/cam/constituents.F90", "ptendnam(m) = 'PTE'//cnst_name(m)\n")
    write(root, "src/physics/cam/diag.F90", """
        character(len=4) :: diag(0:2) = (/'    ', '_d1 ', '_d2 '/)
        call cnst_get_ind('CLDICE', ixcldice)
        call addfld(ptendnam(ixcldice), (/ 'lev' /), 'A', 'kg/kg/s', 'x')
        call addfld('FLUT'//diag(icall), horiz_only, 'A', 'W/m2', 'olr')
        """)
    r = {x["name"]: x for x in cam.scrape(root)}
    assert "PTECLDICE" in r and "PTECLDLIQ" not in r        # one constituent, not all of them
    assert "FLUT" in r and "FLUT_d1" not in r              # the list initialiser (first entry), not FLUT*
