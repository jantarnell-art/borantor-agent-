"""Länsförsäkringar Bank rate collector."""

import logging
from datetime import date

from collectors.base_collector import BaseCollector, RateResult
from config import BINDING_PERIODS

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "3 mån": "3_man",
    "3 månader": "3_man",
    "1 år": "1_ar",
    "2 år": "2_ar",
    "3 år": "3_ar",
    "5 år": "5_ar",
}


class LansforsakringarCollector(BaseCollector):
    bank_name = "Länsförsäkringar"
    list_rates_url = (
        "https://www.lansforsakringar.se/privat/bank/bolan/bolanerantor/"
    )

    def collect_list_rates(self) -> list[RateResult]:
        soup = self._fetch(self.list_rates_url)
        if not soup:
            return []

        results = []
        today = date.today()

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

        if results:
            logger.info("Länsförsäkringar: collected %d list rates", len(results))
        else:
            logger.warning("Länsförsäkringar: no rates parsed")

        return results

    def _match_period(self, text: str) -> str | None:
        text = text.strip()
        return PERIOD_MAP.get(text) or next(
            (k for label, k in PERIOD_MAP.items() if label in text), None
        )
