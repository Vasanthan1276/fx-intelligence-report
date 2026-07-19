from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SIGNALS_PATH = DATA_DIR / "fx_signals.json"
OUTPUT_PATH = ROOT / "index.html"


def fmt_number(value, decimals=2, fallback="—"):
    if value is None:
        return fallback
    return f"{value:,.{decimals}f}"


def fmt_pct(value, decimals=2):
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def fmt_bps(value):
    if value is None:
        return "—"
    if abs(value) < 0.05:
        return "0 bp"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.0f} bp"


def score_class(score):
    if score >= 4.0:
        return "score-strong"
    if score >= 3.0:
        return "score-good"
    if score >= 2.25:
        return "score-neutral"
    return "score-weak"


def recommendation_class(score):
    if score >= 4.0:
        return "rec-buy"
    if score >= 3.0:
        return "rec-accumulate"
    if score >= 2.25:
        return "rec-wait"
    return "rec-avoid"


def rate_text(item):
    unit = item["unit"]
    symbol = html.escape(item["symbol"])
    rate = item["rate_sgd"]
    if unit == 1:
        return f"{symbol}1 = S${rate:,.4f}"
    return f"{symbol}{unit} = S${rate:,.4f}"


def buying_power_text(item):
    return f"S$1 buys {item['inverse_per_sgd']:,.3f} {item['code']}"


def level_text(item, value):
    if value is None:
        return "—"
    unit = item["unit"]
    symbol = html.escape(item["symbol"])
    if unit == 1:
        return f"S${value:,.4f}"
    return f"S${value:,.4f} per {symbol}{unit}"


def gap_text(item):
    gap = item.get("distance_to_buy_zone_pct")
    if gap is None:
        return "—"
    if gap <= 0:
        return "In buy zone"
    return f"Needs {gap:.1f}% better rate"


def policy_text(item):
    rate = item.get("policy_rate_pct")
    if rate is None:
        return "Unavailable"
    return f"{rate:.2f}%"


def outlook_text(current_year, current_value, next_year, next_value):
    parts = []
    if current_value is not None:
        parts.append(f"{current_year}: {current_value:.1f}%")
    if next_value is not None:
        parts.append(f"{next_year}: {next_value:.1f}%")
    return " · ".join(parts) if parts else "Unavailable"


