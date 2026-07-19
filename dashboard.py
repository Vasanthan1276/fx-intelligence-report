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


def fmt_pct(value):
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


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
    code = item["code"]
    rate = item["rate_sgd"]
    if unit == 1:
        return f"{symbol}1 = S${rate:,.4f}"
    return f"{symbol}{unit} = S${rate:,.4f}"


def buying_power_text(item):
    return f"S$1 buys {item['inverse_per_sgd']:,.3f} {item['code']}"


def build_currency_cards(currencies):
    cards = []
    for rank, item in enumerate(currencies, start=1):
        drivers = "".join(f"<li>{html.escape(driver)}</li>" for driver in item.get("drivers", []))
        validation = item.get("validation_status", "Unavailable")
        validation_diff = item.get("validation_difference_pct")
        validation_text = validation if validation_diff is None else f"{validation} · {validation_diff:.2f}% diff"
        buy_pct = item.get("suggested_buy_pct", 0)
        allocation = f"Suggested tranche: {buy_pct}%" if buy_pct else "Suggested tranche: 0%"

        cards.append(f"""
        <article class="currency-card" data-code="{item['code']}" data-score="{item['score']}">
          <div class="card-topline">
            <div>
              <div class="rank">#{rank} opportunity</div>
              <h2>{item['code']} <span>{html.escape(item['name'])}</span></h2>
            </div>
            <div class="score-ring {score_class(item['score'])}">
              <strong>{item['score']:.2f}</strong><small>/ 5</small>
            </div>
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

          <div class="action-box">
            <div>
              <span>Model action</span>
              <strong>{html.escape(item['suggested_action'])}</strong>
            </div>
            <div class="allocation">{allocation}</div>
          </div>

          <ul class="drivers">{drivers}</ul>
          <button class="chart-button" onclick="showCurrency('{item['code']}')">View 5-year chart</button>
        </article>
        """)
    return "\n".join(cards)


def build_table_rows(currencies):
    rows = []
    for item in currencies:
        rows.append(f"""
        <tr>
          <td><strong>{item['code']}</strong><span>{html.escape(item['name'])}</span></td>
          <td><div class="table-score {score_class(item['score'])}">{item['score']:.2f}</div></td>
          <td><span class="table-rec {recommendation_class(item['score'])}">{html.escape(item['recommendation'])}</span></td>
          <td>{rate_text(item)}</td>
          <td>{fmt_pct(item.get('change_30d_pct'))}</td>
          <td>{fmt_number(item.get('percentile_5y'), 1)}%</td>
          <td>{item['suggested_buy_pct']}%</td>
          <td>{item['confidence']}%</td>
        </tr>
        """)
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
    validation_source = html.escape(data.get("validation_source", "Unavailable"))
    model_version = html.escape(data.get("model_version", ""))

    cards_html = build_currency_cards(currencies)
    rows_html = build_table_rows(currencies)

    html_page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#08111f">
