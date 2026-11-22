# Live ingestion latency (2026-10-31 07:04 UTC)

Target `maribyrnong-environmental-monitor-gytqp85h8-asli6.vercel.app` (POST /api/ingest), device `SIM-01`: 100 readings replayed from `mcc---1_1_device_17_variables_RTG7DUBK4D.csv` (local day 2025-02-19 to 2025-02-25), one every 1 s, each re-stamped to the current time (SEC-03 replay window).
Times are measured on the client from sending each request to receiving its response, so they include the network path from the measuring machine.

| Measure | Value |
|---|--:|
| First request (after the Preview was idle; may include a cold start) | 6872 ms |
| Warm requests | 99 |
| Warm p50 | 272 ms |
| Warm p95 | 321 ms |
| Warm p99 | 367 ms |
| Warm max | 367 ms |
| Non-200 responses | 0 |

**Result: PASS** (warm p95 321 ms against the 2 s target).

HTTP status counts: 200: 100.
Outcomes: stored: 100.

Out-of-range TEST values (deliberately injected; expected: HTTP 200, the value rejected and logged, the rest of the reading stored):

| Reading | Field | Sent | HTTP | Rejected by the API |
|--:|---|--:|--:|---|
| 25 | temperature | 95.0 | 200 | temperature_c |
| 50 | temperature | 95.0 | 200 | temperature_c |
| 75 | temperature | 95.0 | 200 | temperature_c |
| 100 | temperature | 95.0 | 200 | temperature_c |

## Notes (added when filing the report)
- **Cold start.** The first request came after the Preview and the Neon `dev` compute had both been idle for 10 minutes. At 6,872 ms it is **over** the 2 s target: it includes starting the Vercel function, loading the Python dependencies (pandas, the data pipeline) and waking the Neon compute. Every following request took under 0.4 s. The 2 s target is assessed on warm requests (p95), and the cold start is reported separately, as BUILD_PROMPT §6 asks.
- **Environment.** Preview deployment of branch `phase-6` (`9c1fef3`, Vercel `syd1`) on the Neon `dev` branch, run from a team member's machine. Production and Neon `main` were not touched.
- **Readings.** 100 real MCC-01 readings from its first days in the file (sparse at the start, so they span 2025-02-19 to 2025-02-25). Each was sent with the current time. Every 25th reading carried a deliberate out-of-range test temperature (95.0 °C).
- **Database check afterwards** (Neon `dev`, read-only query):
  - `readings`: 100 rows for SIM-01;
  - `aggregates`: 27 rows (hour, day and month for 9 variables); the hourly temperature bucket has n = 96 (100 minus the 4 rejected test values);
  - `error_log`: exactly 4 `out_of_range` entries (`temperature_c`, raw value 95.0), one per test value, and nothing else;
  - every one of the 100 requests answered HTTP 200.
- **First attempt (not used).** An earlier run at 04:27 UTC sent only 65 readings (one day) and, after its 6.8 s cold start, sent some readings within the same second, which the API correctly answered as duplicates. The simulator was fixed (it now waits at least 1 s from the previous send and never repeats a second), regression tests were added, and those test rows were deleted from `dev` before this run.
- **Afterwards** SIM-01 was decommissioned and its test rows deleted from `dev` (both audited), so it never appears in analysis.
