"""Declaring how to *read* a raw file - not what its columns mean.

A `SourceSpec` carries only what cannot be discovered safely from the file
itself: a CRS when the file declares none, and a date format when the dates are
genuinely ambiguous. It deliberately holds no column mapping. Mappings require
having seen the data, and `data/raw/` is still empty; see `ntgw.ingest`.

Everything a spec does carry exists because guessing it corrupts data silently
rather than loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceSpec:
    """One raw file, and the minimum needed to read it without guessing."""

    path: Path
    #: Layer within a multi-layer file. None means the only layer, and a file
    #: with several layers raises rather than picking one.
    layer: str | None = None
    #: CRS to assume when the file declares none. If the file *does* declare
    #: one and this disagrees, loading raises: silently preferring either is
    #: how a dataset ends up in the wrong place with no trace.
    declared_crs: str | None = None
    #: Column -> strptime format, for date columns whose day/month order cannot
    #: be inferred. Required for those columns; loading raises without it.
    date_formats: dict[str, str] = field(default_factory=dict)
    #: Free text recording where the file came from and who confirmed the
    #: above. Carried into the `source_file` column.
    provenance: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))

    @property
    def name(self) -> str:
        return self.path.name
