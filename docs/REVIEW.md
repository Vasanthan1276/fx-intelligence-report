# FX Intelligence reliability review — 13 November 2026

Status: proposed on `review/fx-reliability-transparency`. No merge, deployment, account change or live-model change is authorised by this review.

## Existing design and what works

`main.py` fetches seven years of ECB daily EUR reference rates, converts them into SGD costs for USD, JPY (per 100), EUR, GBP, AUD, MYR and CHF, and calculates the frozen Phase 2C baseline. Market components are historical value, trend/timing, momentum and volatility (50/25/15/10). Full-coverage Opportunity combines 70% market with 30% macro; within macro the weights are 50% policy, 30% growth and 20% inflation. Missing macro components already reduce effective macro weight. This pre-existing behavior is preserved.

BIS supplies monthly policy rates; IMF DataMapper supplies current-/next-year growth and inflation forecasts, with Singapore as benchmark. Yahoo is a reasonableness check, not a scoring input. The model separates valuation, forward outlook and urgency. An attractive historical rate is not sufficient for a Buy: urgency affects the action within the opportunity band. Embedded policy calendars affect urgency and must therefore be treated as model inputs.

GDELT and official central-bank feeds form the Phase 3A.3 experiment. Relevance, direction semantics, evidence and source diversity are already considered. Shadow observations are logged separately with **zero recommendation weight**. Request pacing and short-lived GDELT caching exist already.

`dashboard.py` renders a static `index.html`, with detailed currency cards, explanations, a full scorecard, Chart.js history, baseline performance and shadow performance. GitHub Actions runs the primary and backup schedules at 16:30 and 17:30 UTC Monday–Friday (00:30 and 01:30 Singapore time Tuesday–Saturday). Pages publishes the main branch root. A same-market-date/same-Singapore-day check avoids recomputing the model.

The README contains the project roadmap. Phase 2C is deliberately frozen; Phase 3A.3 is complete as a shadow experiment; Phase 3B semantic/full-text work is conditional on evidence of value. This patch adds reliability work without advancing the model phase.

## Observed findings

