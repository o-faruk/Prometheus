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

> **Correction from Phase 3:** Prophet was being fit on raw UTC timestamps instead of local
> (`America/Los_Angeles`) clock time, which distorts its daily/weekly seasonality across DST
> transitions. Fixed in `ProphetForecaster` (now takes a `timezone` arg). Re-run numbers below
> are barely changed (6.13% → 6.17% MAPE) since it's a subtle effect, but the corrected numbers
> are the ones to trust — see Phase 3 for the up-to-date three-way comparison.

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

---

## Phase 3 — Gradient-boosted model + feature engineering

**What's built and verified live:**
- `app/forecasting/features.py` — builds a "direct multi-horizon" training panel: one row per `(origin, hours_ahead)` pair for `hours_ahead` in 1..24, target = actual demand at `origin + hours_ahead`. Every feature is either calendar knowledge of the target time (always knowable in advance) or computed from data at/before `origin` (never later) — verified this is leakage-free by manually cross-checking feature values against direct lookups on real rows, not just by reasoning about it.
- `app/forecasting/models/lightgbm_model.py` — `LightGBMForecaster`: a single LightGBM model trained on the full panel, with `hours_ahead` itself as a categorical feature, so one model produces the whole 24-hour curve directly instead of chaining 24 recursive one-step predictions (which would compound error).
- **Bug found and fixed while building this:** `ProphetForecaster` (Phase 2) was fitting seasonality against raw UTC timestamps instead of local clock time. Grid demand cycles follow the wall clock, and CAISO observes DST, so a naive UTC hour drifts against real local time depending on time of year. Fixed by converting to `America/Los_Angeles` before building Prophet's `ds` column; re-ran the Phase 2 backtest with the fix (numbers barely moved, see correction note above Phase 2).
- **Interface change:** `Forecaster.predict()` now also receives `demand_history`/`temperature_history` computed fresh as of the actual forecast origin, separate from whatever data the model was last *fit* on. This matters because the harness only refits weekly but predicts daily — a naive design would either force a refit every single day (expensive, unrealistic) or serve lag features from a stale snapshot. Real forecasting systems separate these two clocks: the model's parameters update on a slow cadence, but the features it's fed at serving time are always fresh. `naive` and `prophet` were updated to the new signature (prophet ignores the extra args, since its state is fully internal).

**Real backtest results — CAISO, 90-day held-out window, 1-24h-ahead forecasts, n=2160 (same window as Phase 2, corrected Prophet):**

| Model | MAPE | MAE | RMSE |
|---|---|---|---|
| EIA's own day-ahead forecast | 10.69% | n/a | n/a |
| Seasonal-naive (168h lag) | 6.84% | 1810.7 | 2480.9 |
| Prophet (+temperature) | 6.17% | 1598.7 | 2071.9 |
| **LightGBM (+engineered features)** | **2.94%** | **760.1** | **1078.9** |

LightGBM wins at *every* horizon bucket, not just on average — a much stronger and more consistent result than Phase 2's Prophet-vs-naive gap:

| hours ahead | naive | prophet | lightgbm |
|---|---|---|---|
| 1 | 11.09% | 8.13% | 4.09% |
| 6 | 6.43% | 4.08% | 1.87% |
| 12 | 3.61% | 4.84% | 1.48% |
| 18 | 8.19% | 8.39% | 4.44% |
| 24 | 10.08% | 7.26% | 5.23% |

**Feature importances (LightGBM, gain-based):** `naive_24h_lag` and `temperature_target` dominate, followed closely by `hour_of_day`, `naive_168h_lag`, `day_of_week`, and `month`. `is_holiday` and `temperature_target_sq` contributed **zero** importance — a genuinely interesting, explainable result: gradient-boosted trees split on raw values and can already represent a nonlinear temperature response without a manually squared term, so the engineered quadratic was redundant (the model gets the same nonlinearity for free). Holidays may just be too rare / already implied by day-of-week + is_weekend for this feature set to add signal — worth a closer look before writing this into the README as a firm conclusion, since it's a call to prune, not just a footnote.