<title>V FX Intelligence</title>
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
  --shadow:0 20px 50px rgba(0,0,0,.28);
}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(circle at top right,#132a47 0,#07101d 38%,#050b14 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
a{{color:inherit}}
.container{{max-width:1440px;margin:0 auto;padding:28px 24px 60px}}
.topbar{{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:28px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.16em;color:var(--cyan);font-size:.76rem;font-weight:800;margin-bottom:8px}}
h1{{font-size:clamp(2rem,4vw,3.7rem);line-height:1;margin:0 0 10px;letter-spacing:-.04em}}
.subtitle{{color:var(--muted);max-width:760px;line-height:1.6;margin:0}}
.status-panel{{min-width:280px;background:rgba(13,24,40,.85);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow)}}
.status-panel div{{display:flex;justify-content:space-between;gap:16px;padding:6px 0;color:var(--muted);font-size:.86rem}}
.status-panel strong{{color:var(--text);font-weight:700;text-align:right}}
.hero{{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-bottom:24px}}
.hero-card{{background:linear-gradient(135deg,rgba(22,49,80,.96),rgba(11,25,43,.96));border:1px solid #28425f;border-radius:24px;padding:26px;box-shadow:var(--shadow)}}
.hero-card h3{{margin:0 0 8px;font-size:1rem;color:var(--muted);font-weight:700}}
.hero-opportunity{{font-size:clamp(2rem,5vw,4.4rem);font-weight:900;letter-spacing:-.05em;margin:2px 0}}
.hero-opportunity span{{color:var(--cyan)}}
.hero-score{{display:flex;align-items:baseline;gap:10px;margin-top:10px}}
.hero-score strong{{font-size:2.4rem}}
.hero-score span{{color:var(--muted)}}
.hero-copy{{color:#c7d8ec;line-height:1.6;max-width:760px}}
.hero-side{{background:rgba(13,24,40,.9);border:1px solid var(--line);border-radius:24px;padding:24px;box-shadow:var(--shadow)}}
.hero-side h3{{margin-top:0}}
.hero-side .big-action{{font-size:1.8rem;font-weight:900;color:var(--green);margin:8px 0}}
.hero-side p{{color:var(--muted);line-height:1.55}}
.section-header{{display:flex;justify-content:space-between;align-items:end;gap:20px;margin:34px 0 16px}}
.section-header h2{{margin:0;font-size:1.5rem}}
.section-header p{{margin:0;color:var(--muted);font-size:.9rem}}
.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}
.currency-card{{background:rgba(13,24,40,.92);border:1px solid var(--line);border-radius:22px;padding:20px;box-shadow:var(--shadow);position:relative;overflow:hidden}}
.currency-card:before{{content:"";position:absolute;inset:0 auto auto 0;width:100%;height:3px;background:linear-gradient(90deg,var(--cyan),transparent);opacity:.7}}
.card-topline{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}}
.rank{{font-size:.74rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:800}}
.currency-card h2{{font-size:1.7rem;margin:6px 0 0}}
.currency-card h2 span{{display:block;font-size:.84rem;font-weight:600;color:var(--muted);margin-top:4px}}
.score-ring{{width:72px;height:72px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-direction:column;border:6px solid currentColor;background:#091321;flex:0 0 72px}}
.score-ring strong{{font-size:1.24rem;line-height:1}}
.score-ring small{{font-size:.68rem;color:var(--muted);margin-top:3px}}
.score-strong{{color:var(--green)}}.score-good{{color:var(--lime)}}.score-neutral{{color:var(--amber)}}.score-weak{{color:var(--red)}}
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
.mini-grid strong{{font-size:.86rem}}
.action-box{{display:flex;justify-content:space-between;gap:12px;align-items:center;background:linear-gradient(135deg,rgba(86,217,246,.08),rgba(69,221,163,.06));border:1px solid #26445a;border-radius:14px;padding:13px 14px}}
.action-box span{{display:block;color:var(--muted);font-size:.72rem;margin-bottom:3px}}
.action-box strong{{font-size:.9rem}}
.allocation{{font-size:.75rem;font-weight:900;color:var(--cyan);white-space:nowrap}}
.drivers{{padding-left:18px;margin:16px 0 0;color:#bfd0e4;font-size:.82rem;line-height:1.55;min-height:108px}}
.chart-button{{width:100%;margin-top:12px;background:#142a42;border:1px solid #274764;color:var(--text);border-radius:11px;padding:10px 12px;font-weight:800;cursor:pointer}}
.chart-button:hover{{background:#1a3552}}
.chart-panel{{background:rgba(13,24,40,.94);border:1px solid var(--line);border-radius:22px;padding:20px;box-shadow:var(--shadow)}}
.chart-toolbar{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}}
.chart-toolbar h3{{margin:0}}
.chart-toolbar select{{background:#0a1523;color:var(--text);border:1px solid #2a4058;border-radius:10px;padding:9px 12px}}
.chart-wrap{{height:380px}}
.table-panel{{overflow:auto;background:rgba(13,24,40,.92);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}}
table{{width:100%;border-collapse:collapse;min-width:1050px}}
th,td{{padding:14px 16px;border-bottom:1px solid #1b2c41;text-align:left;font-size:.84rem}}
th{{position:sticky;top:0;background:#0d1928;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em}}
td span{{display:block;color:var(--muted);font-size:.74rem;margin-top:2px}}
.table-score{{font-weight:900;font-size:1rem}}
.table-rec{{display:inline-block;padding:5px 8px;border-radius:999px;font-size:.7rem;font-weight:900}}
.methodology{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.method-card{{background:rgba(13,24,40,.9);border:1px solid var(--line);border-radius:16px;padding:16px}}
.method-card strong{{font-size:1.7rem;display:block;margin-bottom:6px;color:var(--cyan)}}
.method-card span{{color:var(--muted);font-size:.82rem;line-height:1.5}}
.notice{{margin-top:26px;padding:18px 20px;border:1px solid #34435a;background:rgba(17,31,51,.7);border-radius:16px;color:#b9c9dc;font-size:.84rem;line-height:1.6}}
footer{{color:#6f859e;font-size:.76rem;text-align:center;margin-top:26px}}
@media(max-width:1050px){{.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}.hero{{grid-template-columns:1fr}}.methodology{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:680px){{.container{{padding:20px 14px 40px}}.topbar{{display:block}}.status-panel{{margin-top:18px;min-width:0}}.cards{{grid-template-columns:1fr}}.methodology{{grid-template-columns:1fr}}.chart-wrap{{height:300px}}.mini-grid{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>
<div class="container">
  <header class="topbar">
    <div>
      <div class="eyebrow">Personal currency decision support</div>
      <h1>V FX Intelligence</h1>
      <p class="subtitle">Ranks when converting Singapore dollars into foreign currencies looks historically attractive. Scores run from 0 to 5, where a higher score means a more attractive buying zone for an SGD-based buyer.</p>
    </div>
    <div class="status-panel">
      <div><span>Market data</span><strong>{market_date}</strong></div>
      <div><span>Model</span><strong>{model_version}</strong></div>
      <div><span>Primary source</span><strong>{primary_source}</strong></div>
      <div><span>Cross-check</span><strong>{validation_source}</strong></div>
    </div>
  </header>

  <section class="hero">
    <div class="hero-card">
      <h3>Best current opportunity</h3>
      <div class="hero-opportunity"><span>{best['code']}</span> · {html.escape(best['recommendation'])}</div>
      <div class="hero-score"><strong>{best['score']:.2f}/5</strong><span>{rate_text(best)}</span></div>
      <p class="hero-copy">{html.escape(best['drivers'][0] if best.get('drivers') else best['suggested_action'])}</p>
    </div>
    <div class="hero-side">
      <h3>Suggested action</h3>
      <div class="big-action">{html.escape(best['suggested_action'])}</div>
      <p>{best['suggested_buy_pct']}% of your planned discretionary conversion is the model's current suggested first tranche. This is a staging guide, not a requirement to transact.</p>
    </div>
  </section>

  <div class="section-header">
    <div><h2>Currency opportunity ranking</h2><p>Highest Buy Score first</p></div>
  </div>
  <section class="cards">{cards_html}</section>

  <div class="section-header">
    <div><h2>Five-year SGD cost history</h2><p>Lower cost generally means better value for an SGD buyer.</p></div>
  </div>
  <section class="chart-panel" id="chartSection">
    <div class="chart-toolbar">
      <h3 id="chartTitle">{best['code']} cost history</h3>
      <select id="currencySelect" onchange="showCurrency(this.value)">
        {''.join(f'<option value="{item["code"]}" {"selected" if item["code"] == best["code"] else ""}>{item["code"]} — {html.escape(item["name"])}</option>' for item in currencies)}
      </select>
    </div>
    <div class="chart-wrap"><canvas id="fxChart"></canvas></div>
  </section>

  <div class="section-header">
    <div><h2>Full scorecard</h2><p>Compare rate, valuation, recommendation and confidence.</p></div>
  </div>
  <section class="table-panel">
    <table>
      <thead><tr><th>Currency</th><th>Score</th><th>Signal</th><th>Current cost</th><th>1M move</th><th>5Y percentile</th><th>Suggested tranche</th><th>Confidence</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </section>

  <div class="section-header">
    <div><h2>Phase 1 scoring model</h2><p>The model is intentionally transparent and will be backtested before adding AI/news layers.</p></div>
  </div>
  <section class="methodology">
    <div class="method-card"><strong>55%</strong><span>Historical value: 1-year, 3-year and 5-year SGD cost percentiles.</span></div>
    <div class="method-card"><strong>25%</strong><span>Trend & timing: 20-, 50- and 200-day averages plus RSI.</span></div>
    <div class="method-card"><strong>15%</strong><span>Momentum: recent direction of the foreign currency's SGD cost.</span></div>
    <div class="method-card"><strong>5%</strong><span>Volatility: lower uncertainty receives a modest risk-quality boost.</span></div>
  </section>

  <div class="notice"><strong>Important:</strong> ECB reference rates are informational reference rates, not the exact retail rate you will receive from a bank, card, money changer or transfer service. The Buy Score estimates relative attractiveness from an SGD buyer's perspective and does not guarantee that a currency will strengthen after purchase.</div>
  <footer>Generated automatically by GitHub Actions · Last build {html.escape(generated)}</footer>
</div>

<script>
let historyData = null;
let chart = null;
const currencyMeta = {json.dumps({item['code']: {'name': item['name'], 'unit': item['unit'], 'symbol': item['symbol']} for item in currencies})};

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
  document.getElementById('chartSection').scrollIntoView({{behavior:'smooth', block:'start'}});
  const data = await loadHistory();
  const filtered = data.records.filter(row => row[code] !== null && row[code] !== undefined);
  const labels = filtered.map(row => row.date);
  const values = filtered.map(row => row[code]);
  const meta = currencyMeta[code];
  const label = meta.unit === 1 ? `SGD per 1 ${{code}}` : `SGD per ${{meta.unit}} ${{code}}`;

  const ctx = document.getElementById('fxChart');
  if (chart) chart.destroy();
  chart = new Chart(ctx, {{
    type:'line',
    data:{{labels, datasets:[{{label, data:values, borderWidth:2, pointRadius:0, tension:.16, borderColor:'#56d9f6', backgroundColor:'rgba(86,217,246,.10)', fill:true}}]}},
    options:{{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{{mode:'index', intersect:false}},
      plugins:{{legend:{{labels:{{color:'#c5d5e8'}}}}, tooltip:{{callbacks:{{label:(ctx)=>` S$${{ctx.parsed.y.toFixed(4)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#7188a2', maxTicksLimit:8}}, grid:{{color:'rgba(86,110,140,.10)'}}}},y:{{ticks:{{color:'#7188a2'}}, grid:{{color:'rgba(86,110,140,.12)'}}}}}}
    }}
  }});
}}

showCurrency('{best['code']}', false).catch(err => console.error(err));
</script>
</body>
</html>
"""

    OUTPUT_PATH.write_text(html_page, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
