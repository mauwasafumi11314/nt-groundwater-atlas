# CLAUDE.md — NT Groundwater Stress Atlas

Groundwater stress atlas for Central Australia. Pilot area: **Western Davenport
Water Control District, NT**. Portfolio project.

## Phases

Each phase stops at a review gate. A phase is **done** only when `make test`
passes *and* the output has been shown to the user.

1. **Ingest + trends** — load NT bore, water-level, licence and WCD data from
   `data/raw/` into PostGIS (docker-compose); per-bore de-seasonalised
   Mann-Kendall + Sen's slope; GeoPackage export for QGIS.
2. **Hydrostratigraphy** — AEM/hydrostratigraphy, water-table surfaces per
   aquifer, GDE vegetation stress.
3. **Stress index** — GRACE, InSAR, stress index with confidence layer,
   drawdown screening, web map.

At each gate, report: what was built, what is untested, what needs user input.

## Rules

These are binding. Where a rule says *enforced*, there is a check that fails —
prose alone is not enough.

### Coordinate reference system
- **Everything is EPSG:7853** (GDA2020 / MGA zone 53). Every PostGIS table,
  every exported layer, every intermediate.
  *Enforced:* `tests/test_crs.py` fails if any geometry column, any GeoPackage
  layer, or any other spatial output is not 7853.
- **GDA94 → GDA2020 goes through the NTv2 grid**, never a ballpark or
  null transform. The transformation must be the grid-based one; a
  ballpark/no-op fallback is a hard error.
  *Enforced:* the CRS helper resolves transforms with ballpark disabled and
  best-available-only, and raises at import/startup if the grid is absent.
  Missing grid = loud failure, never a silent degrade.

### Levels and datum
- Water levels are stored as **m AHD**.
- A bore **without a collar RL is flagged, never dropped**. It keeps its
  depth-to-water observations and carries an explicit datum status; only the
  m AHD value is null.
  *Enforced:* ingest test asserts no-collar-RL bores survive the load.

### Data handling
- **Never commit data.** `data/` is gitignored *and* a pre-commit hook blocks
  it. Tests use **synthetic fixtures** only — no real extracts in the repo.
  *Enforced:* `scripts/hooks/pre-commit`, installed by `make install-hooks`.
- **Inspect raw files and show the fields before writing any mapping.**
  Never invent a URL, a schema, a field name or a code list. If a file has
  not been seen, its mapping does not get written.

### Interpretation
- **Too little data is "insufficient data"** — never "low stress", never
  "no trend". `insufficient_data` and `no_trend` are distinct outcomes:
  `no_trend` requires that the test actually ran and failed to reject.
  *Enforced:* trend classes are a constrained enum; a test asserts short and
  sparse records classify as `insufficient_data`.

### Scope
- **No spring, soakage or sacred site layers** unless the user asks.
  *Enforced:* a repo check fails on layer/table names matching those themes.
- **Do not generate FME workspaces.** *Enforced:* repo check rejects `.fmw`.

### Environment
- **conda-forge on macOS** is the target dev environment.
- **Ask before adding any dependency.**

## Progress

| Phase | Status | Gate |
|---|---|---|
| 0 — scaffolding | Done | — |
| 1 — ingest + trends | **Analysis built and tested; ingest blocked on raw data** | `make test` + output shown |
| 2 — hydrostratigraphy | Not started | — |
| 3 — stress index | Not started | — |

### Built (phase 1, data-independent parts)
- `ntgw.crs` — EPSG:7853 policy and NTv2 grid enforcement.
- `ntgw.trends` — Mann-Kendall, Sen's slope, two-pass de-seasonalisation,
  sufficiency gate, per-bore runner.
- `ntgw.levels` — m AHD derivation, collar-RL flagging.
- `ntgw.scope` — excluded-theme guard, wired into the GeoPackage writer.
- `ntgw.inspect` / `make inspect` — reports the structure of everything in
  `data/raw/` (fields, dtypes, null fractions, declared CRS vs actual
  coordinates, code lists, dd/mm vs mm/dd ambiguity) so mappings can be written
  from evidence. Reports; never resolves.
- `ntgw.ingest.load` / `ntgw.ingest.source` — the half of ingest that does not
  need column names: open a file, establish its CRS honestly, transform through
  the grid, and prove the result landed in zone 53. Refuses rather than guesses
  on a missing CRS, disagreeing CRS declarations, an unnamed layer in a
  multi-layer file, and dd/mm vs mm/dd dates. **No column mapping** — that still
  needs the files.
- `ntgw.db`, `ntgw.export.gpkg`, `sql/001_schema.sql`, docker-compose,
  `environment.yml`, `make doctor`, `make test-strict`.
- 124 tests. `scripts/demo_phase1.py` runs the pipeline end to end on synthetic data.

### Findings that changed the design
- **`allow_ballpark=False` and `only_best=True` do not catch a missing NTv2
  grid.** PROJ ranks the 7-parameter Helmert ("GDA94 to GDA2020 (1)") as the
  best *available* operation with a 0.01 m stated accuracy, so neither flag
  fires and the Helmert is used silently. Enforcement must name the required
  grid and verify the resolved pipeline uses it. Pinned by
  `test_helmert_fallback_is_not_silently_accepted`.
- **PostGIS coerces SRID 0 to the column SRID.** Geometry offered without a
  SRID is relabelled 7853 rather than rejected, so untransformed GDA94
  coordinates would land ~1.8 m out with the table looking consistent. Guarded
  at write time in `ntgw.db.require_atlas_crs`.
- **Uncorrected Mann-Kendall is unusable on hydrographs.** On trendless AR(1)
  series with phi=0.85 it rejects ~51% of the time against a nominal 5%.
  Hamed & Rao with Anderson bounds, truncated at the first insignificant lag,
  brings that to ~13% (n=120) and ~7% (n=240) — better, not fixed. Summing all
  lags is unstable and can deflate the variance. `autocorrelation_factor` and
  `effective_n` are stored for the phase-3 confidence layer.
- **One-pass de-seasonalising leaks the trend into the climatology**, leaving a
  sawtooth of amplitude ~ slope x 11 months. Two-pass removes it exactly.
- **A wrong declared CRS transforms cleanly.** Nothing in the CRS machinery
  notices; only checking where the coordinates *landed* does. `assert_within_zone53`
  validates the result against a derived zone 53 envelope.
- **`is_object_dtype` is not a portable text test.** pandas 2 reads strings as
  `object`, pandas 3 as `str`, so the ambiguous-date guard was silently
  disabled here and would have behaved differently on macOS. The check is
  inverted now (`may_hold_text`) and pinned by a test across both dtypes.
- **A stopped database turned four enforcement tests into skips and the suite
  still reported green.** `make test-strict` (doctor + `--strict-skips`) makes
  any skip a failure where the environment is supposed to be complete.

### Untested / unverified
- The ICSM NTv2 grid is **not installed in the dev container** (`cdn.proj.org`
  and the conda channels are blocked by network policy), so the grid *success*
  path is skipped, not passing. `make doctor` fails accordingly. Needs a run on
  macOS with `proj-data`.
- `environment.yml` has never been resolved on macOS.
- `docker-compose.yml` has never been started (image pull blocked); PostGIS was
  tested against a local 16/3.4 install instead.
- No real data has been read, so no ingest mapping exists.

### Open questions for the user
- Where is the raw data? `data/raw/` is still empty. Once it is there,
  `make inspect` produces everything needed to write the mappings.
- Sufficiency thresholds are provisional pending the record-length distribution.
- Residual over-rejection at high autocorrelation: accept, or add a block
  bootstrap?