**Decisions made and why:**
- **Direct multi-horizon over recursive forecasting** — a recursive model (predict h=1, feed that prediction back in to predict h=2, etc.) compounds its own errors over 24 steps and requires fabricating "1-hour-ago demand" for target hours where that's actually still in the future. Using only lags guaranteed to be real data regardless of horizon (target−24h, target−168h) avoids both problems at the cost of not using very-short lags (1-3h ago) at all.
- **`hours_ahead` as a model feature, not 24 separate models** — lets one model share statistical strength across horizons (patterns learned from 6h-ahead data can inform 18h-ahead predictions) instead of training on 1/24th the data per horizon.
- **LightGBM over XGBoost** — native categorical feature support (hour/day-of-week/month/hours_ahead) without manual one-hot encoding, and it installed cleanly on Apple Silicon without any build issues (XGBoost's wheel support here is more variable).

**What you should understand now (interview-ready):**
1. **The lag-feature causality trap in multi-step forecasting** — a feature like "demand 1 hour ago" is real data for a 1-hour-ahead forecast but a *prediction* for a 24-hour-ahead one from the same origin. Using it for both without accounting for that is a subtle, easy-to-miss form of data leakage. The fix is to only use lags at least as old as your longest horizon.
2. **Direct vs. recursive multi-horizon strategies** — direct (what we built): one shot per horizon, no error compounding, but limited to features valid at every horizon. Recursive: chain one-step predictions forward, can use richer short-term lags, but errors accumulate and early mistakes poison later steps. Real systems pick based on how far ahead they need to forecast and how much that error compounding actually costs.
3. **Why UTC vs. local time isn't a cosmetic detail** — any feature or seasonality component tied to "hour of day" or "day of week" is implicitly a claim about human behavior, which runs on local clocks, not UTC. Getting this wrong doesn't crash anything; it just quietly degrades a subset of your features in a way that's easy to miss without an explicit check (which is exactly how it slipped through Phase 2).
4. **"Stale model, fresh features" is a real production pattern**, not just a quirk of this backtest — a model's learned parameters (tree splits, regression weights) usually update on a slow, deliberate retraining cadence, but the input features it's scored against at serving time reflect the current instant. Conflating "how often do I retrain" with "how fresh is my input data" is a common design mistake.
5. **Reading gradient-boosted feature importances as a pruning signal, not just a curiosity** — `is_holiday` and `temperature²` scoring zero isn't just interesting trivia, it's actionable: it says those features can likely be dropped without hurting accuracy, and explains *why* (trees already capture what the squared term was meant to add).

**What's left / open:**
- `is_holiday` scoring zero deserves a real look (single-country US calendar might just be too coarse, or too collinear with day-of-week) before deciding whether to drop it or fix it — currently just noted, not resolved.
- No hyperparameter tuning was done on LightGBM (used reasonable defaults) — real tuning (time-series cross-validation over `num_leaves`/`learning_rate`/`n_estimators`) is realistic future work and could push accuracy further, worth mentioning as such in the README rather than implying these are already-optimal numbers.
- Perfect-foresight temperature assumption (flagged in Phase 2) still applies here too, and now matters more since LightGBM leans on `temperature_target` as its #2 feature — this is the most important open item before the case-study README, since it's the biggest gap between backtested and realistically-achievable accuracy.
- This is still single-region (CAISO) — Phase 4 (multi-region + alerting) will show whether this feature set and result generalize, or whether CAISO's specific climate/seasonality was doing a lot of the work.

---

## Phase 4 — Multi-region + alerting logic

**What's built and verified live:**
- **ERCOT (`ERCO`) and PJM (`PJM`) added** to `regions.py` alongside CAISO — timezone, EIA respondent code, and a representative weather coordinate each. Backfilled 2019-present for both using the *exact same* `backfill.py` CLI from Phase 1, unmodified.
- `app/alerts/stress.py` — stress classification and plain-language explanation generator:
  - Two-tier thresholds (`watch` = 95th percentile, `warning` = 99th percentile) computed from each region's own historical hourly demand.
  - `find_similar_historical_event` — among the region's own past watch-or-worse hours, finds the one whose temperature most closely matches the current forecast (excluding a 48h window around the target so it can't trivially match itself).
  - `_render_explanation` — assembles severity, percentile rank, temperature vs. typical-for-this-hour-and-month, weekday/weekend/holiday, and the similar historical event into one readable sentence-per-fact explanation.
