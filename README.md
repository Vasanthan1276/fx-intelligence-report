# V FX Intelligence

A personal foreign-exchange decision-support dashboard for an **SGD-based buyer**, hosted on GitHub Pages and updated automatically with GitHub Actions.

The project answers two different questions:

1. **Opportunity** — is the current SGD exchange rate attractive relative to history and the macro backdrop?
2. **Urgency** — if the rate is attractive, is there evidence that the opportunity may disappear soon?

The current core recommendation model is **frozen at Phase 2C** so its live performance can be measured consistently. Phase 3A news/event intelligence runs separately in **shadow mode** and has **0% weight** in recommendations.

## Currency universe

The dashboard currently tracks:

| Currency | Name | Display convention |
|---|---|---|
| USD | US Dollar | S$ per US$1 |
| JPY | Japanese Yen | S$ per ¥100 |
| EUR | Euro | S$ per €1 |
| GBP | British Pound | S$ per £1 |
| AUD | Australian Dollar | S$ per A$1 |
| MYR | Malaysian Ringgit | S$ per RM1 |
| CHF | Swiss Franc | S$ per CHF1 |

Lower SGD cost means the foreign currency is cheaper for an SGD buyer.

## Current model architecture

### Phase 2C — frozen recommendation baseline

The Phase 2C model remains the sole source of:

- Opportunity Score
- Forward Outlook
- Buy Urgency
- Recommendation
- Suggested staged-buy tranche

The core weights are deliberately frozen while live results accumulate.

### Opportunity Score

With complete macro data:

- **70% Market & Valuation**
- **30% Macro & Policy**

#### Market & Valuation score

- 50% historical value
- 25% trend and timing
- 15% momentum
- 10% volatility

Historical value uses 1-year, 3-year and 5-year context, with greater weight on the longer history.

#### Macro & Policy score

- 50% central-bank policy
- 30% growth outlook
- 20% inflation outlook

Singapore is the benchmark economy because the decision is whether to convert SGD into another currency. MAS is treated differently from conventional policy-rate central banks because Singapore monetary policy is primarily exchange-rate based.

### Forward Outlook

The model separately estimates forward pressure using:

- model-implied central-bank policy bias
- recent FX momentum
- 7-day, 30-day and 90-day movement
- moving-average structure

This is **model-implied**, not a futures-market probability.

### Buy Urgency

Buy Urgency is separate from Opportunity. A currency can be attractive without being urgent.

Urgency currently considers:

- 30% forward policy bias
- 30% forward FX momentum
- 20% valuation rarity
- 20% upcoming policy-event setup

This prevents a high-urgency signal from turning an unattractive currency into a Buy.

## Historical value zones

The dashboard calculates dynamic levels from the rolling five-year SGD-cost distribution.

- **Exceptional Historical Value** — approximately the cheapest 10% of the five-year distribution
- **Strong Historical Value** — approximately the cheapest 20%
- **Attractive Historical Value** — approximately the cheapest 35%
- **Fair Value** — five-year median

These are valuation labels, not standalone recommendations.

For example, a currency can be at **Exceptional Historical Value** while the action remains **Wait** if macro or timing signals are unfavourable.

## Recommendation scale

| Opportunity Score | Recommendation |
|---|---|
| 4.50–5.00 | Exceptional Buy |
| 4.00–4.49 | Buy |
| 3.50–3.99 | Accumulate |
| 3.00–3.49 | Light Accumulate |
| 2.25–2.99 | Wait |
| 1.50–2.24 | Expensive |
| 0.00–1.49 | Avoid |

Suggested tranche percentages are staged-conversion guidance, not financial advice.

## Phase 3A.3 — news & event shadow intelligence

Phase 3A.3 is an **experiment**. It is displayed and logged separately and has **0% weight** in the frozen Phase 2C recommendation.

The purpose is to test whether news/event information can add useful leading information before it is ever allowed to influence a Buy/Wait decision.

### Phase 3A.3 safeguards

The current shadow layer includes:

- hard target-currency relevance filtering
- English-language headline interpretation
- strict official central-bank content filtering
- pair-aware cross-currency direction semantics
- context-aware monetary-policy wording
- minimum directional-evidence rules
- source-diversity requirements
- GDELT request pacing and short-lived caching
- 1-day, 5-day and 10-day shadow-performance measurement

### Pair-aware direction semantics

The classifier interprets explicit currency relationships from the target currency's point of view.

Examples:

- `US dollar weakens against Japanese yen` → **JPY strengthening**
- `GBP rises versus AUD` → **AUD weakening**
- `USD/SGD falls` → **USD weakening**
- `EUR/CHF rises` → **CHF weakening**

This avoids the earlier proximity-keyword error where a verb associated with one currency could accidentally be assigned to the other currency in the headline.

### Official-source relevance gate

Being published by a central bank is not enough by itself.

Administrative material such as calendars, accessibility notices, event schedules or procurement items is rejected unless the content also contains a genuine monetary-policy, rate, inflation, growth, labour-market, FX or related macro signal.

### Minimum evidence rule

