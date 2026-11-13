"""Review helpers for the existing dashboard; no model calculations."""
import html
import json


def esc(value):
    return html.escape(str(value if value is not None else "Unknown / not recorded"))


def why(item):
    score, urgency = item["opportunity_score"], item["buy_urgency_score"]
    weight = item.get("effective_macro_weight_pct", 0)
    explanation = (f"Opportunity {score:.2f}/5 combines market {item['market_score']:.2f} "
                   f"at {100-weight}% and macro {item['macro_score']:.2f} at {weight}%. ")
    if 3 <= score < 3.5:
        explanation += "In the 3.00–3.49 band, Light Accumulate requires urgency ≥4.00; otherwise the action is Wait. "
    elif 3.5 <= score < 4:
        explanation += "In the 3.50–3.99 band, urgency selects Patient Accumulate (<2.50), Accumulate (2.50–3.99) or Accumulate Now (≥4.00). "
    elif 4 <= score < 4.5:
        explanation += "In the 4.00–4.49 band, urgency ≥3.50 selects Buy Now; otherwise Buy. "
    elif score >= 4.5:
        explanation += "At ≥4.50, urgency ≥3.75 selects Exceptional Buy; otherwise Strong Buy. "
    else:
        explanation += "Below 3.00, the opportunity band determines Wait, Expensive or Avoid; urgency cannot upgrade it to Buy. "
    return explanation + f"Recorded urgency: {urgency:.2f}/5. Displayed components are rounded."


