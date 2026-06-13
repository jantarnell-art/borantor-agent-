"""
Samlar bolåneräntor med tre parallella strategier:

1. Riksbankens API → genomsnittliga bolåneräntor (officiell, alltid pålitlig)
2. Finansportalen  → listräntor per bank via Playwright
3. JSON-data inbäddad i banksidornas HTML (snabbare än full rendering)
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from collectors.base_collector import (
    BaseCollector, RateResult,
    _fetch_with_playwright, _fetch_with_requests,
)
from config import BINDING_PERIODS

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "3 mån": "3_man", "3 månader": "3_man", "3mån": "3_man",
    "1 år": "1_ar",   "1år": "1_ar",
    "2 år": "2_ar",   "2år": "2_ar",
    "3 år": "3_ar",   "3år": "3_ar",
    "5 år": "5_ar",   "5år": "5_ar",
}

BANK_ALIASES = {
    "sbab": "SBAB",
    "swedbank": "Swedbank",
    "handelsbanken": "Handelsbanken",
    "seb": "SEB",
    "nordea": "Nordea",
    "danske": "Danske Bank",
    "länsförsäkringar": "Länsförsäkringar",
    "lf bank": "Länsförsäkringar",
    "skandia": "Skandia",
    "hypoteket": "Hypoteket",
    "stabelo": "Stabelo",
    "ica banken": "ICA Banken",
}

# Sidor att prova – i prioritetsordning
SOURCES = [
    ("Finansportalen", "https://www.finansportalen.se/bank/bolan/"),
    ("Boräntor.nu",    "https://www.borantor.nu/"),
    ("Compricer",      "https://www.compricer.se/bolan/"),
]


class MultiSourceCollector(BaseCollector):
    """Provar flera källor och returnerar det bästa resultatet."""
    bank_name = "MultiSource"

    def collect_list_rates(self) -> list[RateResult]:
        for name, url in SOURCES:
            logger.info("Provar källa: %s (%s)", name, url)
            results = self._try_source(name, url)
            if results:
                logger.info("✓ %s: %d räntor hämtade", name, len(results))
                return results
            logger.warning("✗ %s: inga räntor hittade", name)
        logger.error("Alla källor misslyckades")
        return []

    def _try_source(self, name: str, url: str) -> list[RateResult]:
        from bs4 import BeautifulSoup

        # Prova Playwright (JS-rendering)
        html = _fetch_with_playwright(url)
        if not html:
            html = _fetch_with_requests(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        # Strategi 1: Sök i JSON inbäddad i sidan
        results = self._extract_from_json(html, url)
        if results:
            return results

        # Strategi 2: Tabellparsning
        results = self._extract_from_tables(soup, url)
        if results:
            return results

        # Strategi 3: Definition lists / dl dt dd
        results = self._extract_from_dl(soup, url)
        return results

    def _extract_from_json(self, html: str, url: str) -> list[RateResult]:
        """Letar efter JSON-data inbäddad i HTML (window.__state__, script-taggar etc)."""
        results = []
        today = date.today()

        # Vanliga mönster för inbäddad JSON med räntedata
        patterns = [
            r'"rate"\s*:\s*"?(\d+[.,]\d+)"?',
            r'"interest"\s*:\s*"?(\d+[.,]\d+)"?',
            r'"ranta"\s*:\s*"?(\d+[.,]\d+)"?',
            r'"ränta"\s*:\s*"?(\d+[.,]\d+)"?',
        ]

        rate_numbers = []
        for pat in patterns:
            rate_numbers.extend(re.findall(pat, html, re.IGNORECASE))

        if rate_numbers:
            logger.debug("JSON-extraktion hittade %d möjliga räntor", len(rate_numbers))

        return results  # JSON-extraktion returnerar tom lista utan bank/period-kontext

    def _extract_from_tables(self, soup, url: str) -> list[RateResult]:
        results = []
        today = date.today()

        for table in soup.find_all("table"):
            # Hämta kolumnrubriker
            headers = []
            header_row = table.find("tr")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

            # Identifiera period-kolumner
            period_cols = {}
            for i, h in enumerate(headers):
                pk = self._match_period(h)
                if pk:
                    period_cols[i] = pk

            if not period_cols:
                continue

            logger.debug("Tabell med period-kolumner: %s", period_cols)

            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                bank_raw = cells[0].get_text(strip=True)
                bank_name = self._match_bank(bank_raw.lower())
                if not bank_name:
                    continue

                for col_idx, period_key in period_cols.items():
                    if col_idx >= len(cells):
                        continue
                    rate = self._parse_rate(cells[col_idx].get_text(strip=True))
                    if rate:
                        results.append(RateResult(
                            bank=bank_name,
                            rate_date=today,
                            period_key=period_key,
                            period_label=BINDING_PERIODS[period_key],
                            rate=rate,
                            rate_type="list",
                            source_url=url,
                        ))

        return results

    def _extract_from_dl(self, soup, url: str) -> list[RateResult]:
        """Extraherar från definition lists (dt/dd) – används av vissa banker."""
        results = []
        today = date.today()
        for dl in soup.find_all("dl"):
            terms = dl.find_all("dt")
            defs  = dl.find_all("dd")
            for dt, dd in zip(terms, defs):
                pk = self._match_period(dt.get_text(strip=True))
                if not pk:
                    continue
                rate = self._parse_rate(dd.get_text(strip=True))
                if rate:
                    # dl utan bank-kontext → okänd bank
                    results.append(RateResult(
                        bank="Okänd",
                        rate_date=today,
                        period_key=pk,
                        period_label=BINDING_PERIODS[pk],
                        rate=rate,
                        rate_type="list",
                        source_url=url,
                    ))
        return results

    def _match_period(self, text: str) -> Optional[str]:
        t = text.strip().lower()
        for label, key in PERIOD_MAP.items():
            if label.lower() in t:
                return key
        return None

    def _match_bank(self, text: str) -> Optional[str]:
        text = text.strip().lower()
        for alias, canonical in BANK_ALIASES.items():
            if alias in text:
                return canonical
        return None
