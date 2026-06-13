"""Base class for all bank rate collectors.

Uses Playwright (headless Chromium) as primary fetcher so JavaScript-rendered
bank pages work correctly. Falls back to plain requests when Playwright is
not available.
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from config import REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class RateResult:
    def __init__(
        self,
        bank: str,
        rate_date: date,
        period_key: str,
        period_label: str,
        rate: float,
        rate_type: str = "list",
        source_url: Optional[str] = None,
    ):
        self.bank = bank
        self.rate_date = rate_date
        self.period_key = period_key
        self.period_label = period_label
        self.rate = rate
        self.rate_type = rate_type
        self.source_url = source_url

    def __repr__(self):
        return (
            f"RateResult({self.bank}, {self.rate_date}, "
            f"{self.period_key}, {self.rate}%, {self.rate_type})"
        )


def _fetch_with_playwright(url: str, wait_for: str = "networkidle") -> Optional[str]:
    """Render page with headless Chromium and return HTML."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=REQUEST_HEADERS["User-Agent"],
                locale="sv-SE",
            )
            page = ctx.new_page()
            page.goto(url, timeout=30000)
            try:
                page.wait_for_load_state(wait_for, timeout=20000)
            except PWTimeout:
                pass  # take whatever we have
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.warning("Playwright unavailable (%s) – falling back to requests", exc)
        return None


def _fetch_with_requests(url: str, retries: int = 3) -> Optional[str]:
    import requests
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("requests attempt %d/%d failed – %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


class BaseCollector(ABC):
    bank_name: str = ""
    list_rates_url: str = ""
    avg_rates_url: Optional[str] = None

    def _fetch(self, url: str) -> Optional["BeautifulSoup"]:
        from bs4 import BeautifulSoup
        html = _fetch_with_playwright(url)
        if html is None:
            html = _fetch_with_requests(url)
        if html is None:
            logger.error("%s: kunde inte hämta %s", self.bank_name, url)
            return None
        return BeautifulSoup(html, "lxml")

    def _parse_rate(self, text: str) -> Optional[float]:
        cleaned = (
            text.strip()
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(" ", "")
            .replace("%", "")
            .replace(",", ".")
        )
        try:
            value = float(cleaned)
            if 0.0 < value < 25.0:
                return round(value, 4)
        except ValueError:
            pass
        return None

    @abstractmethod
    def collect_list_rates(self) -> list[RateResult]:
        """Scrape and return list rates for this bank."""

    def collect_avg_rates(self) -> list[RateResult]:
        return []

    def collect_all(self) -> list[RateResult]:
        results = []
        try:
            results.extend(self.collect_list_rates())
        except Exception as exc:
            logger.error("%s: fel vid insamling av listräntor – %s", self.bank_name, exc)
        try:
            results.extend(self.collect_avg_rates())
        except Exception as exc:
            logger.error("%s: fel vid insamling av snitträntor – %s", self.bank_name, exc)
        return results
