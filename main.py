from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:  # yfinance is optional for validation only
    yf = None


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ECB SDMX series structure:
# FREQ.CURRENCY.CURRENCY_DENOM.EXR_TYPE.EXR_SUFFIX
ECB_CURRENCIES = ["USD", "JPY", "GBP", "AUD", "MYR", "SGD"]
ECB_QUERY = "+".join(ECB_CURRENCIES)
ECB_API_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/"
    f"D.{ECB_QUERY}.EUR.SP00.A"
)
ECB_STATIC_CSV = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.csv"

# Foreign currencies we want to evaluate from the perspective of a Singapore-dollar buyer.
# unit=100 for JPY so the dashboard shows the familiar cost of JPY 100.
CURRENCY_CONFIG = {
    "USD": {"name": "US Dollar", "symbol": "US$", "unit": 1, "yf": "USDSGD=X"},
    "JPY": {"name": "Japanese Yen", "symbol": "¥", "unit": 100, "yf": "JPYSGD=X"},
    "EUR": {"name": "Euro", "symbol": "€", "unit": 1, "yf": "EURSGD=X"},
    "GBP": {"name": "British Pound", "symbol": "£", "unit": 1, "yf": "GBPSGD=X"},
    "AUD": {"name": "Australian Dollar", "symbol": "A$", "unit": 1, "yf": "AUDSGD=X"},
    "MYR": {"name": "Malaysian Ringgit", "symbol": "RM", "unit": 1, "yf": "MYRSGD=X"},
}

MODEL_VERSION = "1.1-phase1b"
MODEL_WEIGHTS = {
    "historical_value": 0.50,
    "trend_timing": 0.25,
    "momentum": 0.15,
    "volatility": 0.10,
}


@dataclass
class CurrencySignal:
    code: str
    name: str
    symbol: str
    unit: int
    rate_sgd: float
    inverse_per_sgd: float
    score: float
    recommendation: str
    suggested_action: str
    suggested_buy_pct: int
    confidence: int
    confidence_label: str
    data_date: str
    change_1d_pct: Optional[float]
    change_7d_pct: Optional[float]
    change_30d_pct: Optional[float]
    change_90d_pct: Optional[float]
    change_1y_pct: Optional[float]
    percentile_1y: Optional[float]
    percentile_3y: Optional[float]
    percentile_5y: Optional[float]
    low_52w: Optional[float]
    high_52w: Optional[float]
    ma20: Optional[float]
    ma50: Optional[float]
    ma200: Optional[float]
    rsi14: Optional[float]
    annualized_volatility_pct: Optional[float]
    fair_value_sgd: Optional[float]
    buy_zone_upper_sgd: Optional[float]
    strong_buy_level_sgd: Optional[float]
    exceptional_buy_level_sgd: Optional[float]
    distance_to_buy_zone_pct: Optional[float]
    zone_status: str
    component_scores: Dict[str, float]
    validation_rate_sgd: Optional[float]
    validation_difference_pct: Optional[float]
    validation_status: str
    drivers: List[str]


