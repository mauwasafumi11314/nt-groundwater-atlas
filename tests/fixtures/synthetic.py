"""Synthetic fixtures. No real NT data appears anywhere in this repository.

Coordinates are plausible for the Western Davenport WCD only so that envelope
checks exercise realistic numbers; they are generated, not observed, and the
"WCD boundary" here is a rectangle, not the gazetted district.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# MGA53_ENVELOPE is re-exported from the package: it is a derived property of
# zone 53, not a fixture choice, and an independent copy here drifted (its
# southern bound sat ~600 km outside the NT).
from ntgw.crs import ATLAS_EPSG, MGA53_ENVELOPE  # noqa: F401

#: Approximate MGA zone 53 envelope of the Western Davenport area, used to
#: catch wrong-zone or swapped lat/lon loads. Deliberately generous.
WCD_ENVELOPE = {"min_x": 300_000.0, "max_x": 560_000.0, "min_y": 7_540_000.0, "max_y": 7_760_000.0}


def synthetic_bores(n: int = 6, seed: int = 11) -> pd.DataFrame:
    """Bores inside the pilot envelope. Two deliberately lack a collar RL."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(WCD_ENVELOPE["min_x"] + 20_000, WCD_ENVELOPE["max_x"] - 20_000, n)
    y = rng.uniform(WCD_ENVELOPE["min_y"] + 20_000, WCD_ENVELOPE["max_y"] - 20_000, n)
    collar = rng.uniform(300.0, 420.0, n)
    rows = []
    for i in range(n):
        missing_rl = i in (2, 4)
        rows.append(
            {
                "bore_id": f"SYN{i + 1:03d}",
                "x": float(x[i]),
                "y": float(y[i]),
                "collar_rl_m_ahd": None if missing_rl else float(collar[i]),
                "collar_rl_source": None if missing_rl else "synthetic_survey",
                "datum_status": "collar_rl_missing" if missing_rl else "collar_rl_known",
                "source_file": "synthetic",
                "source_crs": f"EPSG:{ATLAS_EPSG}",
            }
        )
    return pd.DataFrame(rows)


def hydrograph(
    kind: str,
    start: str = "2008-01-01",
    seed: int = 3,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Generate a monthly hydrograph of a named shape.

    kinds: 'falling', 'rising', 'flat', 'short', 'sparse', 'seasonal_only',
           'autocorrelated_flat'

    Values are always a plain ndarray, never a pandas Index.
    """
    rng = np.random.default_rng(seed)

    def base(n_months: int) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
        idx = pd.date_range(start, periods=n_months, freq="MS")
        t = np.arange(n_months, dtype=float)
        # np.asarray: DatetimeIndex.month is an Index, and Index arithmetic
        # propagates, which would hand callers an Index instead of an ndarray.
        month = np.asarray(idx.month, dtype=float)
        season = 1.5 * np.sin(2 * np.pi * month / 12.0)
        return idx, t, season

    if kind == "falling":
        idx, t, season = base(180)
        return idx, 330.0 - 0.25 * (t / 12.0) + season + rng.normal(0, 0.10, t.size)
    if kind == "rising":
        idx, t, season = base(180)
        return idx, 330.0 + 0.18 * (t / 12.0) + season + rng.normal(0, 0.10, t.size)
    if kind == "flat":
        idx, t, season = base(180)
        return idx, 330.0 + season + rng.normal(0, 0.10, t.size)
    if kind == "seasonal_only":
        idx, t, season = base(180)
        return idx, 330.0 + 3.0 * season
    if kind == "short":
        idx, t, season = base(9)
        return idx, 330.0 - 0.25 * (t / 12.0) + season + rng.normal(0, 0.10, t.size)
    if kind == "sparse":
        # 15 years of record but only a handful of readings, and a long blind gap.
        idx, t, season = base(180)
        values = 330.0 - 0.25 * (t / 12.0) + season + rng.normal(0, 0.10, t.size)
        keep = np.zeros(t.size, dtype=bool)
        keep[:6] = True
        keep[-6:] = True
        return idx[keep], values[keep]
    if kind == "autocorrelated_flat":
        idx, t, season = base(180)
        noise = np.zeros(t.size)
        e = rng.normal(0, 0.3, t.size)
        for i in range(1, t.size):
            noise[i] = 0.85 * noise[i - 1] + e[i]
        return idx, 330.0 + season + noise
    raise ValueError(f"unknown hydrograph kind {kind!r}")


def synthetic_wcd_polygon():
    """A rectangular stand-in for the district boundary."""
    from shapely.geometry import MultiPolygon, box

    e = WCD_ENVELOPE
    return MultiPolygon([box(e["min_x"], e["min_y"], e["max_x"], e["max_y"])])
