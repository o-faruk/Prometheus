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

---

## Phase 5a — API backend (dashboard frontend pending)

**What's built and verified live:**
- **Batch-score, serve-from-DB architecture**: two new tables, `forecasts` and `alerts`, written by a new scoring job (`app/forecasting/score.py`) that runs after every hourly ingestion cycle (wired into `scheduler.py`). It fits `LightGBMForecaster` fresh each run and uses Open-Meteo's **real forward-looking forecast** (`fetch_forecast_hourly`, built in Phase 4) for the next 24h — not the perfect-foresight actual-temperature assumption used for backtesting. This closes that long-flagged caveat for the *live* path specifically; backtested accuracy numbers correctly keep the old methodology, since real historical forecast-vs-actual weather isn't available after the fact.
- A third new table, `model_accuracy`, stores backtest summary rows (one per model per run) so `run_backtest.py`'s results are queryable by the API instead of living only in CSVs.
- FastAPI app (`app/api/`) with six endpoints, all read-only, all DB-backed, none doing model inference in the request path: `/regions`, `/{region}/current`, `/{region}/forecast`, `/{region}/accuracy`, `/{region}/alerts`, `/{region}/predictions-history`. All tested end-to-end against real data for all three regions.
- Backtested and stored real `model_accuracy` numbers for ERCOT and PJM (closing a Phase 4 open item) — see below, this changed the story meaningfully.

**Real, important finding — LightGBM does not win everywhere:**

| Region | Best model | LightGBM MAPE | EIA's own forecast MAPE |
|---|---|---|---|
| CAISO | LightGBM | **2.94%** | 10.69% |
| ERCOT | **EIA's own forecast** | 3.08% | **1.99%** |
| PJM | LightGBM | **2.80%** | 3.69% |

For ERCOT specifically, EIA's own published day-ahead forecast beats our LightGBM model. This is a more credible, useful result than a universal win would have been — ERCOT is widely regarded as having a mature, well-resourced internal forecasting operation (a single-state, tightly-coupled market), which is a plausible explanation, though not confirmed. It also resolves part of the Phase 2/3 "why does EIA's forecast underperform" question: it doesn't, universally — CAISO's specific EIA series is the outlier (10.69% MAPE, far worse than ERCOT's 1.99% or PJM's 3.69%), not EIA forecasting in general. **This is exactly the kind of finding to lead with in the case-study README** — "our model wins 2 of 3 regions, and here's the honest story about the one where it doesn't" is a stronger, more defensible claim than "our model always wins."

**Decisions made and why:**
- **Batch-score to DB rather than fit-on-request** (explained live before building) — keeps expensive ML compute (~6s per model fit) out of the API request path entirely, matching how production forecasting systems are actually architected (scheduled scoring, not on-demand inference), and proves real service-boundary thinking rather than a monolith that happens to have two folders.
- **`/predictions-history` matches each resolved hour to the forecast run made closest to 24h before it** (not just "the most recent forecast covering that hour") — approximates genuine day-ahead forecast quality, consistent with how every other accuracy number in this project has been evaluated, rather than silently mixing in same-day short-horizon forecasts which would look artificially better.
- **A real bug found while wiring live scoring to the backtest-tested `LightGBMForecaster`**: `temperature_future` from a live Open-Meteo pull isn't pre-trimmed to start exactly after `origin` (it starts at local midnight), which collided with `temperature_history` and crashed on a pandas "duplicate labels" error during reindexing. The backtest harness never hit this because it always pre-sliced `temperature_future` to the exact forecast window before calling `predict()`. Fixed inside `LightGBMForecaster.predict()` itself (de-dupe, preferring the actual observation over the forecast for any overlapping hour) rather than pushing the fix onto every caller — the model should be robust to what it's handed, not trust caller discipline.

