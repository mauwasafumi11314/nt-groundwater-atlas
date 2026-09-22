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
| 0 — repo scaffolding | CLAUDE.md + data guard written | — |
| 1 — ingest + trends | **Not started** — blocked, awaiting plan approval and raw data | `make test` + output shown |
| 2 — hydrostratigraphy | Not started | — |
| 3 — stress index | Not started | — |

### Current state
- Repository was empty at session start; branch `claude/great-davinci-ti3mj3`.
- `data/raw/` **does not exist** and contains no files. No raw data has been
  inspected, so **no field mappings exist and none may be written yet.**
- Phase 1 plan proposed, awaiting user approval.

### Open questions for the user
- Where is the raw data? `data/raw/` is empty/absent.
- Dependency list for phase 1 needs approval before anything is installed.