def build_currency_cards(currencies):
    cards = []
    for rank, item in enumerate(currencies, start=1):
        market_drivers = "".join(
            f"<li>{html.escape(driver)}</li>" for driver in item.get("drivers", [])
        )
        macro_drivers = "".join(
            f"<li>{html.escape(driver)}</li>" for driver in item.get("macro_drivers", [])
        )
        validation = item.get("validation_status", "Unavailable")
        validation_diff = item.get("validation_difference_pct")
        validation_text = (
            validation if validation_diff is None else f"{validation} · {validation_diff:.2f}% diff"
        )
        buy_pct = item.get("suggested_buy_pct", 0)
        allocation = f"Suggested tranche: {buy_pct}%" if buy_pct else "Suggested tranche: 0%"
        macro_coverage = item.get("macro_coverage_pct", 0)
        effective_macro_weight = item.get("effective_macro_weight_pct", 0)

        growth_outlook = outlook_text(
            item.get("growth_current_year"),
            item.get("growth_current_pct"),
            item.get("growth_next_year"),
            item.get("growth_next_pct"),
        )
        inflation_outlook = outlook_text(
            item.get("inflation_current_year"),
            item.get("inflation_current_pct"),
            item.get("inflation_next_year"),
            item.get("inflation_next_pct"),
        )

        cards.append(
            f"""
        <article class="currency-card" data-code="{item['code']}" data-score="{item['score']}">
          <div class="card-topline">
            <div>
              <div class="rank">#{rank} opportunity</div>
              <h2>{item['code']} <span>{html.escape(item['name'])}</span></h2>
            </div>
            <div class="score-ring {score_class(item['score'])}">
              <strong>{item['score']:.2f}</strong><small>/ 5 overall</small>
            </div>
          </div>

          <div class="score-split">
            <div><span>Market & valuation</span><strong class="{score_class(item.get('market_score', item['score']))}">{item.get('market_score', item['score']):.2f}/5</strong></div>
            <div><span>Macro & policy</span><strong class="{score_class(item.get('macro_score', 2.5))}">{item.get('macro_score', 2.5):.2f}/5</strong></div>
          </div>

          <div class="recommendation {recommendation_class(item['score'])}">{html.escape(item['recommendation'])}</div>
          <div class="rate-primary">{rate_text(item)}</div>
          <div class="rate-secondary">{buying_power_text(item)}</div>

          <div class="mini-grid">
            <div><span>1 month</span><strong>{fmt_pct(item.get('change_30d_pct'))}</strong></div>
            <div><span>5Y cost percentile</span><strong>{fmt_number(item.get('percentile_5y'), 1)}%</strong></div>
            <div><span>Confidence</span><strong>{item['confidence']}% · {item['confidence_label']}</strong></div>
            <div><span>Data check</span><strong>{validation_text}</strong></div>
          </div>

          <div class="macro-box">
            <div class="macro-head">
              <div><span>Phase 2A macro intelligence</span><strong>{macro_coverage}% coverage</strong></div>
              <div class="macro-weight">{effective_macro_weight}% of final score</div>
            </div>
            <div class="macro-grid">
              <div>
                <span>Policy rate</span>
                <strong>{policy_text(item)}</strong>
                <small>6M {fmt_bps(item.get('policy_rate_6m_change_bps'))}</small>
              </div>
              <div>
                <span>Real GDP growth</span>
                <strong>{html.escape(growth_outlook)}</strong>
                <small>IMF WEO</small>
              </div>
              <div>
                <span>Inflation</span>
                <strong>{html.escape(inflation_outlook)}</strong>
                <small>IMF WEO</small>
              </div>
            </div>
          </div>

          <div class="zone-box">
            <div class="zone-head">
              <span>Current valuation zone</span>
              <strong>{html.escape(item.get('zone_status', '—'))}</strong>
            </div>
            <div class="zone-grid">
              <div><span>Buy zone</span><strong>≤ {level_text(item, item.get('buy_zone_upper_sgd'))}</strong></div>
              <div><span>Strong buy</span><strong>≤ {level_text(item, item.get('strong_buy_level_sgd'))}</strong></div>
              <div><span>Exceptional</span><strong>≤ {level_text(item, item.get('exceptional_buy_level_sgd'))}</strong></div>
              <div><span>5Y fair value</span><strong>{level_text(item, item.get('fair_value_sgd'))}</strong></div>
            </div>
            <div class="zone-gap">{html.escape(gap_text(item))}</div>
          </div>

          <div class="action-box">
            <div>
              <span>Model action</span>
              <strong>{html.escape(item['suggested_action'])}</strong>
            </div>
            <div class="allocation">{allocation}</div>
          </div>

          <div class="driver-columns">
            <div><h4>Market signals</h4><ul>{market_drivers}</ul></div>
            <div><h4>Macro signals</h4><ul>{macro_drivers}</ul></div>
          </div>
          <button class="chart-button" onclick="showCurrency('{item['code']}')">View 5-year chart</button>
        </article>
        """
        )
    return "\n".join(cards)


def build_table_rows(currencies):
    rows = []
    for item in currencies:
        growth = outlook_text(
            item.get("growth_current_year"),
            item.get("growth_current_pct"),
            item.get("growth_next_year"),
            item.get("growth_next_pct"),
        )
        rows.append(
            f"""
        <tr>
          <td><strong>{item['code']}</strong><span>{html.escape(item['name'])}</span></td>
          <td><div class="table-score {score_class(item['score'])}">{item['score']:.2f}</div></td>
          <td>{item.get('market_score', item['score']):.2f}</td>
          <td>{item.get('macro_score', 2.5):.2f}<span>{item.get('macro_coverage_pct', 0)}% coverage</span></td>
          <td><span class="table-rec {recommendation_class(item['score'])}">{html.escape(item['recommendation'])}</span></td>
          <td>{rate_text(item)}</td>
          <td>{fmt_number(item.get('percentile_5y'), 1)}%</td>
          <td>{policy_text(item)}<span>6M {fmt_bps(item.get('policy_rate_6m_change_bps'))}</span></td>
          <td>{html.escape(growth)}</td>
          <td>{level_text(item, item.get('buy_zone_upper_sgd'))}<span>{html.escape(gap_text(item))}</span></td>
          <td>{item['confidence']}%</td>
        </tr>
        """
        )
    return "\n".join(rows)


