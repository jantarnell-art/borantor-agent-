"""
Samlar bolåneräntor från Finansportalen (finansportalen.se).

Finansportalen drivs av Konsumentverket och publicerar aktuella listräntor
från alla svenska banker. Sidan är mer stabil än enskilda banksidor.

Fallback-källa om bankspecifika scrapers misslyckas.
"""

import logging
import re
from datetime import date
from typing import Optional

from collectors.base_collector import BaseCollector, RateResult, _fetch_with_playwright, _fetch_with_requests
from config import BINDING_PERIODS

logger = logging.getLogger(__name__)

# Finansportalens kategorier → våra period-nycklar
PERIOD_MAP = {
    "3 mån": "3_man",
    "3 månader": "3_man",
    "1 år": "1_ar",
    "2 år": "2_ar",
    "3 år": "3_ar",
    "5 år": "5_ar",
}

# Banker som Finansportalen listar (deras exakta stavning varierar)
BANK_ALIASES = {
    "sbab": "SBAB",
    "swedbank": "Swedbank",
    "handelsbanken": "Handelsbanken",
    "seb": "SEB",
    "nordea": "Nordea",
    "danske bank": "Danske Bank",
    "länsförsäkringar": "Länsförsäkringar",
    "skandia": "Skandia",
    "ica banken": "ICA Banken",
    "hypoteket": "Hypoteket",
    "stabelo": "Stabelo",
}

FINANSPORTALEN_URL = "https://www.finansportalen.se/bank/bolan/"


class FinansportalenCollector(BaseCollector):
    """
    Samlar räntor för alla banker från Finansportalen på en gång.
    Returnerar RateResult-objekt för varje bank+period kombination.
    """
    bank_name = "Finansportalen"
    list_rates_url = FINANSPORTALEN_URL

    def collect_list_rates(self) -> list[RateResult]:
        from bs4 import BeautifulSoup

        logger.info("Hämtar räntor från Finansportalen…")

        # Prova Playwright först (JS-rendering), sedan requests
        html = _fetch_with_playwright(FINANSPORTALEN_URL)
        if not html:
            html = _fetch_with_requests(FINANSPORTALEN_URL)
        if not html:
            logger.error("Finansportalen: kunde inte hämta sidan")
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []
        today = date.today()

        # Finansportalen använder tabeller med bank i rad, period i kolumn
        tables = soup.find_all("table")
        for table in tables:
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

            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                bank_raw = cells[0].get_text(strip=True).lower()
                bank_name = self._match_bank(bank_raw)
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
                            source_url=FINANSPORTALEN_URL,
                        ))

        if results:
            banks_found = {r.bank for r in results}
            logger.info(
                "Finansportalen: %d räntor hämtade för %d banker: %s",
                len(results), len(banks_found), ", ".join(sorted(banks_found))
            )
        else:
            logger.warning(
                "Finansportalen: inga räntor hittades – "
                "sidans struktur kan ha ändrats"
            )

        return results

    def _match_period(self, text: str) -> Optional[str]:
        text = text.strip()
        return PERIOD_MAP.get(text) or next(
            (k for label, k in PERIOD_MAP.items() if label in text), None
        )

    def _match_bank(self, text: str) -> Optional[str]:
        text = text.strip().lower()
        for alias, canonical in BANK_ALIASES.items():
            if alias in text:
                return canonical
        return None