def _http_get(url: str, params: Optional[dict] = None, timeout: int = 45) -> requests.Response:
    headers = {
        "User-Agent": "V-FX-Intelligence/1.0 (+GitHub Actions)",
        "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    }
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_ecb_history(years: int = 7) -> Tuple[pd.DataFrame, str]:
    """Fetch official ECB daily reference rates and return a wide dataframe.

    ECB rates are quoted as units of foreign currency per EUR.
    The returned dataframe is indexed by date and contains USD/JPY/GBP/AUD/MYR/SGD.
    """
    start_period = (pd.Timestamp.utcnow().normalize() - pd.DateOffset(years=years)).date().isoformat()

    # Primary method: ECB Data Portal API.
    try:
        response = _http_get(
            ECB_API_URL,
            params={"format": "csvdata", "startPeriod": start_period},
        )
        raw = pd.read_csv(io.StringIO(response.text))
        required = {"TIME_PERIOD", "OBS_VALUE", "CURRENCY"}
        if not required.issubset(raw.columns):
            raise ValueError(f"Unexpected ECB API columns: {list(raw.columns)}")

        raw["TIME_PERIOD"] = pd.to_datetime(raw["TIME_PERIOD"], errors="coerce")
        raw["OBS_VALUE"] = pd.to_numeric(raw["OBS_VALUE"], errors="coerce")
        raw = raw.dropna(subset=["TIME_PERIOD", "OBS_VALUE", "CURRENCY"])
        wide = raw.pivot_table(
            index="TIME_PERIOD",
            columns="CURRENCY",
            values="OBS_VALUE",
            aggfunc="last",
        ).sort_index()
        wide.index.name = "Date"
        validate_ecb_dataframe(wide)
        return wide, "ECB Data Portal API"
    except Exception as api_error:
        print(f"ECB API fetch failed; trying ECB historical CSV fallback: {api_error}")

    # Fallback method: ECB historical CSV download.
    response = _http_get(ECB_STATIC_CSV)
    wide = pd.read_csv(io.StringIO(response.text))
    if "Date" not in wide.columns:
        raise ValueError("ECB CSV fallback does not contain a Date column.")
    wide["Date"] = pd.to_datetime(wide["Date"], errors="coerce")
    wide = wide.dropna(subset=["Date"]).set_index("Date").sort_index()
    for column in ECB_CURRENCIES:
        if column in wide.columns:
            wide[column] = pd.to_numeric(wide[column], errors="coerce")
    wide = wide.loc[wide.index >= pd.Timestamp(start_period)]
    validate_ecb_dataframe(wide)
    return wide, "ECB historical CSV fallback"


def validate_ecb_dataframe(df: pd.DataFrame) -> None:
    missing = [c for c in ECB_CURRENCIES if c not in df.columns]
    if missing:
        raise ValueError(f"ECB data is missing required currencies: {missing}")
    if df.empty:
        raise ValueError("ECB data is empty.")

    latest_date = pd.Timestamp(df.dropna(subset=["SGD"]).index.max()).tz_localize(None)
    age_days = (pd.Timestamp.utcnow().tz_localize(None).normalize() - latest_date.normalize()).days
    if age_days > 14:
        raise ValueError(f"ECB data appears stale. Latest observation is {latest_date.date()}.")

    latest = df.loc[latest_date]
    plausibility = {
        "USD": (0.5, 2.5),
        "JPY": (50.0, 300.0),
        "GBP": (0.4, 1.5),
        "AUD": (0.8, 3.0),
        "MYR": (2.0, 8.0),
        "SGD": (0.8, 3.0),
    }
    for code, (low, high) in plausibility.items():
        value = float(latest[code])
        if not low <= value <= high:
            raise ValueError(f"Implausible ECB value for {code}: {value}")


def build_sgd_cost_series(ecb: pd.DataFrame) -> Dict[str, pd.Series]:
    """Convert ECB EUR cross-rates into SGD cost of each foreign currency."""
    series: Dict[str, pd.Series] = {}
    sgd_per_eur = ecb["SGD"].astype(float)

    for code, config in CURRENCY_CONFIG.items():
        unit = int(config["unit"])
        if code == "EUR":
            s = sgd_per_eur * unit
        else:
            foreign_per_eur = ecb[code].astype(float)
            s = (sgd_per_eur / foreign_per_eur) * unit
        s = s.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
        series[code] = s
    return series


def fetch_validation_rates() -> Dict[str, float]:
    """Fetch a second-source market snapshot from Yahoo Finance for validation only.

    The score itself remains based on official ECB reference-rate history.
    """
    if yf is None:
        return {}

    validation: Dict[str, float] = {}
    for code, config in CURRENCY_CONFIG.items():
        ticker = config["yf"]
        unit = int(config["unit"])
        try:
            history = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
            if history.empty or "Close" not in history:
                continue
            value = float(history["Close"].dropna().iloc[-1]) * unit
            if math.isfinite(value) and value > 0:
                validation[code] = value
        except Exception as exc:
            print(f"Validation source failed for {code}: {exc}")
    return validation


def pct_change(series: pd.Series, periods: int) -> Optional[float]:
    if len(series) <= periods:
        return None
    old = float(series.iloc[-periods - 1])
    current = float(series.iloc[-1])
    if old == 0:
        return None
    return (current / old - 1.0) * 100.0


def value_at_or_before(series: pd.Series, days: int) -> Optional[float]:
    cutoff = series.index[-1] - pd.Timedelta(days=days)
    earlier = series.loc[series.index <= cutoff]
    if earlier.empty:
        return None
    return float(earlier.iloc[-1])


def calendar_pct_change(series: pd.Series, days: int) -> Optional[float]:
    old = value_at_or_before(series, days)
    if old is None or old == 0:
        return None
    return (float(series.iloc[-1]) / old - 1.0) * 100.0


def percentile_rank(window: pd.Series, current: float) -> Optional[float]:
    clean = window.dropna()
    if len(clean) < 20:
        return None
    return float((clean <= current).mean() * 100.0)


def calculate_rsi(series: pd.Series, period: int = 14) -> Optional[float]:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    latest_loss = float(avg_loss.iloc[-1])
    latest_gain = float(avg_gain.iloc[-1])
    if latest_loss == 0:
        return 100.0 if latest_gain > 0 else 50.0
    rs = latest_gain / latest_loss
    return float(100 - (100 / (1 + rs)))


def weighted_average(items: List[Tuple[Optional[float], float]], default: float = 2.5) -> float:
    valid = [(value, weight) for value, weight in items if value is not None and math.isfinite(value)]
    if not valid:
        return default
    total_weight = sum(weight for _, weight in valid)
    return float(sum(value * weight for value, weight in valid) / total_weight)


def historical_value_score(series: pd.Series) -> Tuple[float, Dict[str, Optional[float]]]:
    current = float(series.iloc[-1])
    end = series.index[-1]
    windows = {
        "1y": series.loc[series.index >= end - pd.DateOffset(years=1)],
        "3y": series.loc[series.index >= end - pd.DateOffset(years=3)],
        "5y": series.loc[series.index >= end - pd.DateOffset(years=5)],
    }
    percentiles = {key: percentile_rank(window, current) for key, window in windows.items()}

    # Lower SGD cost percentile means the foreign currency is cheaper for a Singapore-dollar buyer.
    scores = {
        key: None if pct is None else 5.0 * (1.0 - pct / 100.0)
        for key, pct in percentiles.items()
    }
    score = weighted_average(
        # FX valuation benefits from a longer horizon, so 3Y/5Y history carries more weight.
        [(scores["1y"], 0.25), (scores["3y"], 0.35), (scores["5y"], 0.40)]
    )
    return float(np.clip(score, 0, 5)), percentiles


def relative_to_ma_score(current: float, ma: Optional[float], band: float) -> Optional[float]:
    if ma is None or not math.isfinite(ma) or ma <= 0:
        return None
    deviation = current / ma - 1.0
    # At the moving average = neutral 2.5. Roughly 'band' below = 5; 'band' above = 0.
    return float(np.clip(2.5 - (deviation / band) * 2.5, 0, 5))


def rsi_timing_score(rsi: Optional[float]) -> Optional[float]:
    if rsi is None or not math.isfinite(rsi):
        return None
    if rsi < 25:
        return 4.0  # very cheap but still potentially falling hard
    if rsi < 35:
        return 5.0
    if rsi < 45:
        return 4.5
    if rsi < 55:
        return 3.0
    if rsi < 65:
        return 1.5
    return 0.5


def trend_timing_score(current: float, ma20: Optional[float], ma50: Optional[float], ma200: Optional[float], rsi: Optional[float]) -> float:
    return float(np.clip(weighted_average([
        (relative_to_ma_score(current, ma20, 0.025), 0.25),
        (relative_to_ma_score(current, ma50, 0.040), 0.35),
        (relative_to_ma_score(current, ma200, 0.080), 0.25),
        (rsi_timing_score(rsi), 0.15),
    ]), 0, 5))


def buyer_momentum_score(change_pct: Optional[float], scale: float) -> Optional[float]:
    if change_pct is None or not math.isfinite(change_pct):
        return None
    # Negative foreign-currency price change is favourable to an SGD buyer.
    return float(np.clip(2.5 - 2.5 * np.tanh(change_pct / scale), 0, 5))


def momentum_score(change_7d: Optional[float], change_30d: Optional[float], rsi: Optional[float]) -> float:
    score = weighted_average([
        (buyer_momentum_score(change_7d, 2.0), 0.40),
        (buyer_momentum_score(change_30d, 4.0), 0.60),
    ])
    # Small falling-knife penalty when the move is exceptionally sharp and RSI is deeply oversold.
    if change_7d is not None and rsi is not None and change_7d < -4.0 and rsi < 25:
        score -= 0.6
    return float(np.clip(score, 0, 5))


def volatility_score(series: pd.Series) -> Tuple[float, Optional[float]]:
    returns = series.pct_change().dropna().tail(60)
    if len(returns) < 20:
        return 2.5, None
    annualized = float(returns.std() * np.sqrt(252) * 100.0)
    # Typical developed-market FX volatility often falls inside a broad single-digit to low-teens range.
    score = 5.0 - ((annualized - 3.0) / 12.0) * 4.0
    return float(np.clip(score, 1.0, 5.0)), annualized



def calculate_buy_zones(series: pd.Series) -> Dict[str, Optional[float]]:
    """Calculate transparent valuation thresholds from the latest five years.

    Because the series is the SGD cost of buying foreign currency, lower values are
    better for an SGD buyer. The thresholds are deliberately based on long-run
    percentiles rather than short-term forecasts.
    """
    end = series.index[-1]
    window = series.loc[series.index >= end - pd.DateOffset(years=5)].dropna()
    if len(window) < 250:
        return {
            "exceptional_buy_level": None,
            "strong_buy_level": None,
            "buy_zone_upper": None,
            "fair_value": None,
        }

    return {
        "exceptional_buy_level": float(window.quantile(0.10)),
        "strong_buy_level": float(window.quantile(0.20)),
        "buy_zone_upper": float(window.quantile(0.35)),
        "fair_value": float(window.quantile(0.50)),
    }


def zone_status_from_rate(current: float, zones: Dict[str, Optional[float]]) -> str:
    exceptional = zones.get("exceptional_buy_level")
    strong = zones.get("strong_buy_level")
    buy = zones.get("buy_zone_upper")
    fair = zones.get("fair_value")

    if exceptional is not None and current <= exceptional:
        return "Exceptional Value Zone"
    if strong is not None and current <= strong:
        return "Strong Buy Zone"
    if buy is not None and current <= buy:
        return "Buy Zone"
    if fair is not None and current <= fair:
        return "Fair / Accumulate Zone"
    return "Above Fair Value"


def ordinal(value: float) -> str:
    number = int(round(value))
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def recommendation_from_score(score: float) -> Tuple[str, str, int]:
    if score >= 4.5:
        return "Exceptional Buy", "Buy a meaningful tranche now", 40
    if score >= 4.0:
        return "Buy", "Buy in stages", 30
    if score >= 3.5:
        return "Accumulate", "Start or continue gradual buying", 20
    if score >= 3.0:
        return "Light Accumulate", "Small tranche only", 10
    if score >= 2.25:
        return "Wait", "Wait for a better rate unless funds are needed", 0
    if score >= 1.5:
        return "Expensive", "Avoid a large discretionary purchase", 0
    return "Avoid", "Poor accumulation zone", 0


def confidence_score(series: pd.Series, validation_difference: Optional[float]) -> Tuple[int, str]:
    years = (series.index[-1] - series.index[0]).days / 365.25
    confidence = 60
    if years >= 5:
        confidence += 12
    elif years >= 3:
        confidence += 7

    if validation_difference is not None:
        if validation_difference <= 0.5:
            confidence += 10
        elif validation_difference <= 1.0:
            confidence += 6
        elif validation_difference <= 2.0:
            confidence += 2
        else:
            confidence -= 5

    # Phase 1 intentionally excludes macro/news/event intelligence, so cap confidence.
    confidence = int(np.clip(confidence, 55, 85))
    label = "High" if confidence >= 80 else "Medium" if confidence >= 65 else "Low"
    return confidence, label


def validation_status(diff: Optional[float]) -> str:
    if diff is None:
        return "Unavailable"
    if diff <= 0.5:
        return "Excellent"
    if diff <= 1.0:
        return "Good"
    if diff <= 2.0:
        return "Watch"
    return "Large Difference"


def build_drivers(
    percentile_5y: Optional[float],
    change_30d: Optional[float],
    rsi: Optional[float],
    current: float,
    ma200: Optional[float],
    volatility_pct: Optional[float],
) -> List[str]:
    drivers: List[str] = []

    if percentile_5y is not None:
        if percentile_5y <= 20:
            drivers.append(f"Historically attractive: current cost is in the cheapest {max(1, round(percentile_5y))}% of the 5-year range.")
        elif percentile_5y >= 80:
            drivers.append(f"Historically expensive: current cost is in the highest {round(100 - percentile_5y)}% from the top of the 5-year range.")
        else:
            drivers.append(f"5-year valuation is mid-range at the {ordinal(percentile_5y)} cost percentile.")

    if change_30d is not None:
        if change_30d <= -2:
            drivers.append(f"Buyer-friendly momentum: SGD cost fell {abs(change_30d):.1f}% over roughly one month.")
        elif change_30d >= 2:
            drivers.append(f"Unfavourable momentum: SGD cost rose {change_30d:.1f}% over roughly one month.")
        else:
            drivers.append("One-month price movement is relatively stable.")

    if ma200 is not None:
        if current < ma200:
            drivers.append("Current cost is below its 200-day average, supporting longer-term value.")
        else:
            drivers.append("Current cost is above its 200-day average, reducing timing attractiveness.")

    if rsi is not None and rsi < 30:
        drivers.append("RSI is deeply oversold; this can be attractive but also signals short-term falling-knife risk.")
    elif rsi is not None and rsi > 70:
        drivers.append("RSI is overbought, suggesting poor near-term timing for a fresh currency purchase.")

    if volatility_pct is not None and volatility_pct > 12:
        drivers.append("Recent volatility is elevated, so staged buying is preferred over a single large conversion.")

    return drivers[:4]


def analyse_currency(code: str, series: pd.Series, validation_rates: Dict[str, float]) -> CurrencySignal:
    series = series.dropna().sort_index()
    if len(series) < 250:
        raise ValueError(f"Insufficient history for {code}: only {len(series)} observations")

    current = float(series.iloc[-1])
    data_date = series.index[-1].date().isoformat()
    config = CURRENCY_CONFIG[code]
    unit = int(config["unit"])

    change_1d = pct_change(series, 1)
    change_7d = calendar_pct_change(series, 7)
    change_30d = calendar_pct_change(series, 30)
    change_90d = calendar_pct_change(series, 90)
    change_1y = calendar_pct_change(series, 365)

    historical_score, percentiles = historical_value_score(series)

    ma20 = float(series.tail(20).mean()) if len(series) >= 20 else None
    ma50 = float(series.tail(50).mean()) if len(series) >= 50 else None
    ma200 = float(series.tail(200).mean()) if len(series) >= 200 else None
    rsi = calculate_rsi(series)
    timing_score = trend_timing_score(current, ma20, ma50, ma200, rsi)
    mom_score = momentum_score(change_7d, change_30d, rsi)
    vol_score, annualized_vol = volatility_score(series)
    buy_zones = calculate_buy_zones(series)
    zone_status = zone_status_from_rate(current, buy_zones)

    buy_zone_upper = buy_zones.get("buy_zone_upper")
    distance_to_buy_zone = None
    if buy_zone_upper is not None and current > 0:
        # Positive means the SGD cost would need to fall by this percentage to enter the buy zone.
        distance_to_buy_zone = max(0.0, (current / buy_zone_upper - 1.0) * 100.0)

    component_scores = {
        "historical_value": round(historical_score, 2),
        "trend_timing": round(timing_score, 2),
        "momentum": round(mom_score, 2),
        "volatility": round(vol_score, 2),
    }

    score = sum(component_scores[key] * MODEL_WEIGHTS[key] for key in MODEL_WEIGHTS)
    score = round(float(np.clip(score, 0, 5)), 2)
    recommendation, action, buy_pct = recommendation_from_score(score)

    validation_rate = validation_rates.get(code)
    validation_diff = None
    if validation_rate is not None and current > 0:
        validation_diff = abs(validation_rate / current - 1.0) * 100.0

    confidence, confidence_label = confidence_score(series, validation_diff)

    one_year = series.loc[series.index >= series.index[-1] - pd.DateOffset(years=1)]
    low_52w = float(one_year.min()) if not one_year.empty else None
    high_52w = float(one_year.max()) if not one_year.empty else None

    drivers = build_drivers(
        percentiles.get("5y"),
        change_30d,
        rsi,
        current,
        ma200,
        annualized_vol,
    )

    # inverse_per_sgd expresses how many units of the underlying currency S$1 buys.
    # Because JPY is displayed in units of 100, convert back to a one-unit basis first.
    per_currency_unit_cost = current / unit
    inverse_per_sgd = 1.0 / per_currency_unit_cost

    return CurrencySignal(
        code=code,
        name=str(config["name"]),
        symbol=str(config["symbol"]),
        unit=unit,
        rate_sgd=round(current, 6),
        inverse_per_sgd=round(inverse_per_sgd, 6),
        score=score,
        recommendation=recommendation,
        suggested_action=action,
        suggested_buy_pct=buy_pct,
        confidence=confidence,
        confidence_label=confidence_label,
        data_date=data_date,
        change_1d_pct=None if change_1d is None else round(change_1d, 2),
        change_7d_pct=None if change_7d is None else round(change_7d, 2),
        change_30d_pct=None if change_30d is None else round(change_30d, 2),
        change_90d_pct=None if change_90d is None else round(change_90d, 2),
        change_1y_pct=None if change_1y is None else round(change_1y, 2),
        percentile_1y=None if percentiles.get("1y") is None else round(float(percentiles["1y"]), 1),
        percentile_3y=None if percentiles.get("3y") is None else round(float(percentiles["3y"]), 1),
        percentile_5y=None if percentiles.get("5y") is None else round(float(percentiles["5y"]), 1),
        low_52w=None if low_52w is None else round(low_52w, 6),
        high_52w=None if high_52w is None else round(high_52w, 6),
        ma20=None if ma20 is None else round(ma20, 6),
        ma50=None if ma50 is None else round(ma50, 6),
        ma200=None if ma200 is None else round(ma200, 6),
        rsi14=None if rsi is None else round(rsi, 1),
        annualized_volatility_pct=None if annualized_vol is None else round(annualized_vol, 2),
        fair_value_sgd=None if buy_zones.get("fair_value") is None else round(float(buy_zones["fair_value"]), 6),
        buy_zone_upper_sgd=None if buy_zones.get("buy_zone_upper") is None else round(float(buy_zones["buy_zone_upper"]), 6),
        strong_buy_level_sgd=None if buy_zones.get("strong_buy_level") is None else round(float(buy_zones["strong_buy_level"]), 6),
        exceptional_buy_level_sgd=None if buy_zones.get("exceptional_buy_level") is None else round(float(buy_zones["exceptional_buy_level"]), 6),
        distance_to_buy_zone_pct=None if distance_to_buy_zone is None else round(float(distance_to_buy_zone), 2),
        zone_status=zone_status,
        component_scores=component_scores,
        validation_rate_sgd=None if validation_rate is None else round(validation_rate, 6),
        validation_difference_pct=None if validation_diff is None else round(validation_diff, 2),
        validation_status=validation_status(validation_diff),
        drivers=drivers,
    )


def write_market_history(series_map: Dict[str, pd.Series]) -> None:
    # Keep five years of daily history for dashboard charts and future backtesting.
    latest = max(series.index.max() for series in series_map.values())
    cutoff = latest - pd.DateOffset(years=5)

    all_dates = sorted(set().union(*[set(s.loc[s.index >= cutoff].index) for s in series_map.values()]))
    records = []
    for date in all_dates:
        row = {"date": pd.Timestamp(date).date().isoformat()}
        for code, series in series_map.items():
            value = series.get(date, np.nan)
            row[code] = None if pd.isna(value) else round(float(value), 6)
        records.append(row)

    payload = {
        "base_currency": "SGD",
        "rate_definition": "SGD cost for the display unit of each foreign currency",
        "units": {code: int(cfg["unit"]) for code, cfg in CURRENCY_CONFIG.items()},
        "records": records,
    }
    (DATA_DIR / "fx_history.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def update_score_log(signals: List[CurrencySignal]) -> None:
    path = DATA_DIR / "score_log.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("records", [])
        except Exception:
            records = []
    else:
        records = []

    run_date = max(signal.data_date for signal in signals)
    new_row = {
        "date": run_date,
        "scores": {signal.code: signal.score for signal in signals},
        "recommendations": {signal.code: signal.recommendation for signal in signals},
        "rates_sgd": {signal.code: signal.rate_sgd for signal in signals},
        "buy_zone_upper_sgd": {signal.code: signal.buy_zone_upper_sgd for signal in signals},
        "zone_status": {signal.code: signal.zone_status for signal in signals},
    }

    # Replace an existing entry for the same market date instead of duplicating it.
    records = [row for row in records if row.get("date") != run_date]
    records.append(new_row)
    records = sorted(records, key=lambda row: row.get("date", ""))[-1500:]

    path.write_text(
        json.dumps({"model_version": MODEL_VERSION, "records": records}, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    ecb, source_name = fetch_ecb_history(years=7)
    series_map = build_sgd_cost_series(ecb)
    validation_rates = fetch_validation_rates()

    signals = [analyse_currency(code, series_map[code], validation_rates) for code in CURRENCY_CONFIG]
    signals.sort(key=lambda item: item.score, reverse=True)

    latest_market_date = max(signal.data_date for signal in signals)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_market_date": latest_market_date,
        "base_currency": "SGD",
        "model_version": MODEL_VERSION,
        "phase": "Phase 1B — refined FX scoring and dynamic historical buy zones",
        "primary_source": source_name,
        "validation_source": "Yahoo Finance market snapshot (validation only)" if validation_rates else "Unavailable",
        "model_weights": MODEL_WEIGHTS,
        "important_note": (
            "This model ranks the attractiveness of converting SGD into foreign currency. "
            "It is a decision-support tool, not a guarantee of future exchange-rate direction."
        ),
        "currencies": [asdict(signal) for signal in signals],
    }

    (DATA_DIR / "fx_signals.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_market_history(series_map)
    update_score_log(signals)

    print(f"Updated {len(signals)} currencies using {source_name}. Market date: {latest_market_date}")
    for signal in signals:
        print(f"{signal.code}: {signal.score:.2f}/5 — {signal.recommendation}")


if __name__ == "__main__":
    main()
