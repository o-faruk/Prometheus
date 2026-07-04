CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS regions (
    region_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    weather_lat DOUBLE PRECISION NOT NULL,
    weather_lon DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS demand (
    time TIMESTAMPTZ NOT NULL,
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    demand_mwh DOUBLE PRECISION,
    demand_forecast_mwh DOUBLE PRECISION,
    PRIMARY KEY (time, region_code)
);
SELECT create_hypertable('demand', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_demand_region_time ON demand (region_code, time DESC);

CREATE TABLE IF NOT EXISTS generation_mix (
    time TIMESTAMPTZ NOT NULL,
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    fuel_type TEXT NOT NULL,
    generation_mwh DOUBLE PRECISION,
    PRIMARY KEY (time, region_code, fuel_type)
);
SELECT create_hypertable('generation_mix', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_genmix_region_time ON generation_mix (region_code, time DESC);

CREATE TABLE IF NOT EXISTS weather_observations (
    time TIMESTAMPTZ NOT NULL,
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    temperature_c DOUBLE PRECISION,
    source TEXT NOT NULL,
    PRIMARY KEY (time, region_code, source)
);
SELECT create_hypertable('weather_observations', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_weather_region_time ON weather_observations (region_code, time DESC);

-- Batch-scored, not computed per API request: the hourly scheduler fits the model and
-- writes results here, so the API only ever reads from Postgres. Also builds up a running
-- forecast-vs-actual history for free (see /predictions-history in the API).
CREATE TABLE IF NOT EXISTS forecasts (
    generated_at TIMESTAMPTZ NOT NULL,
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    target_time TIMESTAMPTZ NOT NULL,
    model_name TEXT NOT NULL,
    predicted_demand_mwh DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (generated_at, region_code, target_time, model_name)
);
SELECT create_hypertable('forecasts', 'generated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_forecasts_region_generated ON forecasts (region_code, generated_at DESC);
CREATE INDEX IF NOT EXISTS ix_forecasts_region_target ON forecasts (region_code, target_time);

CREATE TABLE IF NOT EXISTS alerts (
    generated_at TIMESTAMPTZ NOT NULL,
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    target_time TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL,
    forecasted_demand_mwh DOUBLE PRECISION NOT NULL,
    percentile_rank DOUBLE PRECISION,
    explanation TEXT NOT NULL,
    PRIMARY KEY (generated_at, region_code, target_time)
);
SELECT create_hypertable('alerts', 'generated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_alerts_region_generated ON alerts (region_code, generated_at DESC);

-- Small append-only summary log (one row per model per backtest run), not a hypertable —
-- backtests run occasionally/offline, not at ingestion volume.
CREATE TABLE IF NOT EXISTS model_accuracy (
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    region_code TEXT NOT NULL REFERENCES regions (region_code),
    model_name TEXT NOT NULL,
    test_start TIMESTAMPTZ NOT NULL,
    test_end TIMESTAMPTZ NOT NULL,
    mape DOUBLE PRECISION NOT NULL,
    mae DOUBLE PRECISION,
    rmse DOUBLE PRECISION,
    n_forecasts INT NOT NULL,
    PRIMARY KEY (computed_at, region_code, model_name)
);
CREATE INDEX IF NOT EXISTS ix_model_accuracy_region_computed ON model_accuracy (region_code, computed_at DESC);

-- Bookkeeping so backfill/hourly jobs are auditable and resumable, not fire-and-forget.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    region_code TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    rows_ingested INT,
    error_message TEXT
);

INSERT INTO regions (region_code, display_name, timezone, weather_lat, weather_lon)
VALUES ('CISO', 'California ISO', 'America/Los_Angeles', 34.05, -118.25)
ON CONFLICT (region_code) DO NOTHING;
