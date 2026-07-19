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

MODEL_VERSION = "2.2-phase2c"

# Phase 2C keeps the proven Phase 1B market model intact, then separates a macro-policy
# layer. With complete macro coverage, the final score is 70% market intelligence
# and 30% macro-policy intelligence. If a macro source is temporarily unavailable,
# its weight automatically falls away rather than forcing a neutral score into the
# recommendation.
MARKET_WEIGHTS = {
    "historical_value": 0.50,
    "trend_timing": 0.25,
    "momentum": 0.15,
    "volatility": 0.10,
}
MACRO_WEIGHTS = {
    "policy": 0.50,
    "growth": 0.30,
    "inflation": 0.20,
}
MAX_MACRO_WEIGHT = 0.30

# Phase 2C keeps the Opportunity Score separate from Buy Urgency, but makes
# urgency more forward-looking. The new forward layer is explicitly model-implied
# from observable policy paths, IMF forecast direction and FX price behaviour; it
# is NOT a market-futures probability model.
FORWARD_POLICY_WEIGHTS = {
    "recent_policy_path": 0.50,
    "inflation_pressure": 0.30,
    "growth_pressure": 0.20,
}
FORWARD_MOMENTUM_WEIGHTS = {
    "7d_strengthening": 0.20,
    "30d_strengthening": 0.30,
    "90d_strengthening": 0.25,
    "ma_structure": 0.25,
}
FORWARD_OUTLOOK_WEIGHTS = {
    "policy_bias": 0.45,
    "fx_momentum": 0.55,
}
URGENCY_WEIGHTS = {
    "forward_policy_bias": 0.30,
    "forward_fx_momentum": 0.30,
    "valuation_rarity": 0.20,
    "event_setup": 0.20,
}

# Official 2026 monetary-policy decision dates. These are deliberately embedded
# rather than scraped on every run, which keeps the GitHub Action reliable. The
# dashboard exposes the calendar source and will show "calendar rollover needed"
# after the final published date until the next annual schedule is added.
POLICY_MEETING_CALENDAR = {
    "USD": [
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    ],
    "JPY": [
        "2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16",
        "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18",
    ],
    "EUR": ["2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17"],
    "GBP": [
        "2026-02-05", "2026-03-19", "2026-04-30", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
    ],
    "AUD": [
        "2026-02-03", "2026-03-17", "2026-05-05", "2026-06-16",
        "2026-08-11", "2026-09-29", "2026-11-03", "2026-12-08",
    ],
    "MYR": ["2026-01-22", "2026-03-05", "2026-05-07", "2026-07-09", "2026-09-03", "2026-11-05"],
}
POLICY_CALENDAR_SOURCES = {
    "USD": "Federal Reserve FOMC calendar",
    "JPY": "Bank of Japan MPM schedule",
    "EUR": "ECB Governing Council calendar",
    "GBP": "Bank of England MPC calendar",
    "AUD": "Reserve Bank of Australia board schedule",
    "MYR": "Bank Negara Malaysia MPC schedule",
}

# BIS monthly central-bank policy-rate series. The euro-area reference area is XM.
BIS_POLICY_API = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0"
POLICY_AREA_CODES = {
    "USD": "US",
    "JPY": "JP",
    "EUR": "XM",
    "GBP": "GB",
    "AUD": "AU",
    "MYR": "MY",
}
CENTRAL_BANK_NAMES = {
    "USD": "Federal Reserve",
    "JPY": "Bank of Japan",
    "EUR": "European Central Bank",
    "GBP": "Bank of England",
    "AUD": "Reserve Bank of Australia",
    "MYR": "Bank Negara Malaysia",
}

# IMF WEO DataMapper country / aggregate codes. Singapore is the relative macro
# benchmark because the user is deciding when to convert SGD into foreign currency.
IMF_COUNTRY_CODES = {
    "USD": "USA",
    "JPY": "JPN",
    "EUR": "EUQ",
    "GBP": "GBR",
    "AUD": "AUS",
    "MYR": "MYS",
    "SGD": "SGP",
}
IMF_DATAMAPPER_BASES = [
    "https://www.imf.org/external/datamapper/api/v2",
    "https://www.imf.org/external/datamapper/api/v1",
]
IMF_GROWTH_INDICATOR = "NGDP_RPCH"
IMF_INFLATION_INDICATOR = "PCPIPCH"


@dataclass
class CurrencySignal:
    code: str
    name: str
    symbol: str
    unit: int
    rate_sgd: float
    inverse_per_sgd: float
    score: float
    market_score: float
    macro_score: float
    macro_coverage_pct: int
    effective_macro_weight_pct: int
    opportunity_score: float
    buy_urgency_score: float
    buy_urgency_label: str
    event_risk_score: float
    event_risk_label: str
    next_policy_meeting_date: Optional[str]
    days_to_policy_meeting: Optional[int]
    policy_calendar_source: str
    policy_direction_score: Optional[float]
    policy_direction_label: str
    urgency_component_scores: Dict[str, Optional[float]]
    forward_policy_score: float
    forward_policy_label: str
    forward_fx_momentum_score: float
    forward_fx_momentum_label: str
    forward_outlook_score: float
    forward_outlook_label: str
    forward_component_scores: Dict[str, Optional[float]]
    decision_confidence: int
    decision_confidence_label: str
    signal_agreement_pct: int
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
    macro_component_scores: Dict[str, Optional[float]]
    policy_rate_pct: Optional[float]
    policy_rate_6m_change_bps: Optional[float]
    policy_rate_12m_change_bps: Optional[float]
    policy_rate_percentile_5y: Optional[float]
    policy_data_date: Optional[str]
    growth_current_year: Optional[int]
    growth_current_pct: Optional[float]
    growth_next_year: Optional[int]
    growth_next_pct: Optional[float]
    growth_vs_sgd_current_pp: Optional[float]
    growth_vs_sgd_next_pp: Optional[float]
    inflation_current_year: Optional[int]
    inflation_current_pct: Optional[float]
    inflation_next_year: Optional[int]
    inflation_next_pct: Optional[float]
    inflation_vs_sgd_current_pp: Optional[float]
    inflation_vs_sgd_next_pp: Optional[float]
    validation_rate_sgd: Optional[float]
    validation_difference_pct: Optional[float]
    validation_status: str
    drivers: List[str]
    macro_drivers: List[str]
    urgency_drivers: List[str]
    forward_drivers: List[str]


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


