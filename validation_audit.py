"""Additional diagnostics; preserves the original performance series and model."""
import json
from collections import Counter
from datetime import datetime, timezone


def load(root, name):
    path = root / (name + ".json")
    return json.loads(path.read_text()) if path.exists() else {}


def build_audit(root):
    signal = load(root, "fx_signals")
    codes = [c["code"] for c in signal.get("currencies", [])]
    histories = load(root, "fx_history").get("records", [])
    dates = {c: [r["date"] for r in histories if isinstance(r.get(c), (int, float)) and r[c] > 0] for c in codes}
    baseline = [r for r in load(root, "score_log").get("records", []) if r.get("model_version") == signal.get("model_version")]
    shadow = [r for r in load(root, "news_shadow_log").get("records", []) if r.get("app_release") == signal.get("app_release")]
    result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "snapshot_at_utc": signal.get("generated_at_utc"),
              "note": "Diagnostic counts only. Original performance files and frozen model are unchanged. Horizon samples overlap and are not independent; no spread, fees or execution timing are modelled.",
              "baseline": {}, "shadow": {}}
    for name, rows, horizons, date_key, rate_key in [
        ("baseline", baseline, (1, 5, 10, 20), "date", "rates_sgd"),
        ("shadow", shadow, (1, 5, 10), "market_date", "rates_sgd"),
    ]:
        diagnostics = {"logged_days": len(rows), "unique_market_dates": len({r.get(date_key) for r in rows}),
                       "rows_without_observed_timestamp": sum(not r.get("observed_at_utc") for r in rows),
                       "horizons": {}}
        for horizon in horizons:
            counts = Counter(matured=0, pending=0, missing_entry=0, missing_market_date=0,
                             excluded_evidence=0, excluded_neutral=0, duplicate=0)
            seen = set()
            for row in rows:
                for code in codes:
                    if name == "shadow":
                        if ((row.get("news_evidence_eligible") or {}).get(code) is not True
                                or (row.get("news_coverage_quality") or {}).get(code) not in {"Strong", "Adequate"}
                                or ((row.get("news_confidence_pct") or {}).get(code) or 0) < 40):
                            counts["excluded_evidence"] += 1
                            continue
                        score = (row.get("news_scores") or {}).get(code)
                        if score is None or 1.90 < score < 3.10:
                            counts["excluded_neutral"] += 1
                            continue
                    date = row.get(date_key)
                    key = (date, code)
                    if key in seen:
                        counts["duplicate"] += 1
                        continue
                    seen.add(key)
                    entry = (row.get(rate_key) or {}).get(code)
                    if not isinstance(entry, (float, int)) or entry <= 0:
                        counts["missing_entry"] += 1
                    elif date not in dates[code]:
                        counts["missing_market_date"] += 1
                    elif dates[code].index(date) + horizon >= len(dates[code]):
                        counts["pending"] += 1
                    else:
                        counts["matured"] += 1
            diagnostics["horizons"][str(horizon)] = dict(counts)
        result[name] = diagnostics
    return result
