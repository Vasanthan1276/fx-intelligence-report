# V FX Intelligence

A personal foreign-exchange decision-support dashboard for an SGD-based buyer.

## Phase 1

Tracks:

- USD — US Dollar
- JPY — Japanese Yen
- EUR — Euro
- GBP — British Pound
- AUD — Australian Dollar
- MYR — Malaysian Ringgit

The model produces a **0–5 Buy Score** using:

- 55% historical value
- 25% trend and timing
- 15% momentum
- 5% volatility

The score is designed to answer: **How attractive is it to convert SGD into this foreign currency now, relative to its own history?**

## Data sources

- Primary scoring data: ECB daily reference-rate history, transformed into SGD cross-rates.
- Secondary validation: Yahoo Finance snapshot when available.

The secondary source is used only as a reasonableness check. It does not drive the score.

## Files

- `main.py` — downloads rates, calculates indicators and scores, and updates JSON data.
- `dashboard.py` — builds the static GitHub Pages dashboard.
- `data/fx_signals.json` — latest intelligence report.
- `data/fx_history.json` — five years of SGD cost history for charts.
- `data/score_log.json` — daily score history for future backtesting.
- `.github/workflows/update-fx.yml` — automatic scheduled update.

## GitHub setup

1. Create a new public repository, suggested name: `fx-intelligence-report`.
2. Upload all files and folders from this starter package to the repository root.
3. Open **Actions** and run **Update FX Intelligence** manually once.
4. After the workflow succeeds, open **Settings → Pages**.
5. Under **Build and deployment**, select **Deploy from a branch**.
6. Select branch **main** and folder **/(root)**, then save.
7. GitHub will show the published Pages URL.

## Automatic update schedule

The workflow runs at **16:30 UTC Monday–Friday**, which is **00:30 Singapore time on the following day**. The workflow can also be run manually at any time.

## Recommendation scale

- 4.50–5.00: Exceptional Buy
- 4.00–4.49: Buy
- 3.50–3.99: Accumulate
- 3.00–3.49: Light Accumulate
- 2.25–2.99: Wait
- 1.50–2.24: Expensive
- 0.00–1.49: Avoid

Suggested tranche percentages are staging guidance, not financial advice.

## Planned next phases

1. Backtest score performance after enough live observations have accumulated.
2. Add macro and central-bank policy scoring.
3. Add event-risk and news intelligence.
4. Add personal purchase goals and deadline-based staged-buy plans.
5. Add an additional independent SGD-focused reference source where practical.