**What you should understand now (interview-ready):**
1. **Batch scoring vs. online inference** — a real architectural choice, not just "where do I put the code." Batch scoring trades immediacy (the forecast is at most an hour stale) for a fast, simple, horizontally-scalable read-only API and zero coupling between request latency and model complexity. Online inference trades that staleness away but ties API performance directly to model cost. Most forecasting products (weather, demand, traffic) use batch scoring for exactly this reason.
2. **A single strong backtest result should make you suspicious, not confident** — Phase 3's "LightGBM wins every horizon bucket" result, run on one region, looked like a clean story. Testing on two more regions immediately surfaced a counterexample. Generalization has to be checked, not assumed, even when — especially when — the first result looks great.
3. **Why per-region model comparison matters for a multi-region product** — a real deployment might reasonably serve EIA's own forecast for ERCOT and LightGBM for CAISO/PJM; "pick one model for everywhere" is a simplification, and `model_accuracy` being queryable per-region is what makes that kind of decision possible later instead of hardcoded.
4. **Defensive coding at a function boundary vs. defensive coding at every call site** — the `temperature_future` overlap bug could have been "fixed" by remembering to pre-trim it in `score.py`. Fixing it inside `LightGBMForecaster.predict()` instead means every future caller gets the correct behavior automatically, rather than depending on everyone who ever calls this function remembering an undocumented precondition.
5. **Why "last updated X minutes ago" needs a real timestamp, not a boolean** — `minutes_since_update` in `/current` is computed from the actual latest data timestamp, not "did the last ingest job succeed." A dashboard that shows "live" based on job success can lie confidently right up until the moment the upstream API silently stops returning fresh data.

**What's left / open:**
- No caching/rate-limiting on the API yet — fine for local/portfolio use, worth a mention as a known gap for the "what you'd do with more time" section of the final README, not worth building now for a demo-scale audience.
- CORS is wide open (`allow_origins=["*"]`) — reasonable for a public read-only API with no auth, but should be tightened to the real deployed frontend origin once that URL exists (Phase 6).
- Only `lightgbm` forecasts are stored/served live (not naive/Prophet) — intentional, since `model_accuracy` already carries the full comparison story for the accuracy chart, and storing three live forecast curves per hour per region isn't needed for anything the dashboard actually shows.

---

## Phase 5b — React dashboard, built from a user-provided mockup

**What's built and verified live:**
- User supplied a finished visual design made with a design tool ("Claude Design"), exported as `Prometheus Grid Ambient.dc.html` plus a runtime (`support.js`) and an earlier set of design explorations (`DESIGN.md`, alternate aesthetics). Read through the whole export rather than skimming — the file encodes a complete design system (colors, typography scale, spacing, component conventions), not just one screen.
- **The mockup was a static visual spec with fabricated data** — a fictional grid-frequency reading in Hz, fictional real-time $/MWh pricing, and a fake geographic "grid topology" node map with made-up substation names. None of that data exists in this project (no frequency sensor feed, no wholesale pricing ingestion, no geographic topology data). Rather than build convincing-looking fake widgets, each was replaced with something real:
  - "Grid Stability (Hz)" → **Grid Status** (real, from the alert system: NOMINAL/ELEVATED/CRITICAL)
  - "Real-Time Price ($/MWh)" → **Temperature** (real, from `/current`)
  - "Grid Topology" node map → **Generation Mix** donut (real, new `/​{region}/generation-mix` endpoint, built specifically for this)
  - Added a **Model Comparison** chart and **Predictions vs. Outcomes** table — both explicitly required by the original brief, absent from the mockup, now real (`/accuracy`, `/predictions-history`)
- Ported the mockup's animated WebGL "domain-warping" shader background as a real React component (`GridAmbientBackground.jsx`) — and made it functionally meaningful rather than purely decorative: it's tinted live by the region's actual current alert level (cyan=nominal, amber=elevated, rose=critical), not a design-tool toggle.
- Full region switching (CAISO/ERCOT/PJM) — every panel re-fetches and re-renders on tab change, confirmed by screenshotting all three regions.
- Stack: Vite + React + Recharts, proxying `/api/*` to the FastAPI backend in dev.

