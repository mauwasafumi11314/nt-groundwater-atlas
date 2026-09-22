"""Conversion of depth-to-water readings to m AHD.

The project rule is that a bore without a collar reduced level is *flagged*,
not dropped. That is a deliberate choice about what the atlas is measuring. A
bore with no surveyed collar is usually a bore nobody has invested in, and
those are disproportionately the ones in the parts of the network with the
worst records. Dropping them would make the atlas quietly cleanest exactly
where monitoring is weakest.

Such a bore keeps every reading it has. `level_m_ahd` is null - it genuinely
is unknown - but `depth_to_water_m` is intact, and a trend in depth is a valid
trend once the sign is flipped. `ntgw.trends.runner` handles that.
"""

from __future__ import annotations

import pandas as pd

DATUM_KNOWN = "collar_rl_known"
DATUM_MISSING = "collar_rl_missing"


def classify_datum_status(collar_rl: pd.Series) -> pd.Series:
    """Map a collar RL column to its datum status flag."""
    return collar_rl.isna().map({True: DATUM_MISSING, False: DATUM_KNOWN})


def derive_levels(
    levels: pd.DataFrame,
    bores: pd.DataFrame,
    bore_id_col: str = "bore_id",
    depth_col: str = "depth_to_water_m",
    collar_col: str = "collar_rl_m_ahd",
) -> pd.DataFrame:
    """Attach `level_m_ahd` to `levels`, keeping every row.

    level_m_ahd = collar RL - depth below collar. Rows whose bore has no collar
    RL keep a null level and are not removed.
    """
    if bore_id_col not in levels.columns:
        raise KeyError(f"levels is missing {bore_id_col!r}")
    if bore_id_col not in bores.columns:
        raise KeyError(f"bores is missing {bore_id_col!r}")

    n_before = len(levels)
    collar = bores.set_index(bore_id_col)[collar_col]
    out = levels.copy()
    out["_collar_rl"] = out[bore_id_col].map(collar)
    out["level_m_ahd"] = out["_collar_rl"] - out[depth_col]
    out["datum_status"] = classify_datum_status(out["_collar_rl"])
    out = out.drop(columns=["_collar_rl"])

    if len(out) != n_before:
        raise AssertionError(
            f"derive_levels changed the row count ({n_before} -> {len(out)}); "
            "readings must never be dropped here"
        )
    return out


def datum_summary(levels: pd.DataFrame) -> dict[str, int]:
    """Counts by datum status, for the phase report."""
    counts = levels["datum_status"].value_counts().to_dict()
    return {
        "readings_total": int(len(levels)),
        "readings_with_ahd": int(counts.get(DATUM_KNOWN, 0)),
        "readings_without_collar_rl": int(counts.get(DATUM_MISSING, 0)),
    }
