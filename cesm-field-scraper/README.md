# cesm-field-scraper

Reads the CESM `cesm3_0_alpha09e` source and writes YAML listing every
history field each component can register: name, dims, units, long name,
and the source line. The Dockerfile is the record of how the YAML was made.
Nothing here depends on the rest of this repository.

```
make build    # ~2 min: clone CESM at the pinned commit, git-fleximod the six components
make run      # ~10 s: writes out/<component>.yaml and out/submodules.txt
make test     # pytest on synthetic snippets, no checkout needed
```

Without make: `python -m cesm_fields <CESM checkout> <out dir>` (needs PyYAML).

It's deliberately bespoke to this one tag: the call signatures, CICE/MOM6
shape tables and CAM chemistry package were all checked against this tag's
source. Another tag means a new Dockerfile and
re-checking those against the output.

## Output

`out/<component>.yaml` for `atm` (CAM), `lnd` (CTSM), `ice` (CICE), `ocn`
(MOM6), `glc` (CISM) and `rof` (MOSART). `out/submodules.txt` lists every
repo in the checkout with its commit and tag.

There is one record per registration call site:

```yaml
- name: H2OSOI
  dims: [levsoi]          # non-horizontal dims, ncdump order, no time
  horizontal: column      # component-specific token, explained at the top of each file
  time: true
  units: mm3/mm3
  long_name: volumetric soil water (natural vegetated and crop landunits only)
  avgflag: A
  name_variants: water_tracers
  registrar: hist_addfld2d
  source: src/biogeophys/WaterStateType.F90:223
```

Horizontal dims are separate because for CAM and CTSM they depend on case
configuration. CAM's `physgrid` is `ncol` on spectral-element grids and
`lat, lon` on finite-volume. A CTSM field's subgrid level is its horizontal
dim only for vector output.

When a name is built at runtime, the record keeps the source expression as
`name_expr`:

- **With a `name`:** the expression was expanded. For example, CAM's
  `sflxnam(m)` gives `SFQ`, `SFso4_a1`, …, one record each.
- **With `name: null`:** it couldn't be resolved. `name_patterns` holds the
  part the source does fix (`ABSORB*`).
- **`dims: null` + `dims_expr`:** the shape argument didn't resolve.

## CAM constituents

CAM registers constituent fields (`Q`, `O3`, `SFso4_a1`, `so4_a1_SRF`, …) in
loops over `cnst_name(m)`. The scraper expands those loops with what a CAM7
build registers:

- `Q`
- PUMAS's `cnst_names`
- the species of chemistry package `ghg_mam4`, which `bld/configure` uses
  by default for `-phys cam7`

It also expands the per-constituent name arrays built in `constituents.F90`
(`sflxnam`, `ptendnam`, …). A loop over a subset of constituents still
expands to all of them, so expanded records can over-claim.

## Checked against a real alpha09e run

| | names in the log | exact | pattern only | not found |
|---|---|---|---|---|
| CAM | 3245 | 45% | 42% | 13% |
| CTSM | 1922 | 78% | 18% | 5% |
| MOSART | 27 | 19% | 81% | 0% |
| CICE (active subset) | 121 | 100% | – | 0% |

Every CAM name found in the log has a vertical dim that agrees with the
log's level count. That covers both literal and expanded names, with no
disagreements.

The source also registers fields this run doesn't use. 56% of CAM's
literal names and 64% of its expanded names aren't in this run's log; they
come from other dycores, SCAM and debug paths. This tool lists what the
source *can* register, not what one case *does*.

## Layout

```
cesm_fields/fortran.py      statements, call arguments, literals, name expansion
cesm_fields/common.py       file walking, record format
cesm_fields/components/     one module per component
cesm_fields/__main__.py     CLI, YAML writer
docker/cesm3_0_alpha09e.Dockerfile
```