**Real bugs found via actual browser screenshots, not just code review** (screenshots are what surfaced all three):
1. **Region tabs showed EIA's internal codes** (`CISO`, `ERCO`) instead of the names anyone actually recognizes (`CAISO`, `ERCOT`) — both in the frontend header and in generated alert text server-side. Fixed with a small display-label mapping in both places (`SHORT_LABELS`), keeping `region_code` as the real identifier everywhere it's used as one.
2. **Timestamps rendered in the browser's local timezone, not the grid region's** — the exact same class of bug already caught twice in the backend (Prophet's seasonality, feature engineering), now recurring in the frontend. A dashboard for a Texas grid operator showing times in whatever timezone the browser happens to be in is wrong for the same underlying reason it was wrong in the forecasting code. Fixed with a shared `formatTime`/`formatDateTime` utility that always takes an explicit region timezone.
3. **Generation mix showed solar at -0.3%** — investigated before assuming it was a bug: confirmed via direct SQL that EIA's raw data really does report small negative solar generation overnight (self-consumption slightly exceeding zero output — the same category of real EIA quirk as the PJM data corruption found in Phase 4, just far more benign). A pie chart can't render a negative slice regardless, so it's floored at 0 for display only, with a visible note rather than silently hiding the real signed value.
4. Model comparison chart was clipping its 4th bar off the bottom of a too-short fixed-height panel — a plain layout bug, fixed by sizing the panel to fit its content.

**Decisions made and why:**
- **Chose Recharts** over Chart.js (both pre-approved by the original brief) — more idiomatic for React (declarative components vs. an imperative canvas API), composes cleanly with the mockup's exact styling via inline theming.
- **Batch-scored data only, no client-side model inference** — the frontend is a pure consumer of the Phase 5a API; it has no knowledge of how a forecast or alert was produced, which is the correct side of the service boundary for a dashboard.
- **Verified visually, not just "it compiles"** — used Playwright to actually launch the dev server and screenshot the rendered page (twice: once to catch the first round of bugs, again after fixing them), rather than trusting that matching CSS values to the mockup's source would look right. It didn't, the first time — the model-comparison clipping bug wouldn't have been caught by reading the code.

**What you should understand now (interview-ready):**
1. **A visual mockup is a spec for layout and feel, not a spec for what data exists** — treating "the mockup shows a number here" as license to display a fabricated number would have quietly undermined the entire project's honesty premise. Every widget's data source needs the same scrutiny whether it came from a design tool or from your own head.
2. **Screenshots catch a different class of bug than code review** — the timezone bug, the negative-solar display, and the clipped chart were all invisible reading the source; each needed the rendered page to notice. "It compiles and the types match" is not "it's correct."
3. **The same bug can recur across layers** — the UTC-vs-local-time mistake happened once in Prophet's seasonality (Phase 3), and independently again in the frontend's date formatting (Phase 5), because it's a property of the *problem domain* (grid behavior is inherently local-clock-relative), not a one-off coding slip. Recognizing "this is the same category of bug as before" is a different skill than just fixing each instance.
4. **Making decoration functional beats making it merely accurate** — the ambient background could have just been "a nice animation" (matching the mockup) or "correctly showing nominal/elevated/critical" (matching real data). Doing the latter turns pure visual flair into another real-time indicator, at zero extra cost once the alert-level plumbing already exists.
5. **Investigate before you fix — a weird number might be correct** — the instinct on seeing "-0.3%" should not be "that's obviously a bug, clamp it," it should be "why would this be negative, and is that itself informative." The EIA self-consumption explanation is more useful on the dashboard (as a note) than a silently-clamped 0.0% would have been.

**What's left / open:**
- Sidebar nav (Analysis/Alerts/Docs) is visual-only — only Dashboard is a real route, matching what the brief actually asked for; not pretending those pages exist.
- No loading skeletons/spinners — panels just show their empty-state text until data arrives. Fine for a portfolio demo, worth polishing for Phase 6.
- The "Export Data" button now does something real (client-side CSV export of the predictions-history table) rather than being purely decorative, but only covers that one table — could reasonably extend to other panels later.
- Still running against local dev servers (Vite dev + uvicorn, not a production build) — Phase 6 covers actually deploying both.

---

## Phase 6 — Production deployment + polish

**Live at:** https://129.158.44.62.nip.io

**What's built and verified live:**
- Graceful-degradation pass: `scheduler.py`'s hourly job now survives a fully-unreachable database without an unhandled crash trace (logs clearly, skips that cycle, tries again next hour), and the FastAPI app returns a clean 503 instead of an internal error when the DB is down.
- Production Docker setup: `backend/Dockerfile` (slimmed — no Prophet/cmdstan, since the live API and scheduler never import it, only the local-only `run_backtest.py` does), `docker-compose.prod.yml` (Postgres/TimescaleDB with no public port, API, scheduler, Caddy), and a `Caddyfile` that serves the built frontend and reverse-proxies `/api/*` to FastAPI — same-origin in production, so the dev-mode CORS wildcard never actually matters at runtime.
- Full commit history reconstructed and pushed to GitHub — the repo had accumulated six phases of work with a single "Add README" commit (nothing had been pushed since day one, since I only commit/push when asked and it hadn't come up). Rebuilt eight logical, phase-ordered commits with real historical file states where they mattered (dependency growth in `requirements.txt`, region rollout in `regions.py`, the append-only `NOTES.md` log), rather than one large dump.
- Actually deployed: Oracle Cloud (Always Free tier), Ubuntu 24.04, `VM.Standard.E2.1.Micro` (1 OCPU/1GB — see below for why not the Ampere shape originally planned), Docker Compose, Caddy with automatic HTTPS via `nip.io` (free wildcard DNS for the VM's raw IP, no domain purchase needed). Historical data backfilled for all three regions directly in production, and `model_accuracy` populated by running the real backtest (with Prophet) from a local machine against the production database over a temporary SSH tunnel — never installing Prophet on the tiny VM at all.

**Real, unglamorous problems solved along the way:**
1. **Oracle's free-tier Ampere (ARM) capacity was exhausted in every availability domain** in the Ashburn region — a known, common issue, not a configuration mistake. Fell back to the other Always Free shape (`VM.Standard.E2.1.Micro`, x86, 1 OCPU/1GB), which had capacity immediately.
2. **That fallback shape is far smaller than originally planned (12GB → 1GB RAM)**, which forced a genuinely useful architectural realization: Prophet/cmdstan (a heavy C++ compile) was only ever needed for the offline backtest script, never for the live API or scheduler. Splitting `requirements-prod.txt` from `requirements.txt` and dropping the cmdstan build step entirely shrank the production image from ~3GB to under 800MB and made building it on a 1GB box actually feasible, instead of a workaround for a workaround.
3. **Oracle's networking has two independent firewall layers** — the cloud-level Security List (which we had to add explicit ingress rules to for ports 80/443, since the VCN wizard only opens SSH by default) and the VM's own `iptables` rules (which block traffic even after the cloud layer allows it — a well-known Oracle-specific gotcha). Both had to be opened; missing either one silently blocks the exact same traffic with no obvious error message pointing at which layer is responsible.
4. **The production database is deliberately not exposed to the public internet** (no `ports:` mapping in `docker-compose.prod.yml`), which is correct security practice but meant the one-time backtest (needing Prophet, only installed locally) couldn't just connect directly. Solved with an SSH tunnel forwarding a local port to the database container's *internal* Docker IP through the VM — no compose file edits, no temporarily opening anything to the internet, fully reversible by just closing the tunnel.
5. **Only 3 objects on `git clone`** — the actual state of the GitHub remote was still just the initial README, discovered only when the VM's clone came back suspiciously small. Committed and pushed the full six-phase history (see above) before deployment could continue.

**Decisions made and why:**
- **Oracle Cloud Always Free over a paid VPS** (user's call, given real cost/time tradeoffs surfaced live) — genuinely $0/mo forever, at the cost of the capacity lottery and smaller free shapes described above. Worth knowing this tradeoff going in: free-tier ARM capacity in popular regions is a real, recurring friction point, not a one-off bad day.
- **Single VM running everything via Docker Compose, not split across Vercel + a backend host** — same-origin serving eliminates production CORS as a concern entirely, and keeps the whole deployment in one place to reason about, at the cost of the frontend and backend scaling together rather than independently (a non-issue at this traffic scale).
- **`nip.io` instead of a purchased domain** — free, immediate, and Caddy's automatic HTTPS works against it exactly as it would against a real domain, since it's genuine, resolvable DNS, not a hack that skips certificate validation.

**What you should understand now (interview-ready):**
1. **"Free tier" often means "free, if you can get the capacity"** — Oracle's Always Free Ampere allocation is real, but contended in popular regions; a production deployment plan should have a fallback shape/region in mind rather than assuming the first choice will provision on the first try.
2. **Split your dependencies by what actually runs where, not by what the project uses anywhere** — `requirements.txt` (dev/backtesting) vs. `requirements-prod.txt` (live serving) isn't duplication, it's making the real dependency graph of the *deployed* system visible and small, which directly determined whether a 1GB machine could build the image at all.
3. **Cloud firewalls are usually layered, and every layer fails silently** — a request being dropped gives you no signal about *which* layer blocked it (cloud security group vs. host firewall vs. application). Debugging this requires knowing both layers exist, not just retrying the same fix.
4. **An SSH tunnel is a general tool for "run this one thing against that remote resource, safely, temporarily"** — forwarding a local port to a container's internal IP (not just the host's exposed ports) let a one-time offline job reach a deliberately-unexposed production database without changing what's actually exposed to the internet, and without leaving anything open afterward.
5. **Git history is a deliverable, not a byproduct** — reconstructing six phases of accumulated work into real, meaningful, phase-ordered commits (rather than one dump) took real effort, but it's exactly the artifact an interviewer said they wanted to see, and doing it after the fact honestly (grouping by when things were actually built, not fabricating a false day-by-day timeline) is a legitimate, common practice, not a shortcut.

**What's left / open, honestly:**
- `POSTGRES_PASSWORD` in production is a placeholder (`prometheus_prod_change_me`) — fine for a portfolio demo behind a non-exposed database, but would need a real secret in any setting where it mattered.
- The VM has no automated backups of the TimescaleDB volume — acceptable for a demo (all data is re-fetchable from EIA/Open-Meteo by re-running the backfill), not acceptable for anything with data that can't be regenerated.
- No monitoring/alerting on the deployment itself (is the scheduler still running? did a container crash and not restart?) — `restart: unless-stopped` handles simple crashes, but there's no notification if something silently stops working.
- 1GB of RAM is a real, ongoing constraint — comfortable for what's running today, but something to watch if the scope grows (a 4th region, more frequent scoring, etc.).
- This NOTES.md log, kept honestly phase-by-phase including the mistakes, *is* the answer to "walk me through how you built this" — that was the point of keeping it throughout, not just at the end.

**Post-launch incident: a real fix got un-fixed by the history reconstruction, and it took a live outage to notice.**

Shortly after going live, forecasts and alerts weren't populating for any region — every hourly scoring attempt was silently failing with `ValueError: cannot reindex on an axis with duplicate labels`. This is the *exact* bug Phase 5 already found and fixed (`temperature_future` from a live weather pull overlapping `temperature_history`, fixed by de-duplicating inside `LightGBMForecaster.predict()`). Diagnosing it live, against production, took a genuinely long back-and-forth: checked for duplicate rows in `weather_observations` directly (none), reproduced `fit()`/`predict()` in isolation for each region (CISO failed, ERCO/PJM didn't — at that specific moment), traced the exact reindex call site to `features.py`'s `temperature.reindex(origins)`, and manually replicated `LightGBMForecaster.predict()`'s internals step-by-step until the dedup step showed 0 duplicates *when tested in isolation* — yet the same code crashed moments later through the real call path. That inconsistency was the tell: it meant the *actual deployed code* didn't match what was being reasoned about on paper.

The real cause: while reconstructing this repo's git history earlier in Phase 6 (to give it a real, phase-ordered commit log instead of one giant dump), the Phase 3 (pre-fix) version of `lightgbm_model.py` was written out for that historical commit — and no later commit ever re-applied the Phase 5 dedup fix on top of it. The fix existed in this conversation's history and in NOTES.md's own Phase 5 write-up, but not in the file that actually got committed, built into the Docker image, and deployed.

**Why this is worth understanding, not just fixing:**
1. **Reconstructing history from memory is real engineering work with real failure modes** — it's not a mechanical copy-paste, it's re-deriving many file states by hand, and a single dropped edit silently regresses a bug that was already found and fixed. The fix here was documented in prose (NOTES.md) but that documentation didn't get cross-checked against the actual file contents being committed.
2. **A bug that "should be fixed" and isn't is worse than one that was never fixed** — the team believes the risk is handled, so nothing watches for it. This is exactly why post-deployment smoke-testing of the *actual* running system (not just "the code should do X") matters, independent of how confident you are in what the code says.
3. **Diagnosing a live, remote, intermittent failure is a different skill than debugging locally** — no debugger, output only via whatever you think to print, each round-trip costing real time (a fit takes ~15 minutes on this hardware) and every hypothesis has to be tested by actually running something, not stepping through. Ruling out causes systematically (raw data → isolated reproduction → exact call-path tracing) was slower but more reliable than guessing.
4. **The inconsistency between "works in isolation" and "fails through the real path" was the actual clue** — when a manual reproduction succeeds but the real system still fails with identical inputs, the right conclusion isn't "it's flaky," it's "the two aren't running the same code." That reframing is what led to finding the git history gap instead of continuing to chase a phantom race condition.

Fixed by restoring the dedup line, committing and pushing normally (not amending or force-pushing over the flawed history — the reconstruction commits stay as an honest record, this is a new commit on top, exactly like any other bug found after the fact), rebuilding just the `api` and `scheduler` containers, and re-verifying end-to-end on the live site. All three regions now score successfully, including via the scheduler's own unattended hourly run, not just manual triggers.
