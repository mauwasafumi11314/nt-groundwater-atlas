"""Ingest layer - deliberately empty.

No NT bore, water-level, licence or WCD extract has been inspected yet: at the
time of writing `data/raw/` does not exist. CLAUDE.md forbids writing a mapping
against a schema nobody has seen, so there are no readers here, no column
mappings, no code lists and no assumed join keys.

What has to be established from the files themselves before this module is
written:

  * the source CRS of each spatial file, read from its own metadata rather than
    assumed - this decides whether the NTv2 grid is needed at all
  * the join key between bores, levels and licences
  * whether depths are measured from the collar or from a separate measuring
    point, and where the offset lives if so
  * the units and reporting period of licensed entitlement
  * quality/status code lists, and which codes mean a reading is unusable
  * whether a collar RL is carried per bore, per reading, or both

Until then the analysis runs against synthetic fixtures (tests/fixtures/).
"""