def fetch_bis_policy_series(years: int = 6) -> Tuple[Dict[str, pd.Series], Dict[str, str]]:
    """Fetch monthly central-bank policy-rate history from the BIS.

    A failure for one currency does not stop the full report. Missing policy data
    simply reduces that currency's effective macro weight for the current run.
    """
    start_period = (pd.Timestamp.utcnow().normalize() - pd.DateOffset(years=years)).strftime("%Y-%m")
    series_map: Dict[str, pd.Series] = {}
    status: Dict[str, str] = {}

    for code, area in POLICY_AREA_CODES.items():
        try:
            response = _http_get(
                f"{BIS_POLICY_API}/M.{area}",
                params={"format": "csvfile", "startPeriod": start_period},
                timeout=60,
            )
            raw = pd.read_csv(io.StringIO(response.text))
            required = {"TIME_PERIOD", "OBS_VALUE"}
            if not required.issubset(raw.columns):
                raise ValueError(f"Unexpected BIS columns: {list(raw.columns)}")

            if "REF_AREA" in raw.columns:
                filtered = raw.loc[raw["REF_AREA"].astype(str) == area].copy()
                if not filtered.empty:
                    raw = filtered

            raw["TIME_PERIOD"] = pd.to_datetime(raw["TIME_PERIOD"].astype(str), errors="coerce")
            raw["OBS_VALUE"] = pd.to_numeric(raw["OBS_VALUE"], errors="coerce")
            raw = raw.dropna(subset=["TIME_PERIOD", "OBS_VALUE"])
            if raw.empty:
                raise ValueError("BIS response contained no usable observations")

            series = (
                raw.groupby("TIME_PERIOD")["OBS_VALUE"]
                .last()
                .astype(float)
                .sort_index()
            )
            series_map[code] = series
            status[code] = "Available"
        except Exception as exc:
            print(f"BIS policy-rate fetch failed for {code}: {exc}")
            status[code] = f"Unavailable: {exc.__class__.__name__}"

    return series_map, status


def _extract_imf_values(payload: dict, indicator: str, code: str) -> Dict[int, float]:
    """Extract a country-year series from common IMF DataMapper response shapes."""
    candidates = []
    values = payload.get("values") if isinstance(payload, dict) else None
    if isinstance(values, dict):
        indicator_block = values.get(indicator)
        if isinstance(indicator_block, dict):
            candidates.append(indicator_block.get(code))
        candidates.append(values.get(code))

    if isinstance(payload, dict):
        indicator_block = payload.get(indicator)
        if isinstance(indicator_block, dict):
            candidates.append(indicator_block.get(code))

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        result: Dict[int, float] = {}
        for year, value in candidate.items():
            try:
                year_int = int(str(year)[:4])
                value_float = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value_float):
                result[year_int] = value_float
        if result:
            return result
    return {}


def fetch_imf_indicator(indicator: str) -> Tuple[Dict[str, Dict[int, float]], str]:
    """Fetch one IMF WEO indicator for all tracked economies plus Singapore."""
    unique_codes = list(dict.fromkeys(IMF_COUNTRY_CODES.values()))
    code_path = "/".join(unique_codes)
    last_error: Optional[Exception] = None

    for base in IMF_DATAMAPPER_BASES:
        try:
            response = _http_get(f"{base}/{indicator}/{code_path}", timeout=60)
            payload = response.json()
            result: Dict[str, Dict[int, float]] = {}
            for fx_code, imf_code in IMF_COUNTRY_CODES.items():
                result[fx_code] = _extract_imf_values(payload, indicator, imf_code)

            if any(result.values()):
                api_version = "v2" if base.endswith("/v2") else "v1 fallback"
                return result, f"IMF WEO DataMapper {api_version}"
            raise ValueError("IMF response contained no usable country series")
        except Exception as exc:
            last_error = exc
            print(f"IMF DataMapper {indicator} fetch failed from {base}: {exc}")

    raise RuntimeError(f"IMF DataMapper unavailable for {indicator}: {last_error}")


