-- NT Groundwater Stress Atlas - phase 1 target schema.
--
-- Column sets here are the structural minimum the analysis needs. Source
-- columns are deliberately absent: no raw extract has been inspected yet, and
-- CLAUDE.md forbids writing a mapping against a schema nobody has seen. The
-- ingest layer will add source-specific columns once the files are available.
--
-- Two project rules are enforced by the database itself rather than by code:
--
--   * EPSG:7853 everywhere. Every geometry column is declared
--     `geometry(<type>, 7853)`, so PostGIS rejects a wrong-SRID insert at write
--     time. tests/test_crs.py is the second net, not the first.
--   * "insufficient data" is never "no trend". trend_class is constrained to a
--     four-value enum, and a CHECK requires that an insufficient row carries a
--     reason and carries no statistics.

CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS bore_trend CASCADE;
DROP TABLE IF EXISTS water_level CASCADE;
DROP TABLE IF EXISTS licence CASCADE;
DROP TABLE IF EXISTS bore CASCADE;
DROP TABLE IF EXISTS wcd_boundary CASCADE;

-- ---------------------------------------------------------------------------
-- Water Control District boundaries. Pilot area: Western Davenport.
-- ---------------------------------------------------------------------------
CREATE TABLE wcd_boundary (
    wcd_id        text PRIMARY KEY,
    name          text NOT NULL,
    geom          geometry(MultiPolygon, 7853) NOT NULL,
    source_file   text NOT NULL,
    source_crs    text NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX wcd_boundary_geom_idx ON wcd_boundary USING GIST (geom);

-- ---------------------------------------------------------------------------
-- Bores.
--
-- datum_status carries the collar-RL rule. A bore with no collar RL is loaded
-- and flagged, never dropped: its water levels are still usable as depth below
-- collar, and excluding it would quietly shrink the monitoring network exactly
-- where record-keeping is worst.
-- ---------------------------------------------------------------------------
CREATE TABLE bore (
    bore_id           text PRIMARY KEY,
    geom              geometry(Point, 7853) NOT NULL,
    collar_rl_m_ahd   double precision,
    collar_rl_source  text,
    datum_status      text NOT NULL,
    source_file       text NOT NULL,
    source_crs        text NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT bore_datum_status_ck CHECK (
        datum_status IN ('collar_rl_known', 'collar_rl_missing')
    ),
    -- The flag must agree with the data: no silently-null RL claiming to be known.
    CONSTRAINT bore_datum_status_agrees_ck CHECK (
        (datum_status = 'collar_rl_known'   AND collar_rl_m_ahd IS NOT NULL) OR
        (datum_status = 'collar_rl_missing' AND collar_rl_m_ahd IS NULL)
    )
);
CREATE INDEX bore_geom_idx ON bore USING GIST (geom);
CREATE INDEX bore_datum_status_idx ON bore (datum_status);

-- ---------------------------------------------------------------------------
-- Water level observations.
--
-- depth_to_water_m is metres below the collar and is the measured quantity.
-- level_m_ahd is derived and is NULL exactly when the bore has no collar RL.
-- ---------------------------------------------------------------------------
CREATE TABLE water_level (
    observation_id     bigserial PRIMARY KEY,
    bore_id            text NOT NULL REFERENCES bore(bore_id) ON DELETE CASCADE,
    observed_at        timestamptz NOT NULL,
    depth_to_water_m   double precision,
    level_m_ahd        double precision,
    quality_flag       text,
    source_file        text NOT NULL,
    loaded_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT water_level_has_a_value_ck CHECK (
        depth_to_water_m IS NOT NULL OR level_m_ahd IS NOT NULL
    ),
    CONSTRAINT water_level_unique_reading_uq UNIQUE (bore_id, observed_at)
);
CREATE INDEX water_level_bore_time_idx ON water_level (bore_id, observed_at);

-- ---------------------------------------------------------------------------
-- Extraction licences.
--
-- Geometry type is left as generic `geometry` pending inspection of the raw
-- data: licences may be points, parcels or multipolygons and guessing would be
-- inventing a schema. The SRID is still pinned.
-- ---------------------------------------------------------------------------
CREATE TABLE licence (
    licence_id    text PRIMARY KEY,
    geom          geometry(Geometry, 7853),
    source_file   text NOT NULL,
    source_crs    text NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX licence_geom_idx ON licence USING GIST (geom);

-- ---------------------------------------------------------------------------
-- Per-bore trend results.
-- ---------------------------------------------------------------------------
CREATE TABLE bore_trend (
    bore_id                  text PRIMARY KEY REFERENCES bore(bore_id) ON DELETE CASCADE,
    basis                    text NOT NULL,
    trend_class              text NOT NULL,
    insufficient_reason      text,

    n_observations           integer NOT NULL,
    n_months_present         integer NOT NULL,
    span_years               double precision NOT NULL,
    distinct_years           integer NOT NULL,
    gap_fraction             double precision NOT NULL,
    longest_gap_months       integer NOT NULL,
    deseasonalised           boolean NOT NULL,

    sens_slope_m_per_year    double precision,
    sens_slope_lower         double precision,
    sens_slope_upper         double precision,
    p_value                  double precision,
    tau                      double precision,
    z_score                  double precision,
    variance_method          text,
    autocorrelation_factor   double precision,
    effective_n              double precision,

    computed_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT bore_trend_class_ck CHECK (
        trend_class IN ('rising', 'falling', 'no_trend', 'insufficient_data')
    ),
    CONSTRAINT bore_trend_basis_ck CHECK (
        basis IN ('head_m_ahd', 'depth_to_water_m')
    ),
    -- An insufficient record must say why, and must not carry statistics that
    -- would let it be read as a tested result.
    CONSTRAINT bore_trend_insufficient_ck CHECK (
        (trend_class = 'insufficient_data'
            AND insufficient_reason IS NOT NULL
            AND p_value IS NULL
            AND sens_slope_m_per_year IS NULL)
        OR
        (trend_class <> 'insufficient_data'
            AND insufficient_reason IS NULL
            AND p_value IS NOT NULL)
    )
);
CREATE INDEX bore_trend_class_idx ON bore_trend (trend_class);

-- ---------------------------------------------------------------------------
-- Convenience view for QGIS: trends carrying the bore geometry.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW bore_trend_geom AS
SELECT t.*, b.geom, b.datum_status, b.collar_rl_m_ahd
FROM bore_trend t
JOIN bore b USING (bore_id);