A directional news call is eligible for shadow validation only when coverage is **Strong** or **Adequate** and the evidence gate passes.

The gate requires either:

- at least two relevant directional items from multiple sources, or
- at least one directional official item plus one independent directional media item

Thin or unavailable coverage cannot create a validated directional prediction.

### Headline confidence

`Headline confidence` measures:

- amount of directional coverage
- source diversity
- official-source participation
- article relevance
- directional agreement

It is **not** the probability that the currency will move in the predicted direction.

### Shadow performance

Phase 3A.3 news calls are evaluated after:

- 1 trading day
- 5 trading days
- 10 trading days

Tiny future movements inside ±0.10% are treated as neutral rather than correct/incorrect.

Because Phase 3A.3 fixes direction semantics and official-source admission materially, its shadow-performance series starts clean rather than mixing flawed earlier Phase 3A.2 calls into the validation sample.

## Baseline performance tracking

The frozen Phase 2C model is independently evaluated after:

- 1 trading day
- 5 trading days
- 10 trading days
- 20 trading days

The dashboard reports whether the historical recommendation was retrospectively helpful and the average action benefit.

These figures are monitoring statistics, not proof of future predictive accuracy. Small sample sizes should be interpreted cautiously.

## Data sources

### Exchange rates

**Primary:** European Central Bank daily reference-rate history, transformed into SGD cross-rates.

**Secondary validation:** Yahoo Finance market snapshot when available.

Yahoo validation is a reasonableness check only and does not drive the core score.

### Central-bank policy rates

BIS central-bank policy-rate series.

### Growth and inflation

IMF World Economic Outlook / DataMapper.

### Policy calendars

Embedded official 2026 meeting dates for:

- Federal Reserve
- Bank of Japan
- European Central Bank
- Bank of England
- Reserve Bank of Australia
- Bank Negara Malaysia
- Swiss National Bank

### News/event shadow layer

- GDELT DOC API for recent media coverage
- official central-bank feeds and official-domain fallbacks

GDELT responses are paced and cached for a short period to reduce duplicate requests and rate-limit failures during the backup workflow run.

## Main files

- `main.py` — downloads data, calculates scores, updates performance logs and builds the Phase 3A shadow dataset
- `dashboard.py` — generates the static GitHub Pages dashboard
- `index.html` — generated dashboard
- `.github/workflows/update-fx.yml` — scheduled GitHub Actions workflow
- `requirements.txt` — Python dependencies

## Generated data files

- `data/fx_signals.json` — latest complete intelligence snapshot
- `data/fx_history.json` — five-year SGD-cost history used by charts
- `data/score_log.json` — frozen Phase 2C daily score history
- `data/performance.json` — 1/5/10/20-day Phase 2C performance
- `data/macro_snapshot.json` — latest macro/policy data
- `data/policy_calendar.json` — policy-event calendar snapshot
- `data/news_shadow.json` — latest Phase 3A.3 shadow intelligence
- `data/news_shadow_log.json` — daily shadow-signal history
- `data/news_shadow_performance.json` — 1/5/10-day shadow validation
- `data/gdelt_query_cache.json` — short-lived query cache used to reduce repeated GDELT calls

## Automatic update schedule

GitHub Actions runs on weekdays:

- **Primary:** 16:30 UTC = 00:30 Singapore time the following day
- **Backup:** 17:30 UTC = 01:30 Singapore time

The workflow can also be run manually from the **Actions** tab.

The backup run exists for resilience. If the primary run has already completed successfully, the second run should normally result in no meaningful new model data.

## GitHub Pages setup

The repository is designed to publish directly from the `main` branch root:

1. Open **Settings → Pages**
2. Choose **Deploy from a branch**
3. Select `main`
4. Select `/(root)`
5. Save

## Interpretation and limitations

This is a personal decision-support model, not a guaranteed FX forecasting system.

Important limitations:

- exchange rates can move sharply on unexpected events
- historical cheapness does not guarantee future appreciation
- macro relationships can remain disconnected from FX for long periods
- Phase 3A is still headline/summary heuristic analysis rather than full-text semantic analysis
- explicit pair relationships are now handled, but complex multi-asset or conditional headlines may still be misread
- official and market reference rates can differ from retail conversion rates and spreads
- performance statistics need substantially more observations before they can be treated as reliable

The intended use is **staged currency buying with transparent evidence**, rather than trying to predict the exact market bottom.

## Current development status

- Phase 1 — historical valuation and technical model ✅
- Phase 1B — dynamic historical buy zones ✅
- Phase 2A — macro and central-bank layer ✅
- Phase 2B — Buy Urgency and event-risk separation ✅
- Phase 2C — forward outlook and confidence framework ✅
- Phase 2C baseline freeze and performance tracking ✅
- CHF added to the currency universe ✅
- Phase 3A — news/event shadow mode ✅
- Phase 3A.1 — coverage hardening ✅
- Phase 3A.2 — relevance filtering ✅
- **Phase 3A.3 — direction semantics, official-source quality and GDELT pacing/cache ✅**
- Future Phase 3B — deeper semantic/full-text news interpretation, only if shadow performance demonstrates value
