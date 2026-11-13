"""ECB transport safeguards. No recommendation or scoring logic belongs here."""
import io
import time
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

CURRENCIES = ["USD", "JPY", "GBP", "AUD", "MYR", "CHF", "SGD"]
API = "https://data-api.ecb.europa.eu/service/data/EXR/D." + "+".join(CURRENCIES) + ".EUR.SP00.A"
# The ECB downloads page links the ZIP. The bare .csv endpoint returned a
# legacy 2010 sample during the review and is intentionally not used.
ARCHIVE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
MAX_ARCHIVE_BYTES = 20_000_000


def error_summary(exc):
    """Do not publish response bodies, request parameters or credentials."""
    if isinstance(exc, requests.HTTPError):
        return f"HTTP {exc.response.status_code}" if exc.response is not None else "HTTP error"
    if isinstance(exc, requests.Timeout):
        return "Request timed out"
    if isinstance(exc, requests.ConnectionError):
        return "Connection failed"
    if isinstance(exc, ValueError):
        return str(exc)[:240]
    return type(exc).__name__


def request_with_retry(get, url, params, attempts):
    for attempt in range(1, 4):
        try:
            result = get(url, params=params, timeout=45)
            attempts.append({"attempt": attempt, "status": "received"})
            return result
        except (requests.RequestException, OSError) as exc:
            attempts.append({"attempt": attempt, "status": "failed", "error": error_summary(exc)})
            code = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
            retryable = code is None or code in (408, 429, 500, 502, 503, 504)
            if attempt == 3 or not retryable:
                raise
            # Bounded backoff, including a bounded numeric Retry-After.
            delay = 2 ** attempt
            if code == 429:
                try:
                    delay = max(delay, min(30, int(exc.response.headers.get("Retry-After", 0))))
                except (TypeError, ValueError):
                    pass
            time.sleep(delay)


def parse_api(text):
    raw = pd.read_csv(io.StringIO(text))
    if not {"TIME_PERIOD", "OBS_VALUE", "CURRENCY"}.issubset(raw.columns):
        raise ValueError("ECB API response is missing required columns")
    raw["TIME_PERIOD"] = pd.to_datetime(raw["TIME_PERIOD"], errors="coerce")
    raw["OBS_VALUE"] = pd.to_numeric(raw["OBS_VALUE"], errors="coerce")
    raw = raw.dropna(subset=["TIME_PERIOD", "OBS_VALUE", "CURRENCY"])
    return raw.pivot_table(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE", aggfunc="last").sort_index()


def parse_archive(content, start):
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("ECB archive exceeds size limit")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        matches = [i for i in archive.infolist() if i.filename == "eurofxref-hist.csv"]
        if len(matches) != 1 or matches[0].file_size > MAX_ARCHIVE_BYTES:
            raise ValueError("ECB archive has no single bounded historical CSV")
        # Read in memory; never extract arbitrary archive paths.
        raw = pd.read_csv(io.BytesIO(archive.read(matches[0])), skipinitialspace=True)
    raw.columns = raw.columns.str.strip()
    if "Date" not in raw:
        raise ValueError("ECB archive CSV is missing Date")
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
    raw = raw.dropna(subset=["Date"]).set_index("Date").sort_index()
    raw = raw.loc[raw.index >= pd.Timestamp(start)]
    for code in CURRENCIES:
        if code in raw:
            raw[code] = pd.to_numeric(raw[code], errors="coerce")
    return raw


def validate_history(df, now=None):
    if df.empty:
        raise ValueError("ECB history contains no observations in the requested window")
    missing = [c for c in CURRENCIES if c not in df]
    if missing:
        raise ValueError("ECB history missing currencies: " + ", ".join(missing))
    if df.index.has_duplicates or df.index.isna().any():
        raise ValueError("ECB history contains duplicate or invalid dates")
    latest = pd.Timestamp(df.index.max()).tz_localize(None)
    today = pd.Timestamp(now or datetime.now(timezone.utc)).tz_localize(None).normalize()
    if latest > today:
        raise ValueError("ECB history contains a future observation date")
    if (today - latest.normalize()).days > 14:
        raise ValueError(f"ECB history is stale: latest observation {latest.date()}")
    bounds = {"USD": (.5, 2.5), "JPY": (50, 300), "GBP": (.4, 1.5),
              "AUD": (.8, 3), "MYR": (2, 8), "CHF": (.5, 1.8), "SGD": (.8, 3)}
    for code, (low, high) in bounds.items():
        clean = df[code].dropna()
        if len(clean) < 250:
            raise ValueError(f"ECB {code} has insufficient history: {len(clean)} observations")
        if not np.isfinite(clean).all() or (clean <= 0).any():
            raise ValueError(f"ECB {code} contains non-positive or non-finite rates")
        value = df.loc[df.index.max(), code]
        if not low <= value <= high:
            raise ValueError(f"ECB {code} latest rate is missing or implausible")


def fetch_history(years, get, diagnostics):
    diagnostics.clear()
    diagnostics.update({"checked_at_utc": datetime.now(timezone.utc).isoformat(), "sources": []})
    start = (pd.Timestamp.utcnow().normalize() - pd.DateOffset(years=years)).date().isoformat()
    for name, url, params, parser in [
        ("ECB Data Portal API", API, {"format": "csvdata", "startPeriod": start}, lambda r: parse_api(r.text)),
        ("ECB historical ZIP fallback", ARCHIVE, None, lambda r: parse_archive(r.content, start)),
    ]:
        entry = {"name": name, "url": url, "status": "checking", "attempts": []}
        diagnostics["sources"].append(entry)
        try:
            response = request_with_retry(get, url, params, entry["attempts"])
            wide = parser(response)
            validate_history(wide)
            wide.index.name = "Date"
            entry.update(status="available", latest_observation=wide.index.max().date().isoformat())
            diagnostics["selected_source"] = name
            return wide, name
        except Exception as exc:
            entry.update(status="failed", error=error_summary(exc))
            print(f"{name} unavailable: {entry['error']}")
    raise RuntimeError("Both ECB sources failed validation or retrieval; previous snapshot retained")
