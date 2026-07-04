# Prometheus — Build Notes

Checkpoint log for each phase: what got built, decisions made and why, what's left, and the
concepts you should be able to explain afterward. Newest phase at the bottom.

---

## Phase 1 — Data pipeline foundation

**What's built and verified live:**
- TimescaleDB running in Docker, schema applied (`backend/app/db/schema.sql`): `regions`, `demand`, `generation_mix`, `weather_observations` as hypertables, plus `ingestion_runs` for audit bookkeeping.
- `EIAClient` — paginated, retried (exponential backoff + jitter via `tenacity`), rate-limited (custom token bucket), pulls hourly demand, EIA's own day-ahead demand forecast, and generation mix by fuel type.
- `WeatherClient` (Open-Meteo) — historical archive + recent/forecast, both keyless.
- Generic `ingest.py` used by both `backfill.py` (CLI, date-range) and `scheduler.py` (hourly APScheduler job, 3-day rolling re-pull to catch EIA's revisions).
- **Real data loaded:** 65,784 hourly demand rows, 514,722 generation-mix rows across 9 fuel types (coal, geothermal, gas, nuclear, oil, other, solar, water, wind), 65,784 weather rows — CAISO, 2019-01-01 through today. Verified the demand↔weather join works cleanly on `(time, region_code)`.

**Decisions made and why:**
- **CAISO over ERCOT** for region #1 — zero registration friction (ERCOT needs developer-portal approval); EIA gives both the same API shape, so switching/adding regions later is a `regions.py` entry, not a rewrite.
- **Open-Meteo instead of NOAA/OpenWeather** — one free, keyless provider covering both historical (ERA5 reanalysis back to 1940) and recent/forecast, instead of juggling two APIs and a second key.
- **Docker Desktop over native Homebrew Postgres** — TimescaleDB isn't in core Homebrew and Docker matches how this will run in production later.
- **Raw SQL via `psycopg`, not an ORM**, for ingestion — bulk time-series upserts are one of the few places hand-written SQL is the standard production choice.

**What you should understand now (interview-ready):**
1. **Hypertables** — a normal-looking Postgres table that TimescaleDB partitions into time-bounded "chunks" under the hood, so time-filtered queries only scan relevant chunks instead of the whole table.
2. **Why upsert (`ON CONFLICT DO UPDATE`), not insert** — EIA revises recently-published hours for a few days after first publishing them, and Open-Meteo's real-time estimate for an hour gets silently replaced by the authoritative reanalysis value once its archive catches up (~5 day lag). The pipeline is designed to be re-run over the same window safely.
3. **Rate limiting via token bucket** — tokens refill continuously at a fixed rate; if you're out, the caller blocks and waits instead of erroring. This caps our request rate under EIA's limit without needing to track wall-clock windows.
4. **Retry with exponential backoff + jitter** (`tenacity`) — on a transient failure (429, 5xx, connection drop), wait a randomized, growing interval before retrying, so a flaky API call doesn't crash the whole ingestion run, and many clients retrying simultaneously don't all hammer the server at the same instant.
5. **Why demand has two columns (`demand_mwh`, `demand_forecast_mwh`)** — EIA publishes its own day-ahead forecast alongside actuals. That's a free, real naive-baseline comparator for Phase 2's backtesting — "did we beat EIA's own forecast" is a stronger claim than "did we beat same-hour-last-week."

**What's left / open:**
- Only CAISO is loaded — ERCOT/PJM come in Phase 4 per the original plan.
- No API layer yet (Phase 5) — right now this is pure ingestion + storage.
- The hourly scheduler is written and tested logically but not yet left running continuously — that's more of a Phase 6 deployment concern, or it can be run locally now for live updates before then.

---

## Phase 2 — Baseline model + backtesting framework

**What's built and verified live:**
- `app/forecasting/data.py` — loads demand + weather as clean hourly `pandas` series, interpolating gaps up to 3 hours and warning on anything larger (7.5 years of CAISO data had 29 missing demand hours total, mostly the last couple of hours near "now" where EIA hasn't published yet).
- `app/forecasting/metrics.py` — MAPE / MAE / RMSE.
- `app/forecasting/models/` — a small `Forecaster` interface (`fit(demand, temperature)`, `predict(origin, horizon, temperature_future)`) with two implementations:
  - `SeasonalNaiveForecaster` — `forecast(t) = actual(t - 168h)`, the floor.
  - `ProphetForecaster` — daily + weekly + yearly seasonality, temperature as an added regressor.
- `app/forecasting/backtest.py` — the walk-forward harness: steps through daily forecast origins in a held-out window, refitting the model only every N days (configurable per model) and reusing that fit across origins in between, so it mirrors periodic-retrain/continuous-operation deployment instead of an unrealistic hourly-refit.
- `app/forecasting/run_backtest.py` — CLI that runs naive (refit daily — it's free) and Prophet (refit weekly) over a 90-day held-out test window, plus scores EIA's own published day-ahead forecast over the same window as a third reference point. Full per-forecast output in `backend/reports/*.csv` (gitignored, regenerate with `python -m app.forecasting.run_backtest`).

**Real backtest results — CAISO, 90-day held-out window (2026-04-03 to 2026-07-02), 1-24h-ahead forecasts, n=2160:**

| Model | MAPE | MAE | RMSE |
|---|---|---|---|
| EIA's own day-ahead forecast | 10.69% | n/a | n/a |
| Seasonal-naive (168h lag) | 6.84% | 1810.7 | 2480.9 |
| **Prophet (+temperature)** | **6.13%** | **1598.5** | **2071.9** |

**Genuine interesting finding:** both from-scratch models beat EIA's own published day-ahead forecast for CAISO by a wide margin (6-7% MAPE vs 10.69%). Worth digging into *why* before leaning on this in the README — EIA's `DF` series may be a less-tuned or differently-scoped forecast than what CAISO uses operationally, so this isn't necessarily "we outperformed the grid operator," more "we outperformed this specific published series." Flagging so it gets qualified honestly rather than oversold.

**MAPE by hours-ahead (naive vs Prophet):** Prophet wins at every horizon except h=12, where naive's week-ago lookback happens to line up well with regular midday demand:

| hours ahead | naive | prophet |
|---|---|---|
| 1 | 11.09% | 7.64% |
| 6 | 6.43% | 4.68% |
| 12 | 3.61% | 4.85% |
| 18 | 8.19% | 7.88% |
| 24 | 10.08% | 7.21% |

**Decisions made and why:**
- **Prophet instead of SARIMA** (flagged live, both were pre-approved options) — hourly grid data has daily *and* weekly seasonality simultaneously; SARIMA can represent that but a seasonal period of 168 makes the model's state huge and slow to fit, so real usage typically drops the weekly component or hacks it in via exogenous dummies. Prophet decomposes multiple seasonalities natively and takes temperature as a regressor directly — a better fit for this exact data shape.
- **Weekly refit, daily forecast origins, 24h horizon** — refitting a model every single day for 90 days (or worse, every hour) is expensive for no realistic benefit; real deployments retrain periodically and serve forecasts continuously in between. The naive baseline is refit "daily" too, but that's free (no training step, just a pointer to the latest history) — giving it maximum freshness is the fairest treatment of a zero-cost model.
- **Backtest evaluates a full 24-value forecast curve per origin, not one point** — "day-ahead forecast" in grid operations means predicting the whole next day's hourly shape, not a single number, so each origin contributes 24 (hours-ahead, predicted, actual) rows, letting us also break down accuracy by how far ahead the forecast reaches.
- **Known limitation, not yet fixed:** the backtest feeds each model the *actual* historical temperature for the forecast window, not a weather forecast — i.e., it assumes a perfect weather forecast. Real deployment would need real forecasted temperature at prediction time; this overstates achievable accuracy somewhat and should be caveated in the final README.

**What you should understand now (interview-ready):**
1. **Why time series can't be randomly train/test split** — shuffling would let the model train on data from after the point it's being asked to predict, silently leaking the future into training. Walk-forward validation (train on the past, forecast the future, slide forward) is the only honest way to backtest.
2. **Periodic refit vs. continuous refit** — production forecasting systems almost never retrain on every new data point; they retrain on a schedule (here, weekly) and serve forecasts off that fixed model until the next retrain. A backtest that ignores this (refits before every single forecast) overstates real-world accuracy.
3. **Why MAPE was safe to use here** — MAPE divides by the actual value, so it blows up or misbehaves near zero; that's a real risk for series that cross zero (e.g., interchange, temperature) but not for grid demand, which is always tens of thousands of MWh.
4. **What "adding a regressor" means in Prophet** — Prophet's base model is trend + automatically-detected seasonalities; `add_regressor("temperature")` bolts on a linear term for an external variable so the model can react to something it can't learn from the calendar alone (a heat wave doesn't repeat on a fixed schedule).
5. **Why a free baseline (EIA's own forecast) matters** — a model only "beating a baseline" is meaningless if the baseline is trivial. Comparing against EIA's actual published forecast, not just our own naive one, gives a claim ("beat the grid operator's own day-ahead number") that's much harder to dismiss as a strawman — though as noted above, this specific claim needs a caveat before it goes in the README.

**What's left / open:**
- Only 90 days backtested — worth checking whether results hold over a full year (captures summer heat-wave stress periods CAISO is known for, which is exactly the "grid stress" scenario this whole project is about).
- Perfect-foresight temperature assumption needs addressing before the final case study, either by explicitly caveating it or by sourcing a real historical forecast-vs-actual weather dataset.
- Haven't investigated why EIA's own `DF` series underperforms so much — worth a quick look before using that comparison as a headline result.
- Phase 3 (gradient-boosted model) reuses this exact backtest harness for an apples-to-apples three-way comparison.
