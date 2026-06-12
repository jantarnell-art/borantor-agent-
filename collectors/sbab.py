"""SBAB rate collector."""

import logging
import re
from datetime import date

from collectors.base_collector import BaseCollector, RateResult
from config import BINDING_PERIODS

logger = logging.getLogger(__name__)

# Maps text found on SBAB's page to our period keys
PERIOD_MAP = {
    "3 mån": "3_man",
    "3 månader": "3_man",
    "1 år": "1_ar",
    "2 år": "2_ar",
    "3 år": "3_ar",
    "5 år": "5_ar",
}


class SBABCollector(BaseCollector):
    bank_name = "SBAB"
    list_rates_url = "https://www.sbab.se/1/privat/bolan/rantor.html"

    def collect_list_rates(self) -> list[RateResult]:
        soup = self._fetch(self.list_rates_url)
        if not soup:
            return []

        results = []
        today = date.today()

        # SBAB renders rate tables with <table> or definition lists.
        # Try multiple selectors to be resilient to page redesigns.
        rates_found = self._try_table(soup, today)
        if not rates_found:
            rates_found = self._try_dl(soup, today)

        if rates_found:
            logger.info("SBAB: collected %d list rates", len(rates_found))
        else:
            logger.warning("SBAB: could not parse any rates – page structure may have changed")

        return rates_found

    def _try_table(self, soup, today: date) -> list[RateResult]:
        results = []
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True)
                period_key = self._match_period(label)
                if not period_key:
                    continue
                rate = self._parse_rate(cells[1].get_text(strip=True))
                if rate:
                    results.append(RateResult(
                        bank=self.bank_name,
                        rate_date=today,
                        period_key=period_key,
                        period_label=BINDING_PERIODS[period_key],
                        rate=rate,
                        rate_type="list",
                        source_url=self.list_rates_url,
                    ))
        return results

    def _try_dl(self, soup, today: date) -> list[RateResult]:
        results = []
        for dl in soup.find_all("dl"):
            terms = dl.find_all("dt")
            definitions = dl.find_all("dd")
            for dt, dd in zip(terms, definitions):
                period_key = self._match_period(dt.get_text(strip=True))
                if not period_key:
                    continue
                rate = self._parse_rate(dd.get_text(strip=True))
                if rate:
                    results.append(RateResult(
                        bank=self.bank_name,
                        rate_date=today,
                        period_key=period_key,
                        period_label=BINDING_PERIODS[period_key],
                        rate=rate,
                        rate_type="list",
                        source_url=self.list_rates_url,
                    ))
        return results

    def _match_period(self, text: str) -> str | None:
        text = text.strip()
        return PERIOD_MAP.get(text) or next(
            (k for label, k in PERIOD_MAP.items() if label in text), None
        )