def build_review(data, status, audit):
    currencies = data.get("currencies", [])
    summary = []
    source_rows = []
    for c in currencies:
        code = esc(c["code"])
        summary.append(f'<tr><td><a href="#currency-{code}"><strong>{code}</strong></a></td><td>{c["rate_sgd"]:.4f}</td>'
                       f'<td>{c["opportunity_score"]:.2f}</td><td>{c["buy_urgency_score"]:.2f}</td><td>{esc(c["recommendation"])}</td>'
                       f'<td>{c["suggested_buy_pct"]}%</td><td>{c.get("macro_coverage_pct", 0)}%</td></tr>')
        shadow = c.get("shadow_news") or {}
        missing = [k for k, v in c.get("macro_component_scores", {}).items() if v is None]
        forecast_gaps = [k.replace("_", " ") for k in ("growth_current_pct", "growth_next_pct", "inflation_current_pct", "inflation_next_pct") if c.get(k) is None]
        errors = shadow.get("official_feed_errors", []) + shadow.get("query_errors", [])
        # Existing payloads can contain errors with URLs; escape as plain text.
        source_rows.append(f'<tr><td>{code}</td><td>{esc(c.get("data_date"))}</td><td>{esc(c.get("policy_data_date"))}</td>'
                           f'<td>{esc(", ".join(missing + forecast_gaps) or "No missing macro inputs")}</td>'
                           f'<td>{esc(c.get("validation_status"))}</td><td>{esc(shadow.get("coverage_quality"))} · '
                           f'{"eligible" if shadow.get("evidence_eligible") else "ineligible"}'
                           f'<details><summary>{len(errors)} reported source errors</summary><ul>'
                           + ''.join(f'<li>{esc(e)}</li>' for e in errors) + '</ul></details></td>'
                           f'<td>{esc(c.get("next_policy_meeting_date") or "Calendar rollover needed / unknown")}</td></tr>')
    attempts = []
    for s in status.get("fx_fetch", {}).get("sources", []):
        attempts.append(f'<li><strong>{esc(s.get("name"))}</strong> — {esc(s.get("status"))}; '
                        f'{len(s.get("attempts", []))} attempt(s). {esc(s.get("error") or s.get("latest_observation") or "")}</li>')
    diagnostics = []
    for layer, title in [("baseline", "Phase 2C baseline"), ("shadow", "Phase 3A.3 evidence-gated audit")]:
        d = audit.get(layer, {})
        rows = []
        for h, counts in d.get("horizons", {}).items():
            rows.append(f'<tr><td>{esc(h)}D</td>' + ''.join(f'<td>{counts.get(k, 0)}</td>' for k in
                        ("matured", "pending", "excluded_evidence", "excluded_neutral", "missing_entry", "missing_market_date", "duplicate")) + '</tr>')
        diagnostics.append(f'<h3>{title}</h3><p>{d.get("logged_days", "Unknown")} logged days · '
                           f'{d.get("unique_market_dates", "Unknown")} distinct market dates · '
                           f'{d.get("rows_without_observed_timestamp", "Unknown")} rows without an exact signal creation timestamp.</p>'
                           '<div class="table-panel"><table><thead><tr><th>Horizon</th><th>Matured</th><th>Pending</th>'
                           '<th>Evidence excluded</th><th>Neutral signal</th><th>Missing rate</th><th>Missing date</th><th>Duplicate</th>'
                           '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    if not audit:
        diagnostics = ['<p>Validation diagnostics have not been generated yet. Run the staged updater to create them.</p>']
    compact = f'''<section class="review-only review-panel" id="quick-review">
      <div class="section-header"><div><h2>At a glance</h2><p>SGD cost per unit; JPY per ¥100. Lower cost buys more foreign currency. Select a currency for its full evidence.</p></div></div>
      <div class="table-panel"><table><thead><tr><th>Currency</th><th>SGD cost</th><th>Opportunity /5</th><th>Urgency /5</th><th>Recorded action</th><th>Tranche</th><th>Macro coverage</th></tr></thead><tbody>{''.join(summary)}</tbody></table></div>
    </section>'''
    health = f'''<section class="review-panel" id="source-health"><h2>Source health & data gaps</h2>
      <p>Check context: <strong>{esc(status.get('run_context'))}</strong>. A local check is not a deployed workflow run.</p>
      <p>Last attempt: <strong>{esc(status.get('last_attempt_at_utc'))}</strong> · Last successful FX check: <strong>{esc(status.get('last_successful_check_at_utc'))}</strong></p>
      <p>Model snapshot: <strong>{esc(data.get('generated_at_utc'))}</strong> (UTC). Rechecking an unchanged ECB market date does not refresh macro or news inputs. All data below belongs to that snapshot.</p>
      <ul>{''.join(attempts) or '<li>Transport status was not recorded by the previous release.</li>'}</ul>
      <p>{esc(status.get('error') or '')}</p>
      <p>Source links: <a href="https://data.ecb.europa.eu/data/datasets/EXR">ECB rates</a> · <a href="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip">ECB historical ZIP</a> · <a href="https://data.bis.org/topics/CBPOL">BIS policy</a> · <a href="https://www.imf.org/external/datamapper/">IMF forecasts</a> · <a href="https://github.com/Vasanthan1276/fx-intelligence-report/actions/workflows/update-fx.yml">Scheduled runs and logs</a></p>
      <div class="table-panel"><table><thead><tr><th>Currency</th><th>FX observation</th><th>BIS observation</th><th>Macro gaps</th><th>Yahoo check</th><th>Shadow coverage / errors</th><th>Next policy event</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div>
      <p>BIS is monthly; IMF values are forecasts for the displayed years, not daily observations. IMF release vintage and Yahoo quote time are not recorded in older snapshots, so their freshness cannot be independently established here. Headline confidence and model/data quality are not probabilities of success.</p>
    </section>'''
    diagnostic_html = f'''<section class="review-panel" id="validation-audit"><h2>Validation diagnostics</h2>
      <p>Original performance statistics below are retained for continuity. This separate audit explicitly checks the logged shadow evidence flag, coverage, confidence and unique market dates. Counts may therefore differ.</p>
      {''.join(diagnostics)}
      <p>Accuracy uses decisive outcomes only; neutral moves are excluded from its denominator. Overlapping horizons and currency correlations mean observations are not independent. These are reference-rate comparisons, not a tradable return or proof of predictive value. Signal timestamps missing from older logs prevent a full audit of information available at the time. New logs record UTC creation times; historical timestamps are not backfilled.</p>
    </section>'''
    config = {"marketDate": data.get("latest_market_date"), "snapshotAt": data.get("generated_at_utc"), "status": status}
    return compact, health, diagnostic_html, json.dumps(config).replace('<', '\\u003c')