def main():
    if not SIGNALS_PATH.exists():
        raise FileNotFoundError("Run main.py first so data/fx_signals.json exists.")

    data = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    currencies = data["currencies"]
    best = currencies[0]
    generated = data.get("generated_at_utc", "")
    market_date = data.get("latest_market_date", "")
    primary_source = html.escape(data.get("primary_source", "Unknown"))
    policy_source = html.escape(data.get("policy_source", "Unavailable"))
    macro_source = html.escape(data.get("macro_source", "Unavailable"))
    validation_source = html.escape(data.get("validation_source", "Unavailable"))
    model_version = html.escape(data.get("model_version", ""))

    cards_html = build_currency_cards(currencies)
    rows_html = build_table_rows(currencies)

    best_market = best.get("market_score", best["score"])
    best_macro = best.get("macro_score", 2.5)
    best_macro_weight = best.get("effective_macro_weight_pct", 0)
    best_macro_driver = (
        best.get("macro_drivers", [""])[0]
        if best.get("macro_drivers")
        else "Macro-policy data is unavailable for this run."
    )

    html_page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#08111f">
<title>V FX Intelligence</title>
<script>
if ('scrollRestoration' in history) {{ history.scrollRestoration = 'manual'; }}
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg:#07101d;
  --panel:#0d1828;
  --panel2:#111f33;
  --line:#203249;
  --text:#edf5ff;
  --muted:#93a8c3;
  --cyan:#56d9f6;
  --green:#45dda3;
  --lime:#a5e45b;
  --amber:#f4c95d;
  --orange:#ff9f5a;
  --red:#ff6b7b;
  --purple:#b49cff;
  --shadow:0 20px 50px rgba(0,0,0,.28);
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:radial-gradient(circle at top right,#132a47 0,#07101d 38%,#050b14 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
a{{color:inherit}}
.container{{max-width:1440px;margin:0 auto;padding:28px 24px 60px}}
.topbar{{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:28px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.16em;color:var(--cyan);font-size:.76rem;font-weight:800;margin-bottom:8px}}
h1{{font-size:clamp(2rem,4vw,3.7rem);line-height:1;margin:0 0 10px;letter-spacing:-.04em}}
.subtitle{{color:var(--muted);max-width:760px;line-height:1.6;margin:0}}
.status-panel{{min-width:330px;background:rgba(13,24,40,.85);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow)}}
.status-panel div{{display:flex;justify-content:space-between;gap:16px;padding:5px 0;color:var(--muted);font-size:.8rem}}
.status-panel strong{{color:var(--text);font-weight:700;text-align:right;max-width:210px}}
.hero{{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-bottom:24px}}
.hero-card{{background:linear-gradient(135deg,rgba(22,49,80,.96),rgba(11,25,43,.96));border:1px solid #28425f;border-radius:24px;padding:26px;box-shadow:var(--shadow)}}
.hero-card h3{{margin:0 0 8px;font-size:1rem;color:var(--muted);font-weight:700}}
.hero-opportunity{{font-size:clamp(2rem,5vw,4.4rem);font-weight:900;letter-spacing:-.05em;margin:2px 0}}
.hero-opportunity span{{color:var(--cyan)}}
.hero-score{{display:flex;align-items:baseline;gap:10px;margin-top:10px;flex-wrap:wrap}}
.hero-score strong{{font-size:2.4rem}}
.hero-score span{{color:var(--muted)}}
.hero-split{{display:flex;gap:10px;flex-wrap:wrap;margin:15px 0 4px}}
.hero-split div{{background:#0a1727;border:1px solid #29445f;border-radius:12px;padding:9px 12px;color:var(--muted);font-size:.78rem}}
.hero-split strong{{color:var(--text);margin-left:5px}}
.hero-copy{{color:#c7d8ec;line-height:1.6;max-width:760px}}
.hero-macro{{color:#a9bdd4;line-height:1.55;font-size:.88rem;margin-top:8px}}
.hero-side{{background:rgba(13,24,40,.9);border:1px solid var(--line);border-radius:24px;padding:24px;box-shadow:var(--shadow)}}
.hero-side h3{{margin-top:0}}
.hero-side .big-action{{font-size:1.8rem;font-weight:900;color:var(--green);margin:8px 0}}
.hero-side p{{color:var(--muted);line-height:1.55}}
.section-header{{display:flex;justify-content:space-between;align-items:end;gap:20px;margin:34px 0 16px}}
.section-header h2{{margin:0;font-size:1.5rem}}
.section-header p{{margin:3px 0 0;color:var(--muted);font-size:.9rem}}
.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}
.currency-card{{background:rgba(13,24,40,.92);border:1px solid var(--line);border-radius:22px;padding:20px;box-shadow:var(--shadow);position:relative;overflow:hidden}}
.currency-card:before{{content:"";position:absolute;inset:0 auto auto 0;width:100%;height:3px;background:linear-gradient(90deg,var(--cyan),transparent);opacity:.7}}
.card-topline{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}}
.rank{{font-size:.74rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:800}}
.currency-card h2{{font-size:1.7rem;margin:6px 0 0}}
.currency-card h2 span{{display:block;font-size:.84rem;font-weight:600;color:var(--muted);margin-top:4px}}
.score-ring{{width:78px;height:78px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-direction:column;border:6px solid currentColor;background:#091321;flex:0 0 78px}}
.score-ring strong{{font-size:1.24rem;line-height:1}}
.score-ring small{{font-size:.57rem;color:var(--muted);margin-top:4px;text-align:center}}
.score-strong{{color:var(--green)}}.score-good{{color:var(--lime)}}.score-neutral{{color:var(--amber)}}.score-weak{{color:var(--red)}}
.score-split{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:15px}}
.score-split div{{background:#091421;border:1px solid #1a3047;border-radius:11px;padding:9px 10px}}
.score-split span{{display:block;color:var(--muted);font-size:.68rem;margin-bottom:4px}}
.score-split strong{{font-size:.9rem}}
.recommendation{{display:inline-flex;padding:6px 10px;border-radius:999px;font-size:.78rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase;margin-top:14px}}
.rec-buy{{background:rgba(69,221,163,.14);color:var(--green);border:1px solid rgba(69,221,163,.35)}}
.rec-accumulate{{background:rgba(165,228,91,.12);color:var(--lime);border:1px solid rgba(165,228,91,.3)}}
.rec-wait{{background:rgba(244,201,93,.12);color:var(--amber);border:1px solid rgba(244,201,93,.3)}}
.rec-avoid{{background:rgba(255,107,123,.12);color:var(--red);border:1px solid rgba(255,107,123,.3)}}
.rate-primary{{font-size:1.55rem;font-weight:900;margin-top:16px;letter-spacing:-.02em}}
.rate-secondary{{font-size:.9rem;color:var(--muted);margin-top:4px}}
.mini-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:18px 0}}
.mini-grid div{{background:#091421;border:1px solid #182a3f;border-radius:13px;padding:11px}}
.mini-grid span{{display:block;color:var(--muted);font-size:.72rem;margin-bottom:5px}}
.mini-grid strong{{font-size:.82rem}}
.macro-box{{margin:14px 0;background:linear-gradient(135deg,rgba(180,156,255,.07),rgba(86,217,246,.05));border:1px solid #2d3553;border-radius:15px;padding:13px}}
.macro-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;padding-bottom:10px;border-bottom:1px solid #27334d}}
.macro-head span{{display:block;color:var(--purple);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;font-weight:800}}
.macro-head strong{{display:block;font-size:.78rem;margin-top:3px}}
.macro-weight{{font-size:.68rem;color:var(--muted);text-align:right}}
.macro-grid{{display:grid;grid-template-columns:1fr;gap:8px;margin-top:10px}}
.macro-grid div{{background:#0a1625;border:1px solid #222f46;border-radius:10px;padding:9px}}
.macro-grid span{{display:block;color:var(--muted);font-size:.66rem;margin-bottom:4px}}
.macro-grid strong{{display:block;font-size:.76rem;line-height:1.35}}
.macro-grid small{{display:block;color:#7188a2;font-size:.65rem;margin-top:3px}}
.zone-box{{margin:14px 0;background:#091421;border:1px solid #1d354d;border-radius:14px;padding:13px}}
.zone-head{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding-bottom:10px;border-bottom:1px solid #1a2e43}}
.zone-head span{{color:var(--muted);font-size:.72rem}}
.zone-head strong{{font-size:.78rem;color:var(--cyan);text-align:right}}
.zone-grid{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:10px}}
.zone-grid div{{background:#0d1b2b;border:1px solid #1a2e43;border-radius:10px;padding:9px}}
.zone-grid span{{display:block;color:var(--muted);font-size:.67rem;margin-bottom:4px}}
.zone-grid strong{{font-size:.76rem}}
.zone-gap{{margin-top:9px;color:#bcd0e6;font-size:.72rem;font-weight:700}}
.action-box{{display:flex;justify-content:space-between;gap:12px;align-items:center;background:linear-gradient(135deg,rgba(86,217,246,.08),rgba(69,221,163,.06));border:1px solid #26445a;border-radius:14px;padding:13px 14px}}
.action-box span{{display:block;color:var(--muted);font-size:.72rem;margin-bottom:3px}}
.action-box strong{{font-size:.9rem}}
.allocation{{font-size:.75rem;font-weight:900;color:var(--cyan);white-space:nowrap}}
.driver-columns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:15px}}
.driver-columns>div{{background:#091421;border:1px solid #172b40;border-radius:12px;padding:10px}}
.driver-columns h4{{font-size:.69rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 6px}}
.driver-columns ul{{padding-left:16px;margin:0;color:#bfd0e4;font-size:.72rem;line-height:1.45}}
.driver-columns li+li{{margin-top:5px}}
.chart-button{{width:100%;margin-top:12px;background:#142a42;border:1px solid #274764;color:var(--text);border-radius:11px;padding:10px 12px;font-weight:800;cursor:pointer}}
.chart-button:hover{{background:#1a3552}}
.chart-panel{{background:rgba(13,24,40,.94);border:1px solid var(--line);border-radius:22px;padding:20px;box-shadow:var(--shadow);scroll-margin-top:16px}}
.chart-toolbar{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}}
.chart-toolbar h3{{margin:0}}
.chart-toolbar select{{background:#0a1523;color:var(--text);border:1px solid #2a4058;border-radius:10px;padding:9px 12px}}
.chart-wrap{{height:380px}}
.table-panel{{overflow:auto;background:rgba(13,24,40,.92);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}}
table{{width:100%;border-collapse:collapse;min-width:1450px}}
th,td{{padding:14px 16px;border-bottom:1px solid #1b2c41;text-align:left;font-size:.82rem;vertical-align:top}}
th{{position:sticky;top:0;background:#0d1928;color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.06em}}
td span{{display:block;color:var(--muted);font-size:.72rem;margin-top:3px}}
.table-score{{font-weight:900;font-size:1rem}}
.table-rec{{display:inline-block;padding:5px 8px;border-radius:999px;font-size:.7rem;font-weight:900}}
.methodology{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.method-card{{background:rgba(13,24,40,.9);border:1px solid var(--line);border-radius:16px;padding:16px}}
.method-card strong{{font-size:1.55rem;display:block;margin-bottom:6px;color:var(--cyan)}}
.method-card span{{color:var(--muted);font-size:.8rem;line-height:1.5}}
.notice{{margin-top:26px;padding:18px 20px;border:1px solid #34435a;background:rgba(17,31,51,.7);border-radius:16px;color:#b9c9dc;font-size:.84rem;line-height:1.6}}
footer{{color:#6f859e;font-size:.76rem;text-align:center;margin-top:26px}}
@media(max-width:1180px){{.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}.methodology{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:1050px){{.hero{{grid-template-columns:1fr}}.status-panel{{min-width:300px}}}}
@media(max-width:680px){{.container{{padding:20px 14px 40px}}.topbar{{display:block}}.status-panel{{margin-top:18px;min-width:0}}.cards{{grid-template-columns:1fr}}.methodology{{grid-template-columns:1fr}}.chart-wrap{{height:300px}}.mini-grid{{grid-template-columns:1fr 1fr}}.driver-columns{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="container">
  <header class="topbar">
    <div>
      <div class="eyebrow">Personal currency decision support · Phase 2A</div>
      <h1>V FX Intelligence</h1>
      <p class="subtitle">Ranks how attractive it is to convert Singapore dollars into foreign currencies. The overall 0–5 score now combines historical value and market timing with central-bank policy, growth and inflation intelligence.</p>
    </div>
    <div class="status-panel">
      <div><span>Market data</span><strong>{market_date}</strong></div>
      <div><span>Model</span><strong>{model_version}</strong></div>
      <div><span>FX source</span><strong>{primary_source}</strong></div>
      <div><span>Policy source</span><strong>{policy_source}</strong></div>
      <div><span>Macro source</span><strong>{macro_source}</strong></div>
      <div><span>Cross-check</span><strong>{validation_source}</strong></div>
    </div>
  </header>

  <section class="hero">
    <div class="hero-card">
      <h3>Best current opportunity</h3>
      <div class="hero-opportunity"><span>{best['code']}</span> · {html.escape(best['recommendation'])}</div>
      <div class="hero-score"><strong>{best['score']:.2f}/5</strong><span>{rate_text(best)}</span></div>
      <div class="hero-split">
        <div>Market <strong>{best_market:.2f}/5</strong></div>
        <div>Macro & policy <strong>{best_macro:.2f}/5</strong></div>
        <div>Macro weight today <strong>{best_macro_weight}%</strong></div>
      </div>
      <p class="hero-copy">{html.escape(best['drivers'][0] if best.get('drivers') else best['suggested_action'])}</p>
      <p class="hero-macro">Macro view: {html.escape(best_macro_driver)}</p>
    </div>
    <div class="hero-side">
      <h3>Suggested action</h3>
      <div class="big-action">{html.escape(best['suggested_action'])}</div>
      <p><strong>Current zone:</strong> {html.escape(best.get('zone_status', '—'))}<br>
      <strong>Buy-zone threshold:</strong> {level_text(best, best.get('buy_zone_upper_sgd'))}<br>
      <strong>Strong-buy threshold:</strong> {level_text(best, best.get('strong_buy_level_sgd'))}</p>
      <p>{best['suggested_buy_pct']}% of your planned discretionary conversion is the model's current suggested first tranche. The score is designed for staged buying rather than trying to predict one perfect FX bottom.</p>
    </div>
  </section>

  <div class="section-header">
    <div><h2>Currency opportunity ranking</h2><p>Highest combined Buy Score first. Market and macro scores remain visible separately.</p></div>
  </div>
  <section class="cards">{cards_html}</section>

  <div class="section-header">
    <div><h2>Five-year SGD cost history</h2><p>Lower cost generally means better value for an SGD buyer.</p></div>
  </div>
  <section class="chart-panel" id="chartSection">
    <div class="chart-toolbar">
      <h3 id="chartTitle">{best['code']} cost history</h3>
      <select id="currencySelect" onchange="showCurrency(this.value, false)">
        {''.join(f'<option value="{item["code"]}" {"selected" if item["code"] == best["code"] else ""}>{item["code"]} — {html.escape(item["name"])}</option>' for item in currencies)}
      </select>
    </div>
    <div class="chart-wrap"><canvas id="fxChart"></canvas></div>
  </section>

  <div class="section-header">
    <div><h2>Full scorecard</h2><p>Compare the combined score with the underlying market and macro intelligence.</p></div>
  </div>
  <section class="table-panel">
    <table>
      <thead><tr><th>Currency</th><th>Overall</th><th>Market</th><th>Macro</th><th>Signal</th><th>Current cost</th><th>5Y percentile</th><th>Policy</th><th>GDP outlook</th><th>Buy zone</th><th>Confidence</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </section>

  <div class="section-header">
    <div><h2>Phase 2A scoring model</h2><p>The Phase 1B market model is preserved so we can later measure whether the macro layer improves real-world results.</p></div>
  </div>
  <section class="methodology">
    <div class="method-card"><strong>70%</strong><span>Market intelligence when all macro data is available: historical value, trend, momentum and volatility.</span></div>
    <div class="method-card"><strong>30%</strong><span>Maximum macro-policy contribution to the final score. Missing data automatically reduces this weight.</span></div>
    <div class="method-card"><strong>50%</strong><span>Within the macro score: foreign central-bank policy-rate level and recent direction.</span></div>
    <div class="method-card"><strong>30%</strong><span>Within the macro score: IMF real-GDP growth outlook relative to Singapore.</span></div>
    <div class="method-card"><strong>20%</strong><span>Within the macro score: IMF inflation outlook relative to Singapore.</span></div>
  </section>

  <div class="notice"><strong>Important:</strong> The model does not invent a Singapore policy interest rate. Singapore monetary policy is exchange-rate-centred, so Phase 2A uses foreign central-bank policy rates while comparing IMF growth and inflation outlooks against Singapore. ECB reference rates are informational rates and may differ from the retail rate offered by your bank, card, money changer or transfer service. No score guarantees future currency direction.</div>
  <footer>Generated automatically by GitHub Actions · Last build {html.escape(generated)}</footer>
</div>

<script>
let historyData = null;
let chart = null;
const currencyMeta = {json.dumps({item['code']: {'name': item['name'], 'unit': item['unit'], 'symbol': item['symbol'], 'buyZone': item.get('buy_zone_upper_sgd'), 'strongBuy': item.get('strong_buy_level_sgd'), 'exceptional': item.get('exceptional_buy_level_sgd'), 'fairValue': item.get('fair_value_sgd')} for item in currencies})};

async function loadHistory() {{
  if (historyData) return historyData;
  const response = await fetch('data/fx_history.json', {{cache:'no-store'}});
  if (!response.ok) throw new Error('Could not load FX history data');
  historyData = await response.json();
  return historyData;
}}

async function showCurrency(code, shouldScroll = true) {{
  const select = document.getElementById('currencySelect');
  select.value = code;
  document.getElementById('chartTitle').textContent = `${{code}} cost history`;
  if (shouldScroll) {{
    document.getElementById('chartSection').scrollIntoView({{behavior:'smooth', block:'start'}});
  }}
  const data = await loadHistory();
  const filtered = data.records.filter(row => row[code] !== null && row[code] !== undefined);
  const labels = filtered.map(row => row.date);
  const values = filtered.map(row => row[code]);
  const meta = currencyMeta[code];
  const label = meta.unit === 1 ? `SGD per 1 ${{code}}` : `SGD per ${{meta.unit}} ${{code}}`;

  const ctx = document.getElementById('fxChart');
  if (chart) chart.destroy();
  const levelSeries = (value) => labels.map(() => value);
  const datasets = [
    {{label, data:values, borderWidth:2, pointRadius:0, tension:.16, borderColor:'#56d9f6', backgroundColor:'rgba(86,217,246,.10)', fill:true}}
  ];
  if (meta.buyZone !== null && meta.buyZone !== undefined) datasets.push({{label:'Buy-zone threshold', data:levelSeries(meta.buyZone), borderWidth:1.5, pointRadius:0, borderDash:[7,5], borderColor:'#a5e45b', fill:false}});
  if (meta.strongBuy !== null && meta.strongBuy !== undefined) datasets.push({{label:'Strong-buy threshold', data:levelSeries(meta.strongBuy), borderWidth:1.5, pointRadius:0, borderDash:[4,5], borderColor:'#45dda3', fill:false}});
  if (meta.exceptional !== null && meta.exceptional !== undefined) datasets.push({{label:'Exceptional threshold', data:levelSeries(meta.exceptional), borderWidth:1.2, pointRadius:0, borderDash:[2,5], borderColor:'#f4c95d', fill:false}});

  chart = new Chart(ctx, {{
    type:'line',
    data:{{labels, datasets}},
    options:{{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{{mode:'index', intersect:false}},
      plugins:{{legend:{{labels:{{color:'#c5d5e8'}}}}, tooltip:{{callbacks:{{label:(ctx)=>` S$${{ctx.parsed.y.toFixed(4)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#7188a2', maxTicksLimit:8}}, grid:{{color:'rgba(86,110,140,.10)'}}}},y:{{ticks:{{color:'#7188a2'}}, grid:{{color:'rgba(86,110,140,.12)'}}}}}}
    }}
  }});
}}

// Build the initial chart without moving the viewport. This fixes the previous
// behaviour where page load automatically jumped down to the chart section.
window.addEventListener('load', () => {{
  window.scrollTo({{top:0, left:0, behavior:'auto'}});
  showCurrency('{best['code']}', false).catch(err => console.error(err));
}});
</script>
</body>
</html>
"""

    OUTPUT_PATH.write_text(html_page, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
