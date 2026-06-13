"""
Collector for Swedish reference rates via Riksbanken's SWEA REST API.

Riksbanken API docs: https://api.riksbank.se/swea/v1/
Series used:
  SECBREPOEFF  – Riksbankens styrränta (effective)
  SESTIBOR3M   – STIBOR 3 månader
  SESTIBOR1W   – STIBOR 1 vecka
  SEGVB2YC     – Statsobligation 2 år
  SEGVB5YC     – Statsobligation 5 år
"""

import logging
from datetime import date, timedelta
from typing import Optional

import requests

from config import RIKSBANK_API, RIKSBANK_SERIES, REQUEST_TIMEOUT, REQUEST_HEADERS

logger = logging.getLogger(__name__)

SERIES_LABELS = {
    "policy_rate": "Riksbankens styrränta",
    "stibor_3m": "STIBOR 3 månader",
    "stibor_1w": "STIBOR 1 vecka",
    "gov_bond_2y": "Statsobligation 2 år",
    "gov_bond_5y": "Statsobligation 5 år",
    "mortgage_rate_avg": "Genomsnittlig bolåneränta",
}


def _fetch_series(series_id: str, from_date: date, to_date: date) -> Optional[list[dict]]:
    import time
    url = f"{RIKSBANK_API}/observations/{series_id}/{from_date}/{to_date}"
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                logger.warning("Series %s not found in Riksbanken API", series_id)
                return None
            if resp.status_code == 429:
                wait = 5 * attempt
                logger.warning("Riksbanken rate limit for %s, väntar %ds", series_id, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(0.3)  # artigt mellanrum mellan API-anrop
            return resp.json()
        except requests.RequestException as exc:
            logger.error("Riksbanken API error for %s: %s", series_id, exc)
            return None
        except ValueError as exc:
            logger.error("JSON decode error for %s: %s", series_id, exc)
            return None
    logger.error("Riksbanken API: max retries för %s", series_id)
    return None


def collect_latest_reference_rates() -> list[dict]:
    """
    Fetch the most recent value for each reference rate series.
    Returns a list of dicts with keys: series_key, series_label, rate_date, rate.
    """
    to_date = date.today()
    from_date = to_date - timedelta(days=14)  # buffer for weekends/holidays

    results = []
    for key, series_id in RIKSBANK_SERIES.items():
        data = _fetch_series(series_id, from_date, to_date)
        if not data:
            continue

        # API returns list of {"date": "YYYY-MM-DD", "value": "3.50"} sorted ascending
        valid = [
            obs for obs in data
            if obs.get("value") not in (None, "", ".")
        ]
        if not valid:
            logger.warning("No data returned for series %s (%s)", key, series_id)
            continue

        latest = valid[-1]
        try:
            rate_val = float(str(latest["value"]).replace(",", "."))
            rate_date = date.fromisoformat(latest["date"])
        except (KeyError, ValueError) as exc:
            logger.error("Parse error for series %s: %s", key, exc)
            continue

        results.append({
            "series_key": key,
            "series_label": SERIES_LABELS.get(key, key),
            "rate_date": rate_date,
            "rate": rate_val,
            "source": f"{RIKSBANK_API}/observations/{series_id}",
        })
        logger.info(
            "Reference rate [%s]: %.4f%% on %s", key, rate_val, rate_date
        )

    return results


def list_available_series(search: str = "") -> list[dict]:
    """
    Fetch all series available in the Riksbanken SWEA API.
    Optionally filter by a search string (case-insensitive).
    Useful for finding the correct series IDs.
    """
    url = f"{RIKSBANK_API}/series"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        all_series = resp.json()
    except requests.RequestException as exc:
        logger.error("Riksbanken API – kan inte hämta serielist: %s", exc)
        return []

    if search:
        search_lower = search.lower()
        return [
            s for s in all_series
            if search_lower in s.get("seriesid", "").lower()
            or search_lower in s.get("description", "").lower()
        ]
    return all_series


def collect_reference_rate_history(days: int = 365) -> list[dict]:
    """Fetch full history for all series. Used for backfill on first run."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days)

    results = []
    for key, series_id in RIKSBANK_SERIES.items():
        data = _fetch_series(series_id, from_date, to_date)
        if not data:
            continue
        for obs in data:
            if obs.get("value") in (None, "", "."):
                continue
            try:
                rate_val = float(str(obs["value"]).replace(",", "."))
                rate_date = date.fromisoformat(obs["date"])
            except (KeyError, ValueError):
                continue
            results.append({
                "series_key": key,
                "series_label": SERIES_LABELS.get(key, key),
                "rate_date": rate_date,
                "rate": rate_val,
                "source": f"{RIKSBANK_API}/observations/{series_id}",
            })

    logger.info("Collected %d historical reference rate observations", len(results))
    return results