def _year_value(series: Dict[int, float], year: int) -> Optional[float]:
    value = series.get(year)
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def fetch_imf_macro_snapshot() -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Fetch current-year and next-year IMF WEO growth and inflation projections.

    The function is intentionally fail-soft. Growth and inflation are fetched
    independently so one unavailable indicator does not suppress the other.
    """
    current_year = datetime.now(timezone.utc).year
    next_year = current_year + 1
    status = {"growth": "Unavailable", "inflation": "Unavailable"}

    try:
        growth, growth_source = fetch_imf_indicator(IMF_GROWTH_INDICATOR)
        status["growth"] = growth_source
    except Exception as exc:
        print(f"IMF growth data unavailable: {exc}")
        growth = {code: {} for code in IMF_COUNTRY_CODES}

    try:
        inflation, inflation_source = fetch_imf_indicator(IMF_INFLATION_INDICATOR)
        status["inflation"] = inflation_source
    except Exception as exc:
        print(f"IMF inflation data unavailable: {exc}")
        inflation = {code: {} for code in IMF_COUNTRY_CODES}

    snapshot: Dict[str, dict] = {}
    for code in IMF_COUNTRY_CODES:
        snapshot[code] = {
            "growth_current_year": current_year,
            "growth_current_pct": _year_value(growth.get(code, {}), current_year),
            "growth_next_year": next_year,
            "growth_next_pct": _year_value(growth.get(code, {}), next_year),
            "inflation_current_year": current_year,
            "inflation_current_pct": _year_value(inflation.get(code, {}), current_year),
            "inflation_next_year": next_year,
            "inflation_next_pct": _year_value(inflation.get(code, {}), next_year),
        }

    return snapshot, status


def policy_direction_score(change_bps: Optional[float]) -> Optional[float]:
    if change_bps is None or not math.isfinite(change_bps):
        return None
    # Roughly +/-100 bp over the lookback produces a strong, but not absolute,
    # directional signal. Tightening raises buy urgency; easing lowers it.
    return float(np.clip(2.5 + 2.5 * np.tanh(change_bps / 100.0), 0, 5))


def policy_direction_label(score: Optional[float]) -> str:
    if score is None:
        return "Unavailable"
    if score >= 4.1:
        return "Strongly hawkish"
    if score >= 3.1:
        return "Hawkish"
    if score > 1.9:
        return "Broadly neutral"
    if score > 0.9:
        return "Dovish"
    return "Strongly dovish"


def next_policy_meeting(code: str, as_of=None) -> Dict[str, object]:
    today = as_of or datetime.now(timezone.utc).date()
    dates = []
    for raw in POLICY_MEETING_CALENDAR.get(code, []):
        try:
            dates.append(pd.Timestamp(raw).date())
        except Exception:
            continue
    upcoming = [item for item in dates if item >= today]
    next_date = min(upcoming) if upcoming else None
    days = None if next_date is None else (next_date - today).days
    return {
        "date": None if next_date is None else next_date.isoformat(),
        "days": days,
        "source": POLICY_CALENDAR_SOURCES.get(code, "Official central-bank calendar"),
    }


def event_risk_from_days(days: Optional[int]) -> Tuple[float, str]:
    if days is None:
        return 1.5, "Calendar rollover needed"
    if days <= 3:
        return 5.0, "Very high"
    if days <= 7:
        return 4.6, "High"
    if days <= 14:
        return 4.0, "Elevated"
    if days <= 30:
        return 3.3, "Moderate"
    if days <= 60:
        return 2.5, "Normal"
    if days <= 90:
        return 2.0, "Low"
    return 1.5, "Very low"


def buyer_strengthening_score(change_pct: Optional[float], scale: float) -> Optional[float]:
    if change_pct is None or not math.isfinite(change_pct):
        return None
    # Positive SGD cost change means the foreign currency is becoming more expensive,
    # which increases urgency for a buyer who already likes the valuation.
    return float(np.clip(2.5 + 2.5 * np.tanh(change_pct / scale), 0, 5))


def _directional_score(delta: Optional[float], scale: float) -> Optional[float]:
    if delta is None or not math.isfinite(delta):
        return None
    return float(np.clip(2.5 + 2.5 * np.tanh(delta / scale), 0, 5))


def forward_policy_bias(macro: Dict[str, object]) -> Dict[str, object]:
    """Estimate forward policy pressure from existing official data.

    This is deliberately labelled model-implied rather than market-implied. It
    combines the recent BIS policy-rate path with the direction of IMF inflation
    and growth forecasts. A higher score means a stronger tightening / currency-
    supportive bias, which can increase urgency for an SGD buyer.
    """
    policy = macro.get("policy", {}) or {}
    direction_6m = policy_direction_score(policy.get("change_6m_bps"))
    direction_12m = policy_direction_score(policy.get("change_12m_bps"))
    recent_path = None
    if direction_6m is not None or direction_12m is not None:
        recent_path = weighted_average([(direction_6m, 0.65), (direction_12m, 0.35)])

    inflation_current = macro.get("inflation_current_pct")
    inflation_next = macro.get("inflation_next_pct")
    inflation_vs_sgd_next = macro.get("inflation_vs_sgd_next_pp")
    inflation_path = None
    if inflation_current is not None and inflation_next is not None:
        inflation_path = _directional_score(float(inflation_next) - float(inflation_current), 1.5)
    relative_inflation_pressure = _directional_score(
        None if inflation_vs_sgd_next is None else float(inflation_vs_sgd_next),
        2.5,
    )
    inflation_pressure = None
    if inflation_path is not None or relative_inflation_pressure is not None:
        inflation_pressure = weighted_average([
            (inflation_path, 0.70),
            (relative_inflation_pressure, 0.30),
        ])

    growth_current = macro.get("growth_current_pct")
    growth_next = macro.get("growth_next_pct")
    growth_vs_sgd_next = macro.get("growth_vs_sgd_next_pp")
    growth_path = None
    if growth_current is not None and growth_next is not None:
        growth_path = _directional_score(float(growth_next) - float(growth_current), 2.0)
    relative_growth_pressure = _directional_score(
        None if growth_vs_sgd_next is None else float(growth_vs_sgd_next),
        3.0,
    )
    growth_pressure = None
    if growth_path is not None or relative_growth_pressure is not None:
        growth_pressure = weighted_average([
            (growth_path, 0.65),
            (relative_growth_pressure, 0.35),
        ])

    components: Dict[str, Optional[float]] = {
        "recent_policy_path": None if recent_path is None else round(float(recent_path), 2),
        "inflation_pressure": None if inflation_pressure is None else round(float(inflation_pressure), 2),
        "growth_pressure": None if growth_pressure is None else round(float(growth_pressure), 2),
    }
    score = weighted_average(
        [(components[key], FORWARD_POLICY_WEIGHTS[key]) for key in FORWARD_POLICY_WEIGHTS],
        default=2.5,
    )
    score = round(float(np.clip(score, 0, 5)), 2)

    if score >= 4.10:
        label = "Strong tightening bias"
    elif score >= 3.10:
        label = "Tightening bias"
    elif score > 1.90:
        label = "Balanced / uncertain"
    elif score > 0.90:
        label = "Easing bias"
    else:
        label = "Strong easing bias"

    drivers: List[str] = []
    if recent_path is not None:
        drivers.append(f"Recent policy path points to {policy_direction_label(recent_path).lower()} conditions.")
    if inflation_current is not None and inflation_next is not None:
        direction = "higher" if float(inflation_next) > float(inflation_current) else "lower"
        drivers.append(f"IMF inflation is projected {direction} next year, affecting future policy pressure.")
    if growth_current is not None and growth_next is not None:
        direction = "stronger" if float(growth_next) > float(growth_current) else "softer"
        drivers.append(f"IMF growth is projected {direction} next year, influencing the model-implied policy bias.")
    if not drivers:
        drivers.append("Insufficient macro inputs for a strong forward-policy signal; the model stays near neutral.")

    return {
        "score": score,
        "label": label,
        "components": components,
        "drivers": drivers[:3],
    }


def forward_fx_momentum(
    current: float,
    change_7d: Optional[float],
    change_30d: Optional[float],
    change_90d: Optional[float],
    ma20: Optional[float],
    ma50: Optional[float],
) -> Dict[str, object]:
    """Score whether the foreign currency appears to be strengthening versus SGD.

    Higher means the SGD cost is rising / momentum is turning against the buyer,
    which increases urgency when valuation is already attractive.
    """
    s7 = buyer_strengthening_score(change_7d, 1.5)
    s30 = buyer_strengthening_score(change_30d, 3.0)
    s90 = buyer_strengthening_score(change_90d, 6.0)

    ma_scores: List[Tuple[Optional[float], float]] = []
    if ma20 is not None and ma20 > 0:
        ma_scores.append((buyer_strengthening_score((current / ma20 - 1.0) * 100.0, 2.0), 0.55))
    if ma50 is not None and ma50 > 0:
        ma_scores.append((buyer_strengthening_score((current / ma50 - 1.0) * 100.0, 3.5), 0.45))
    ma_structure = weighted_average(ma_scores, default=2.5)

    components: Dict[str, Optional[float]] = {
        "7d_strengthening": None if s7 is None else round(float(s7), 2),
        "30d_strengthening": None if s30 is None else round(float(s30), 2),
        "90d_strengthening": None if s90 is None else round(float(s90), 2),
        "ma_structure": round(float(ma_structure), 2),
    }
    score = weighted_average(
        [(components[key], FORWARD_MOMENTUM_WEIGHTS[key]) for key in FORWARD_MOMENTUM_WEIGHTS],
        default=2.5,
    )
    score = round(float(np.clip(score, 0, 5)), 2)

    if score >= 4.10:
        label = "Strong strengthening"
    elif score >= 3.10:
        label = "Strengthening"
    elif score > 1.90:
        label = "Mixed / range-bound"
    elif score > 0.90:
        label = "Weakening"
    else:
        label = "Strong weakening"

    drivers = []
    if score >= 3.1:
        drivers.append("Recent price structure suggests the foreign currency is gaining strength against SGD.")
    elif score <= 1.9:
        drivers.append("Recent price structure still favours the SGD buyer, reducing the need to chase the rate.")
    else:
        drivers.append("Forward FX momentum is mixed and does not show a decisive reversal yet.")
    if change_30d is not None:
        direction = "more expensive" if change_30d > 0 else "cheaper"
        drivers.append(f"Over one month the currency became {abs(change_30d):.2f}% {direction} in SGD terms.")

    return {
        "score": score,
        "label": label,
        "components": components,
        "drivers": drivers[:2],
    }


def decision_confidence_score(
    data_confidence: int,
    macro_coverage: float,
    support_scores: List[Optional[float]],
) -> Tuple[int, str, int]:
    valid = [float(v) for v in support_scores if v is not None and math.isfinite(v)]
    if len(valid) < 3:
        agreement = 50
    else:
        dispersion = float(np.std(valid))
        agreement = int(round(np.clip(100.0 * (1.0 - dispersion / 2.5), 0, 100)))

    confidence = int(round(
        0.50 * data_confidence
        + 0.35 * agreement
        + 0.15 * (macro_coverage * 100.0)
    ))
    confidence = int(np.clip(confidence, 45, 95))
    label = "High" if confidence >= 80 else "Medium" if confidence >= 65 else "Low"
    return confidence, label, agreement


def calculate_buy_urgency(
    code: str,
    percentile_5y: Optional[float],
    forward_policy: Dict[str, object],
    forward_momentum: Dict[str, object],
) -> Dict[str, object]:
    forward_policy_score = float(forward_policy.get("score", 2.5))
    forward_momentum_score = float(forward_momentum.get("score", 2.5))

    rarity_score = None
    if percentile_5y is not None and math.isfinite(percentile_5y):
        rarity_score = float(np.clip(5.0 * (1.0 - percentile_5y / 100.0), 0, 5))

    meeting = next_policy_meeting(code)
    event_risk_score, event_risk_label = event_risk_from_days(meeting.get("days"))
    proximity = max(0.0, min(1.0, (event_risk_score - 1.5) / 3.5))
    # A nearby meeting matters more when the model already sees a tightening bias;
    # an easing bias can reduce urgency instead of automatically creating fear.
    event_setup_score = 2.5 + (forward_policy_score - 2.5) * proximity
    event_setup_score = float(np.clip(event_setup_score, 0, 5))

    components = {
        "forward_policy_bias": round(forward_policy_score, 2),
        "forward_fx_momentum": round(forward_momentum_score, 2),
        "valuation_rarity": None if rarity_score is None else round(float(rarity_score), 2),
        "event_setup": round(float(event_setup_score), 2),
    }
    urgency_score = weighted_average(
        [(components[key], URGENCY_WEIGHTS[key]) for key in URGENCY_WEIGHTS],
        default=2.5,
    )
    urgency_score = round(float(np.clip(urgency_score, 0, 5)), 2)

    if urgency_score >= 4.25:
        urgency_label = "Very high"
    elif urgency_score >= 3.50:
        urgency_label = "High"
    elif urgency_score >= 2.75:
        urgency_label = "Moderate"
    elif urgency_score >= 2.00:
        urgency_label = "Low"
    else:
        urgency_label = "Very low"

    drivers = [
        f"Forward policy bias is {str(forward_policy.get('label', 'uncertain')).lower()} (model-implied, not futures-implied).",
        f"Forward FX momentum is {str(forward_momentum.get('label', 'mixed')).lower()} based on 7D/30D/90D price structure.",
    ]
    if meeting.get("date") is not None:
        drivers.append(
            f"Next {POLICY_CALENDAR_SOURCES.get(code, 'policy')} event is in {meeting.get('days')} days ({meeting.get('date')}); event risk is {event_risk_label.lower()}."
        )
    else:
        drivers.append("No later meeting is stored in the current calendar; refresh the annual schedule before the next policy cycle.")

    return {
        "score": urgency_score,
        "label": urgency_label,
        "components": components,
        "policy_direction_score": round(forward_policy_score, 2),
        "policy_direction_label": str(forward_policy.get("label", "Unavailable")),
        "event_risk_score": round(float(event_risk_score), 2),
        "event_risk_label": event_risk_label,
        "next_policy_meeting_date": meeting.get("date"),
        "days_to_policy_meeting": meeting.get("days"),
        "policy_calendar_source": meeting.get("source"),
        "drivers": drivers[:3],
    }

def analyse_policy_series(series: Optional[pd.Series]) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {
        "score": None,
        "rate": None,
        "change_6m_bps": None,
        "change_12m_bps": None,
        "percentile_5y": None,
        "data_date": None,
    }
    if series is None:
        return result

    clean = series.dropna().sort_index()
    if clean.empty:
        return result

    current = float(clean.iloc[-1])
    latest_date = clean.index[-1]
    six_month_old = value_at_or_before(clean, 183)
    twelve_month_old = value_at_or_before(clean, 365)
    change_6m_bps = None if six_month_old is None else (current - six_month_old) * 100.0
    change_12m_bps = None if twelve_month_old is None else (current - twelve_month_old) * 100.0

    five_year = clean.loc[clean.index >= latest_date - pd.DateOffset(years=5)]
    rate_percentile = percentile_rank(five_year, current)
    # Phase 2C deliberately keeps recent policy direction out of the Opportunity
    # Score so that it is not double-counted. The macro backdrop uses the current
    # policy-rate level relative to its own five-year history; recent tightening or
    # easing is handled separately by the Buy Urgency model.
    level_score = None if rate_percentile is None else 5.0 * rate_percentile / 100.0
    score = level_score

    result.update({
        "score": None if score is None else float(np.clip(score, 0, 5)),
        "rate": current,
        "change_6m_bps": change_6m_bps,
        "change_12m_bps": change_12m_bps,
        "percentile_5y": rate_percentile,
        "data_date": pd.Timestamp(latest_date).date().isoformat(),
    })
    return result


def relative_growth_score(foreign: Optional[float], singapore: Optional[float]) -> Optional[float]:
    if foreign is None or singapore is None:
        return None
    differential = foreign - singapore
    return float(np.clip(2.5 + 2.5 * np.tanh(differential / 2.5), 0, 5))


def relative_inflation_score(foreign: Optional[float], singapore: Optional[float]) -> Optional[float]:
    if foreign is None or singapore is None:
        return None
    # Higher inflation than Singapore is generally a headwind to the foreign
    # currency's purchasing power. Lower relative inflation is supportive.
    differential = foreign - singapore
    return float(np.clip(2.5 - 2.5 * np.tanh(differential / 3.0), 0, 5))


def analyse_macro_components(
    code: str,
    policy_series: Optional[pd.Series],
    macro_snapshot: Dict[str, dict],
) -> Dict[str, object]:
    policy = analyse_policy_series(policy_series)
    foreign = macro_snapshot.get(code, {})
    singapore = macro_snapshot.get("SGD", {})

    growth_current = foreign.get("growth_current_pct")
    growth_next = foreign.get("growth_next_pct")
    sg_growth_current = singapore.get("growth_current_pct")
    sg_growth_next = singapore.get("growth_next_pct")
    growth_current_score = relative_growth_score(growth_current, sg_growth_current)
    growth_next_score = relative_growth_score(growth_next, sg_growth_next)
    growth_score = weighted_average(
        [(growth_current_score, 0.40), (growth_next_score, 0.60)],
        default=2.5,
    ) if any(v is not None for v in [growth_current_score, growth_next_score]) else None

    inflation_current = foreign.get("inflation_current_pct")
    inflation_next = foreign.get("inflation_next_pct")
    sg_inflation_current = singapore.get("inflation_current_pct")
    sg_inflation_next = singapore.get("inflation_next_pct")
    inflation_current_score = relative_inflation_score(inflation_current, sg_inflation_current)
    inflation_next_score = relative_inflation_score(inflation_next, sg_inflation_next)
    inflation_score = weighted_average(
        [(inflation_current_score, 0.40), (inflation_next_score, 0.60)],
        default=2.5,
    ) if any(v is not None for v in [inflation_current_score, inflation_next_score]) else None

    components: Dict[str, Optional[float]] = {
        "policy": None if policy["score"] is None else round(float(policy["score"]), 2),
        "growth": None if growth_score is None else round(float(growth_score), 2),
        "inflation": None if inflation_score is None else round(float(inflation_score), 2),
    }

    available_weight = sum(MACRO_WEIGHTS[key] for key, value in components.items() if value is not None)
    macro_coverage = available_weight / sum(MACRO_WEIGHTS.values())
    macro_score = weighted_average(
        [(components[key], MACRO_WEIGHTS[key]) for key in MACRO_WEIGHTS],
        default=2.5,
    )

    growth_vs_sgd_current = None
    if growth_current is not None and sg_growth_current is not None:
        growth_vs_sgd_current = float(growth_current) - float(sg_growth_current)
    growth_vs_sgd_next = None
    if growth_next is not None and sg_growth_next is not None:
        growth_vs_sgd_next = float(growth_next) - float(sg_growth_next)

    inflation_vs_sgd_current = None
    if inflation_current is not None and sg_inflation_current is not None:
        inflation_vs_sgd_current = float(inflation_current) - float(sg_inflation_current)
    inflation_vs_sgd_next = None
    if inflation_next is not None and sg_inflation_next is not None:
        inflation_vs_sgd_next = float(inflation_next) - float(sg_inflation_next)

    return {
        "macro_score": round(float(np.clip(macro_score, 0, 5)), 2),
        "macro_coverage": float(np.clip(macro_coverage, 0, 1)),
        "components": components,
        "policy": policy,
        "growth_current_year": foreign.get("growth_current_year"),
        "growth_current_pct": growth_current,
        "growth_next_year": foreign.get("growth_next_year"),
        "growth_next_pct": growth_next,
        "growth_vs_sgd_current_pp": growth_vs_sgd_current,
        "growth_vs_sgd_next_pp": growth_vs_sgd_next,
        "inflation_current_year": foreign.get("inflation_current_year"),
        "inflation_current_pct": inflation_current,
        "inflation_next_year": foreign.get("inflation_next_year"),
        "inflation_next_pct": inflation_next,
        "inflation_vs_sgd_current_pp": inflation_vs_sgd_current,
        "inflation_vs_sgd_next_pp": inflation_vs_sgd_next,
    }


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


def recommendation_from_score(opportunity_score: float, urgency_score: float) -> Tuple[str, str, int]:
    """Opportunity-first recommendation matrix for Phase 2C.

    Urgency can accelerate or slow a staged purchase only when the underlying
    opportunity is already reasonable. It cannot turn an expensive currency into
    a Buy merely because that currency is strengthening.
    """
    if opportunity_score >= 4.5:
        if urgency_score >= 3.75:
            return "Exceptional Buy", "Buy a meaningful tranche now", 40
        return "Strong Buy", "Buy in stages while value remains exceptional", 30
    if opportunity_score >= 4.0:
        if urgency_score >= 3.5:
            return "Buy Now", "Start or accelerate staged buying", 30
        return "Buy", "Buy in stages", 25
    if opportunity_score >= 3.5:
        if urgency_score >= 4.0:
            return "Accumulate Now", "Start or continue gradual buying now", 20
        if urgency_score >= 2.5:
            return "Accumulate", "Start or continue gradual buying", 15
        return "Patient Accumulate", "Small staged purchases; no need to rush", 10
    if opportunity_score >= 3.0:
        if urgency_score >= 4.0:
            return "Light Accumulate", "Small tranche only before the window changes", 10
        return "Wait", "Wait for a better rate unless funds are needed", 0
    if opportunity_score >= 2.25:
        return "Wait", "Wait for a better rate unless funds are needed", 0
    if opportunity_score >= 1.5:
        return "Expensive", "Avoid a large discretionary purchase", 0
    return "Avoid", "Poor accumulation zone", 0


def confidence_score(
    series: pd.Series,
    validation_difference: Optional[float],
    macro_coverage: float,
) -> Tuple[int, str]:
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

    # The model receives a modest confidence lift when the macro-policy layer has
    # broad coverage, while still recognising that macro forecasts are uncertain.
    if macro_coverage >= 0.95:
        confidence += 7
    elif macro_coverage >= 0.70:
        confidence += 4
    elif macro_coverage >= 0.40:
        confidence += 2

    confidence = int(np.clip(confidence, 55, 92))
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


def build_macro_drivers(code: str, macro: Dict[str, object]) -> List[str]:
    drivers: List[str] = []
    policy = macro.get("policy", {})
    policy_rate = policy.get("rate") if isinstance(policy, dict) else None
    change_6m = policy.get("change_6m_bps") if isinstance(policy, dict) else None

    if policy_rate is not None:
        direction = "unchanged"
        if change_6m is not None and change_6m >= 12.5:
            direction = f"up {abs(change_6m):.0f} bp over 6 months"
        elif change_6m is not None and change_6m <= -12.5:
            direction = f"down {abs(change_6m):.0f} bp over 6 months"
        drivers.append(
            f"{CENTRAL_BANK_NAMES.get(code, 'Central bank')} policy rate is {policy_rate:.2f}% and {direction}."
        )

    growth_current = macro.get("growth_current_pct")
    growth_next = macro.get("growth_next_pct")
    growth_current_year = macro.get("growth_current_year")
    growth_next_year = macro.get("growth_next_year")
    growth_diff_next = macro.get("growth_vs_sgd_next_pp")
    if growth_current is not None or growth_next is not None:
        parts = []
        if growth_current is not None:
            parts.append(f"{growth_current_year}: {float(growth_current):.1f}%")
        if growth_next is not None:
            parts.append(f"{growth_next_year}: {float(growth_next):.1f}%")
        comparison = ""
        if growth_diff_next is not None:
            relation = "above" if float(growth_diff_next) >= 0 else "below"
            comparison = f", {abs(float(growth_diff_next)):.1f} pp {relation} Singapore next year"
        drivers.append(f"IMF real-GDP growth outlook is {'; '.join(parts)}{comparison}.")

    inflation_current = macro.get("inflation_current_pct")
    inflation_next = macro.get("inflation_next_pct")
    inflation_current_year = macro.get("inflation_current_year")
    inflation_next_year = macro.get("inflation_next_year")
    inflation_diff_next = macro.get("inflation_vs_sgd_next_pp")
    if inflation_current is not None or inflation_next is not None:
        parts = []
        if inflation_current is not None:
            parts.append(f"{inflation_current_year}: {float(inflation_current):.1f}%")
        if inflation_next is not None:
            parts.append(f"{inflation_next_year}: {float(inflation_next):.1f}%")
        comparison = ""
        if inflation_diff_next is not None:
            relation = "above" if float(inflation_diff_next) >= 0 else "below"
            comparison = f", {abs(float(inflation_diff_next)):.1f} pp {relation} Singapore next year"
        drivers.append(f"IMF inflation outlook is {'; '.join(parts)}{comparison}.")

    if not drivers:
        drivers.append("Macro-policy data is temporarily unavailable; the final score falls back toward the market model.")
    return drivers[:3]


def analyse_currency(
    code: str,
    series: pd.Series,
    validation_rates: Dict[str, float],
    policy_series_map: Dict[str, pd.Series],
    macro_snapshot: Dict[str, dict],
) -> CurrencySignal:
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
    market_score = sum(component_scores[key] * MARKET_WEIGHTS[key] for key in MARKET_WEIGHTS)
    market_score = round(float(np.clip(market_score, 0, 5)), 2)

    macro = analyse_macro_components(
        code=code,
        policy_series=policy_series_map.get(code),
        macro_snapshot=macro_snapshot,
    )
    macro_score = float(macro["macro_score"])
    macro_coverage = float(macro["macro_coverage"])
    effective_macro_weight = MAX_MACRO_WEIGHT * macro_coverage
    opportunity_score = market_score * (1.0 - effective_macro_weight) + macro_score * effective_macro_weight
    opportunity_score = round(float(np.clip(opportunity_score, 0, 5)), 2)

    policy = macro.get("policy", {})
    forward_policy = forward_policy_bias(macro)
    forward_momentum = forward_fx_momentum(
        current=current,
        change_7d=change_7d,
        change_30d=change_30d,
        change_90d=change_90d,
        ma20=ma20,
        ma50=ma50,
    )
    forward_outlook_score = weighted_average([
        (float(forward_policy["score"]), FORWARD_OUTLOOK_WEIGHTS["policy_bias"]),
        (float(forward_momentum["score"]), FORWARD_OUTLOOK_WEIGHTS["fx_momentum"]),
    ])
    forward_outlook_score = round(float(np.clip(forward_outlook_score, 0, 5)), 2)
    if forward_outlook_score >= 4.1:
        forward_outlook_label = "Strongly supportive of buying sooner"
    elif forward_outlook_score >= 3.1:
        forward_outlook_label = "Supportive of buying sooner"
    elif forward_outlook_score > 1.9:
        forward_outlook_label = "Mixed / neutral"
    elif forward_outlook_score > 0.9:
        forward_outlook_label = "Supports waiting"
    else:
        forward_outlook_label = "Strongly supports waiting"

    urgency = calculate_buy_urgency(
        code=code,
        percentile_5y=percentiles.get("5y"),
        forward_policy=forward_policy,
        forward_momentum=forward_momentum,
    )
    recommendation, action, buy_pct = recommendation_from_score(opportunity_score, float(urgency["score"]))

    validation_rate = validation_rates.get(code)
    validation_diff = None
    if validation_rate is not None and current > 0:
        validation_diff = abs(validation_rate / current - 1.0) * 100.0

    confidence, confidence_label = confidence_score(series, validation_diff, macro_coverage)
    decision_confidence, decision_confidence_label, signal_agreement = decision_confidence_score(
        confidence,
        macro_coverage,
        [
            historical_score,
            timing_score,
            mom_score,
            macro_score,
            float(forward_policy["score"]),
            float(forward_momentum["score"]),
        ],
    )

    one_year = series.loc[series.index >= series.index[-1] - pd.DateOffset(years=1)]
    low_52w = float(one_year.min()) if not one_year.empty else None
    high_52w = float(one_year.max()) if not one_year.empty else None

    market_drivers = build_drivers(
        percentiles.get("5y"),
        change_30d,
        rsi,
        current,
        ma200,
        annualized_vol,
    )
    macro_drivers = build_macro_drivers(code, macro)
    forward_drivers = list(forward_policy.get("drivers", []))[:2] + list(forward_momentum.get("drivers", []))[:2]

    # inverse_per_sgd expresses how many units of the underlying currency S$1 buys.
    # Because JPY is displayed in units of 100, convert back to a one-unit basis first.
    per_currency_unit_cost = current / unit
    inverse_per_sgd = 1.0 / per_currency_unit_cost

    macro_components = macro.get("components", {})

    return CurrencySignal(
        code=code,
        name=str(config["name"]),
        symbol=str(config["symbol"]),
        unit=unit,
        rate_sgd=round(current, 6),
        inverse_per_sgd=round(inverse_per_sgd, 6),
        score=opportunity_score,
        market_score=market_score,
        macro_score=round(macro_score, 2),
        macro_coverage_pct=int(round(macro_coverage * 100)),
        effective_macro_weight_pct=int(round(effective_macro_weight * 100)),
        opportunity_score=opportunity_score,
        buy_urgency_score=float(urgency["score"]),
        buy_urgency_label=str(urgency["label"]),
        event_risk_score=float(urgency["event_risk_score"]),
        event_risk_label=str(urgency["event_risk_label"]),
        next_policy_meeting_date=urgency.get("next_policy_meeting_date"),
        days_to_policy_meeting=urgency.get("days_to_policy_meeting"),
        policy_calendar_source=str(urgency.get("policy_calendar_source", "Official central-bank calendar")),
        policy_direction_score=urgency.get("policy_direction_score"),
        policy_direction_label=str(urgency.get("policy_direction_label", "Unavailable")),
        urgency_component_scores={
            key: None if value is None else round(float(value), 2)
            for key, value in urgency.get("components", {}).items()
        },
        forward_policy_score=round(float(forward_policy["score"]), 2),
        forward_policy_label=str(forward_policy["label"]),
        forward_fx_momentum_score=round(float(forward_momentum["score"]), 2),
        forward_fx_momentum_label=str(forward_momentum["label"]),
        forward_outlook_score=forward_outlook_score,
        forward_outlook_label=forward_outlook_label,
        forward_component_scores={
            "policy_recent_path": forward_policy.get("components", {}).get("recent_policy_path"),
            "policy_inflation_pressure": forward_policy.get("components", {}).get("inflation_pressure"),
            "policy_growth_pressure": forward_policy.get("components", {}).get("growth_pressure"),
            "momentum_7d": forward_momentum.get("components", {}).get("7d_strengthening"),
            "momentum_30d": forward_momentum.get("components", {}).get("30d_strengthening"),
            "momentum_90d": forward_momentum.get("components", {}).get("90d_strengthening"),
            "momentum_ma_structure": forward_momentum.get("components", {}).get("ma_structure"),
        },
        decision_confidence=decision_confidence,
        decision_confidence_label=decision_confidence_label,
        signal_agreement_pct=signal_agreement,
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
        macro_component_scores={
            key: None if value is None else round(float(value), 2)
            for key, value in macro_components.items()
        },
        policy_rate_pct=None if policy.get("rate") is None else round(float(policy["rate"]), 3),
        policy_rate_6m_change_bps=None if policy.get("change_6m_bps") is None else round(float(policy["change_6m_bps"]), 1),
        policy_rate_12m_change_bps=None if policy.get("change_12m_bps") is None else round(float(policy["change_12m_bps"]), 1),
        policy_rate_percentile_5y=None if policy.get("percentile_5y") is None else round(float(policy["percentile_5y"]), 1),
        policy_data_date=policy.get("data_date"),
        growth_current_year=macro.get("growth_current_year"),
        growth_current_pct=None if macro.get("growth_current_pct") is None else round(float(macro["growth_current_pct"]), 2),
        growth_next_year=macro.get("growth_next_year"),
        growth_next_pct=None if macro.get("growth_next_pct") is None else round(float(macro["growth_next_pct"]), 2),
        growth_vs_sgd_current_pp=None if macro.get("growth_vs_sgd_current_pp") is None else round(float(macro["growth_vs_sgd_current_pp"]), 2),
        growth_vs_sgd_next_pp=None if macro.get("growth_vs_sgd_next_pp") is None else round(float(macro["growth_vs_sgd_next_pp"]), 2),
        inflation_current_year=macro.get("inflation_current_year"),
        inflation_current_pct=None if macro.get("inflation_current_pct") is None else round(float(macro["inflation_current_pct"]), 2),
        inflation_next_year=macro.get("inflation_next_year"),
        inflation_next_pct=None if macro.get("inflation_next_pct") is None else round(float(macro["inflation_next_pct"]), 2),
        inflation_vs_sgd_current_pp=None if macro.get("inflation_vs_sgd_current_pp") is None else round(float(macro["inflation_vs_sgd_current_pp"]), 2),
        inflation_vs_sgd_next_pp=None if macro.get("inflation_vs_sgd_next_pp") is None else round(float(macro["inflation_vs_sgd_next_pp"]), 2),
        validation_rate_sgd=None if validation_rate is None else round(validation_rate, 6),
        validation_difference_pct=None if validation_diff is None else round(validation_diff, 2),
        validation_status=validation_status(validation_diff),
        drivers=market_drivers[:3],
        macro_drivers=macro_drivers,
        urgency_drivers=list(urgency.get("drivers", [])),
        forward_drivers=forward_drivers[:4],
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


def write_macro_snapshot(
    signals: List[CurrencySignal],
    policy_status: Dict[str, str],
    imf_status: Dict[str, str],
    macro_snapshot: Dict[str, dict],
) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "policy_source": "BIS central bank policy rates",
        "macro_source": "IMF World Economic Outlook via DataMapper",
        "policy_status": policy_status,
        "imf_status": imf_status,
        "singapore_baseline": macro_snapshot.get("SGD", {}),
        "currencies": {
            signal.code: {
                "macro_score": signal.macro_score,
                "macro_coverage_pct": signal.macro_coverage_pct,
                "effective_macro_weight_pct": signal.effective_macro_weight_pct,
                "macro_component_scores": signal.macro_component_scores,
                "policy_rate_pct": signal.policy_rate_pct,
                "policy_rate_6m_change_bps": signal.policy_rate_6m_change_bps,
                "policy_rate_12m_change_bps": signal.policy_rate_12m_change_bps,
                "policy_rate_percentile_5y": signal.policy_rate_percentile_5y,
                "policy_data_date": signal.policy_data_date,
                "growth_current_year": signal.growth_current_year,
                "growth_current_pct": signal.growth_current_pct,
                "growth_next_year": signal.growth_next_year,
                "growth_next_pct": signal.growth_next_pct,
                "inflation_current_year": signal.inflation_current_year,
                "inflation_current_pct": signal.inflation_current_pct,
                "inflation_next_year": signal.inflation_next_year,
                "inflation_next_pct": signal.inflation_next_pct,
                "forward_policy_score": signal.forward_policy_score,
                "forward_policy_label": signal.forward_policy_label,
                "forward_fx_momentum_score": signal.forward_fx_momentum_score,
                "forward_fx_momentum_label": signal.forward_fx_momentum_label,
                "forward_outlook_score": signal.forward_outlook_score,
                "forward_outlook_label": signal.forward_outlook_label,
                "decision_confidence": signal.decision_confidence,
                "signal_agreement_pct": signal.signal_agreement_pct,
            }
            for signal in signals
        },
    }
    (DATA_DIR / "macro_snapshot.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_policy_calendar_snapshot(signals: List[CurrencySignal]) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "note": "Official 2026 decision dates embedded for reliable daily event-risk scoring.",
        "sources": POLICY_CALENDAR_SOURCES,
        "calendars": POLICY_MEETING_CALENDAR,
        "next_events": {
            signal.code: {
                "next_policy_meeting_date": signal.next_policy_meeting_date,
                "days_to_policy_meeting": signal.days_to_policy_meeting,
                "event_risk_label": signal.event_risk_label,
                "policy_calendar_source": signal.policy_calendar_source,
            }
            for signal in signals
        },
    }
    (DATA_DIR / "policy_calendar.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        "opportunity_scores": {signal.code: signal.opportunity_score for signal in signals},
        "buy_urgency_scores": {signal.code: signal.buy_urgency_score for signal in signals},
        "forward_policy_scores": {signal.code: signal.forward_policy_score for signal in signals},
        "forward_fx_momentum_scores": {signal.code: signal.forward_fx_momentum_score for signal in signals},
        "forward_outlook_scores": {signal.code: signal.forward_outlook_score for signal in signals},
        "decision_confidence": {signal.code: signal.decision_confidence for signal in signals},
        "signal_agreement_pct": {signal.code: signal.signal_agreement_pct for signal in signals},
        "event_risk_labels": {signal.code: signal.event_risk_label for signal in signals},
        "next_policy_meeting_dates": {signal.code: signal.next_policy_meeting_date for signal in signals},
        "market_scores": {signal.code: signal.market_score for signal in signals},
        "macro_scores": {signal.code: signal.macro_score for signal in signals},
        "macro_coverage_pct": {signal.code: signal.macro_coverage_pct for signal in signals},
        "effective_macro_weight_pct": {signal.code: signal.effective_macro_weight_pct for signal in signals},
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

    # Macro sources are deliberately fail-soft: the FX report must still update if
    # BIS or IMF has a temporary outage. Missing macro components automatically lose
    # their weight for that run.
    policy_series_map, policy_status = fetch_bis_policy_series(years=6)
    try:
        macro_snapshot, imf_status = fetch_imf_macro_snapshot()
    except Exception as exc:
        print(f"IMF macro layer unavailable: {exc}")
        macro_snapshot = {code: {} for code in IMF_COUNTRY_CODES}
        imf_status = {"growth": "Unavailable", "inflation": "Unavailable"}

    signals = [
        analyse_currency(
            code,
            series_map[code],
            validation_rates,
            policy_series_map,
            macro_snapshot,
        )
        for code in CURRENCY_CONFIG
    ]
    signals.sort(key=lambda item: item.score, reverse=True)

    latest_market_date = max(signal.data_date for signal in signals)
    available_policy = sum(1 for value in policy_status.values() if value == "Available")
    policy_source = (
        f"BIS central bank policy rates ({available_policy}/{len(POLICY_AREA_CODES)} available)"
        if available_policy
        else "BIS policy data unavailable for this run"
    )
    macro_source = "IMF World Economic Outlook via DataMapper"
    if all(value == "Unavailable" for value in imf_status.values()):
        macro_source = "IMF WEO unavailable for this run"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_market_date": latest_market_date,
        "base_currency": "SGD",
        "model_version": MODEL_VERSION,
        "phase": "Phase 2C — forward policy bias, forward FX momentum and decision confidence",
        "primary_source": source_name,
        "policy_source": policy_source,
        "macro_source": macro_source,
        "macro_source_status": imf_status,
        "validation_source": "Yahoo Finance market snapshot (validation only)" if validation_rates else "Unavailable",
        "model_weights": {
            "combined_when_full_coverage": {"market": 1.0 - MAX_MACRO_WEIGHT, "macro": MAX_MACRO_WEIGHT},
            "market": MARKET_WEIGHTS,
            "macro": MACRO_WEIGHTS,
            "buy_urgency": URGENCY_WEIGHTS,
            "forward_policy": FORWARD_POLICY_WEIGHTS,
            "forward_momentum": FORWARD_MOMENTUM_WEIGHTS,
            "forward_outlook": FORWARD_OUTLOOK_WEIGHTS,
        },
        "scoring_note": (
            "The Opportunity Score keeps the market/macro model. Phase 2C adds a separate Forward Outlook built from "
            "a model-implied policy bias and forward FX momentum. Buy Urgency uses those forward signals plus valuation "
            "rarity and event proximity. The policy bias is derived from BIS policy history and IMF forecast direction; "
            "it is not a market-futures probability. Urgency still cannot turn poor value into a Buy."
        ),
        "important_note": (
            "This model ranks the attractiveness of converting SGD into foreign currency. "
            "It is a decision-support tool, not a guarantee of future exchange-rate direction."
        ),
        "currencies": [asdict(signal) for signal in signals],
    }

    (DATA_DIR / "fx_signals.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_market_history(series_map)
    write_macro_snapshot(signals, policy_status, imf_status, macro_snapshot)
    write_policy_calendar_snapshot(signals)
    update_score_log(signals)

    print(f"Updated {len(signals)} currencies using {source_name}. Market date: {latest_market_date}")
    for signal in signals:
        print(
            f"{signal.code}: opportunity {signal.opportunity_score:.2f}/5 | "
            f"urgency {signal.buy_urgency_score:.2f}/5 ({signal.buy_urgency_label}) | "
            f"market {signal.market_score:.2f} | macro {signal.macro_score:.2f} — {signal.recommendation}"
        )


if __name__ == "__main__":
    main()