| Finding | Evidence / consequence | Proposed change |
|---|---|---|
| ECB API intermittently returns HTTP 504 | [Failed 10 November run](https://github.com/Vasanthan1276/fx-intelligence-report/actions/runs/42909227871); update failed and render/commit were skipped | Bounded retries, source-level diagnostics, visible retained-snapshot state |
| Bare historical CSV is not the current download | At review, the old URL returned three legacy sample rows ending 2010-02-14; applying the seven-year cutoff yielded zero rows | Use ECB's published historical ZIP; validate contents, currency coverage, dates and rates |
| Static page conceals failed updates | Old page remains when job stops before rendering | Always attempt status rendering on failures; independently check GitHub job state and browser-time freshness |
| No distinction between rate date, model timestamp and last successful check | Same-date backup no-op has no dashboard heartbeat | Separate observation date, snapshot creation, last attempt and last successful check; no timestamp inflation |
| Recommendation table did not match implemented urgency conditions | For example 3.00–3.49 can be Wait, not always Light Accumulate | Correct documentation and add per-currency explanations; keep action function untouched |
| Shadow evaluator did not explicitly inspect logged `news_evidence_eligible` | Current sample has no count discrepancy, but future/legacy inconsistencies could matter | Additional evidence-gated audit with pending/excluded/missing/duplicate counts; retain original metrics for continuity |
| Exact creation timestamps absent from older logs | Cannot establish exact historical information availability or execution timing | Record timestamps prospectively; prominently label this limitation; do not invent historical timestamps |
| Chart errors only went to the console | Empty history or a missing CDN script leaves a blank chart | Visible errors with currency-selection retry |
| Long source box consumes the first screen | Important recommendation pushed down | Compact header, navigation and summary table; classic option preserves familiar details |

The official [ECB reference-rate downloads page](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) links `eurofxref-hist.zip` for time series and states its working-day publication cadence. During this review the ZIP had 7,135 observations from 1999-01-04 to 2026-11-12. A read-only API smoke check returned 1,793 rows for the requested seven-year window, also ending 2026-11-12. A real staged same-date check then completed without changing the model snapshot.

## Snapshot interpretation

The retained model snapshot was generated at **06:44 SGT on 13 November**, using **12 November 2026** rates. All seven actions are Wait. JPY ranks first at **3.49/5 opportunity**, with **3.11/5 urgency**, 100% macro coverage, 70% market / 30% macro effective weight, and a 0% suggested tranche. Under the existing function, opportunity 3.00–3.49 requires urgency ≥4.00 for Light Accumulate; otherwise Wait. Exceptional Historical Value is a valuation label, not an instruction to buy.

The snapshot's shadow evidence is ineligible for all seven currencies. This does not change any live action. The page exposes reported news-source failures and coverage separately.

## Performance evidence and limits

- Baseline: 84 logged market dates; 567 matured 1D currency observations, 7 pending and 14 missing logged entry rates. Missing entries are shown, not imputed. The 1D helpful-rate denominator is 357 decisive outcomes (206 helpful, 151 unhelpful), excluding 210 neutral outcomes.
- Shadow: 70 logged dates; 22 matured 1D evidence-eligible directional calls, of which only 10 have decisive movements (5 correct, 5 incorrect; 12 neutral). At 5D and 10D there are 20 matured and 2 pending eligible calls. Per horizon, 457 currency observations fail evidence checks and 11 are neutral signals.
- All older baseline and shadow log rows lack exact creation timestamps. These are retrospective reference-rate comparisons with overlapping horizons and correlated currencies, without spreads, fees or executable quote timing. The results do not demonstrate predictive value.
- The original performance files and every historical record remain byte-for-byte unchanged by this branch. The audit adds diagnostics, not a replacement model or an improved backtest claim.

## Tests and preview

Automated verification: **23 Python tests and 20 JavaScript tests pass**. Tests use isolated temporary data and no live trades or paid services.

| Area | Checks |
|---|---|
| Normal update | Seven currency outputs, optional-source degradation, complete snapshot promotion |
| ECB reliability | 504 recovery, timeout retry exhaustion, valid ZIP recovery, 404 fail-fast, malformed response, empty fallback, insufficient history, missing latest currency, non-positive/infinite/future/stale rates |
| Preservation | Total source failure and late computation failure leave existing model/history untouched; corrupt log cannot be silently reset; same-date no-op preserves model timestamp; recovery retains previous failure metadata |
| Frozen baseline | All output fields compared with original-code golden outputs for seven currencies under full, partial and missing macro coverage (21 scenarios); action threshold cases; changed shadow inputs have zero effect on live outputs |
| Validation | Neutral denominator, pending horizons, explicit evidence exclusion and duplicate-date detection |
| Dashboard scripts | Normal/stale/cached/failure states; overdue schedules; weekends, TARGET holidays and summer time; invalid/future dates; chart normal/empty/network/library/missing-currency states |

The golden fixture was captured from original commit `ab46feb6144ecf0ee68e7df4a0ebf55af60d73ac`, using a fixed clock and deterministic price/macro inputs. It protects existing behavior rather than asserting financial correctness.

A portable HTML preview contains the exact generated dashboard, embedded history and Chart.js. It is clearly labelled as an unpublished branch preview. The connected browser cannot reach the isolated local server; the cloud browser also cannot access it and rejects local-file navigation under its URL policy. Browser visual and mobile interaction checks therefore remain unverified. Script tests passed; a downloadable preview is provided for visual review. No hosted preview was deployed to bypass this limitation.

## Remaining limits and approval boundary

- A cancelled/timed-out runner, checkout failure or failed push can prevent writing health status. The independent public GitHub check and overdue warning cover this where browser network access permits; they cannot guarantee delivery.
- Browser job polling uses the unauthenticated public API once per page load and may be blocked or rate-limited. It explicitly displays unknown/unavailable rather than success in that case. Source and timestamp warnings still work locally.
- IMF release vintage and Yahoo quote timestamps are not recorded in older payloads. Do not infer freshness from their availability label. Collecting those timestamps is an appropriate follow-up.
- MYR's embedded calendar has passed its final listed 2026 event. Updating that calendar can affect urgency and requires separate approval.
- GDELT still shows rate limiting and thin coverage. This patch exposes it but does not expand source access or alter shadow semantics.
- After approval, merge will cause the existing main-branch GitHub Pages workflow to publish. No merge, deployment, model-weight change, currency transaction, credential exposure, new paid service or account change has been performed.