- `app/alerts/demo.py` — proves alerts fire correctly against **real** historical stress events (not synthetic ones): for each region, finds its true historical peak-demand hour, fits `LightGBMForecaster` on everything before the day prior, forecasts forward 24h, and runs the result through the alert generator.
- Extended `WeatherClient` with `fetch_forecast_hourly` (Open-Meteo's real forward-looking forecast, not the perfect-foresight actuals used for backtesting) — for a live deployment, the alert pipeline can use a genuine weather forecast instead of assuming perfect knowledge of the future.

**Real demonstration output — all three regions, real historical peak events:**

| Region | Peak event found | Forecast vs. actual | Alert | Driving factor |
|---|---|---|---|---|
| CAISO | 2022-09-06 18:00 PDT (the real Sept 2022 CA heat wave — a genuine near-rotating-outage event) | 44,411 vs 51,104 MWh | WARNING (top 0.1%) | 30°C, 4°C above typical |
| ERCOT | 2024-08-20 18:00 CDT | 81,968 vs 85,544 MWh | WARNING (top 0.3%) | 38°C, 3°C above typical |
| PJM | 2025-06-23 18:00 EDT | 148,471 vs 160,560 MWh | WARNING (top 0.0%) | 37°C, 11°C above typical |

All three fired correctly, and CAISO's result lines up with a real, well-known grid emergency — a strong validation that isn't just "the code runs," it's "the code identifies an event a domain expert would recognize." Worth noting honestly: in all three cases the model *under-predicted* the actual extreme value (by 6-13%), consistent with what backtesting already showed — hard tail events are the hardest thing to forecast well, for any model. The alerts still correctly fired as WARNING in every case, because even the conservative forecasts were extreme enough to cross the threshold — a useful robustness property, not a coincidence: a system that only alerts when the forecast is *exactly* right would be far less useful than one that alerts on "this is going to be bad" even when it can't pin down exactly how bad.

**Bugs found and fixed while building this (both real, both worth knowing):**
1. **Region config wasn't actually wired to the database.** `REGIONS` in Python and the `regions` table in Postgres were two disconnected sources of truth — Phase 1's `schema.sql` only ever seeded CISO once, at container creation. Adding ERCOT/PJM to `regions.py` alone did nothing; the first backfill attempt failed on a foreign-key violation. Fixed with `ensure_region_row()`, called at the start of every backfill/ingest run, which upserts `regions.py`'s data into the DB — so `regions.py` is now genuinely the single source of truth, and adding a 4th region really is just a config edit, which is what Phase 1 originally claimed but hadn't actually proven under a second region.
2. **EIA returned corrupted data for PJM** — a demand value of ~2.1 billion MWh for one hour (and several smaller but still impossible values, up to ~192,000 MWh against a real all-time PJM record of ~165,000). Not our bug — genuine garbage from an "authoritative" source. Added plausibility bounds (`MAX_PLAUSIBLE_DEMAND_MWH`, `MAX_PLAUSIBLE_GENERATION_MWH`) to `ingest_demand`/`ingest_generation_mix` so future ingestion silently rejects and logs implausible values instead of writing them, and cleaned up the ~11 already-ingested bad rows directly. Found by working through the demo, not by proactively auditing — worth remembering that "the pipeline ran without errors" and "the data is correct" are different claims.

**Decisions made and why:**
- **Stress defined by historical demand percentile, not literal generation capacity** (flagged live before building) — true capacity data (EIA-860 nameplate generation) isn't ingested, and I didn't want to hardcode publicly-reported peak-capacity figures from memory into alert logic without a verifiable source. "Would rank in the top 1% of hours we've observed" is honest, fully backed by ingested data, and is a real methodology utilities use internally — but it is a genuine substitution for "% of capacity," not just a rename, so treat any capacity-flavored language in the eventual README carefully.
- **"Similar event" matches on temperature among the region's own past stress hours, not calendar proximity** — CAISO's similar event ended up being in June, not August/September, because it's matching the actual driving variable (temperature), not the season. Methodologically correct, but can read a little oddly ("comparing a September peak to a June event"); noted as a possible future refinement (e.g., blend temperature similarity with day-of-year proximity) rather than something to silently "fix" by weakening the match.
- **Demonstration uses each region's own real historical peak**, with the model fit on data strictly before it and the alert's demand-history/threshold also cut off before it — not a synthetic or cherry-picked scenario, and not leaking the event itself into its own baseline.

**What you should understand now (interview-ready):**
1. **A schema-level foreign key is a genericity test, not just a constraint** — the `regions` FK violation is exactly the kind of failure that proves whether "add a new region" is really a config change or was silently coupled to manual setup that only happened once, by hand, for the first region. This is the sort of gap that's invisible until you actually add a second instance of something.
2. **Never trust an external API's values just because the request succeeded** — a 200 response with a well-formed JSON body is not the same guarantee as "the data is correct." Validating plausible ranges on ingested values is a basic, non-optional part of any pipeline pulling from third-party sources, government or otherwise.
3. **Percentile-based thresholds vs. absolute capacity thresholds** — percentile thresholds are self-calibrating (automatically appropriate to each region's own scale, no manual tuning per region) but drift over time as the underlying distribution shifts (e.g., if demand structurally grows), and they can't tell you "how close to the physical limit are we," only "how unusual is this relative to our own history." Different question, different use case — good to be able to articulate which one you're actually answering.
4. **A single weather coordinate is a much bigger approximation for a huge multi-state RTO (PJM) than for a geographically concentrated one (CAISO, ERCOT)** — worth being able to say out loud unprompted, not something to let an interviewer catch you not having thought about.
5. **Why "the forecast under-predicted the actual extreme" doesn't invalidate the alert system** — an alerting system's job is to correctly flag "this will be unusually bad," not to pin down the exact magnitude. A system whose forecasts are directionally right but magnitude-conservative on tail events can still be operationally very useful; conflating "forecast accuracy" with "alert usefulness" is a subtle mistake worth being able to explain you *didn't* make.

**What's left / open:**
- Backtest results (Phase 2/3) have not been re-run for ERCOT/PJM yet — Phase 4 proved the *ingestion and alerting* pipeline generalizes, but whether LightGBM's ~3% MAPE win margin holds in Texas or the mid-Atlantic (vs. CAISO's specific climate) is still an open question, and a good candidate for a quick follow-up before the final README.
- `find_similar_historical_event`'s pure-temperature matching (no seasonal/day-of-year weighting) is a known simplification, noted above.
- True capacity-relative stress framing (EIA-860 integration) remains future work, not done here.
- The plausibility-bound cleanup was reactive (found via the demo, not a proactive audit) — worth a dedicated pass over all three regions' full history before the final case study, in case other EIA glitches are still sitting in the data unnoticed.
