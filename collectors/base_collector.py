"""Base class for all bank rate collectors."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

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
        self.rate_type = rate_type  # "list" or "avg"
        self.source_url = source_url

    def __repr__(self):
        return (
            f"RateResult({self.bank}, {self.rate_date}, "
            f"{self.period_key}, {self.rate}%, {self.rate_type})"
        )


class BaseCollector(ABC):
    bank_name: str = ""
    list_rates_url: str = ""
    avg_rates_url: Optional[str] = None

    def _fetch(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(
                    url,
                    headers=REQUEST_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                return BeautifulSoup(resp.text, "lxml")
            except requests.RequestException as exc:
                logger.warning(
                    "%s: attempt %d/%d failed – %s",
                    self.bank_name, attempt, retries, exc,
                )
                if attempt < retries:
                    time.sleep(2 ** attempt)
        logger.error("%s: all retries exhausted for %s", self.bank_name, url)
        return None

    def _parse_rate(self, text: str) -> Optional[float]:
        """
        Parse a rate string like '3,12 %', '3.12%', or '3,12' into a float.
        Returns None if parsing fails.
        """
        cleaned = (
            text.strip()
            .replace("\xa0", "")
            .replace(" ", "")
            .replace("%", "")
            .replace(",", ".")
        )
        try:
            value = float(cleaned)
            # Sanity check: Swedish mortgage rates are between 0 and 25 %
            if 0.0 < value < 25.0:
                return round(value, 4)
        except ValueError:
            pass
        return None

    @abstractmethod
    def collect_list_rates(self) -> list[RateResult]:
        """Scrape and return list rates for this bank."""

    def collect_avg_rates(self) -> list[RateResult]:
        """Scrape and return average rates. Override if bank publishes these."""
        return []

    def collect_all(self) -> list[RateResult]:
        results = []
        try:
            results.extend(self.collect_list_rates())
        except Exception as exc:
            logger.error("%s: error collecting list rates – %s", self.bank_name, exc)
        try:
            results.extend(self.collect_avg_rates())
        except Exception as exc:
            logger.error("%s: error collecting avg rates – %s", self.bank_name, exc)
        return results
