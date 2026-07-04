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
