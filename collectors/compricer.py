"""
Dedicated collector for Compricer.se mortgage rate comparison.

Compricer shows a full comparison table of mortgage rates from multiple banks.
The page is JavaScript-rendered (React/Next.js), so we use Playwright and try
multiple extraction strategies:
  1. Next.js __NEXT_DATA__ embedded JSON (all rates pre-loaded server-side)
  2. Div-based comparison rows (React-rendered, lazy-loaded after scroll)
  3. Standard HTML table parsing (fallback – catches "top picks" section)
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from collectors.base_collector import (
    BaseCollector, RateResult,
    _fetch_with_requests,
)
from config import BINDING_PERIODS, REQUEST_HEADERS

logger = logging.getLogger(__name__)

URL = "https://www.compricer.se/bolan/"

PERIOD_MAP = {
    "3 mån": "3_man", "3 månader": "3_man", "3mån": "3_man",
    "rörlig": "3_man", "rörlig ränta": "3_man",
    "1 år": "1_ar", "1år": "1_ar", "12 mån": "1_ar", "12 månader": "1_ar",
    "2 år": "2_ar", "2år": "2_ar", "24 mån": "2_ar", "24 månader": "2_ar",
    "3 år": "3_ar", "3år": "3_ar", "36 mån": "3_ar", "36 månader": "3_ar",
    "5 år": "5_ar", "5år": "5_ar", "60 mån": "5_ar", "60 månader": "5_ar",
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
    "länsförs": "Länsförsäkringar",
    "skandia": "Skandia",
    "hypoteket": "Hypoteket",
    "stabelo": "Stabelo",
    "ica banken": "ICA Banken",
    "ica bank": "ICA Banken",
    "bluestep": "Bluestep",
    "aros": "Aros Kapital",
    "marginalen": "Marginalen Bank",
    "ålandsbanken": "Ålandsbanken",
    "wasa kredit": "Wasa Kredit",
}

_RATE_KEYS = {
    "rate", "interest", "interestrate", "listrate", "nominelleränta",
    "ranta", "ränta", "listränta", "nominalrate", "nominalränta",
    "effectiverate", "effectivränta", "räntenivå", "interest_rate",
    "list_rate", "interest_rate_percent", "ratevalue",
}
_BANK_KEYS = {
    "bank", "bankname", "provider", "creditor", "name",
    "institutename", "long_bank", "longbank", "institute",
    "bankprovider", "creditorname", "institution",
}
_PERIOD_KEYS = {
    "period", "binding", "bindingperiod", "duration",
    "löptid", "bindningstid", "fixedperiod", "term",
    "rateterm", "bindning", "bindningperiod", "fixedrate_period",
}


class CompricerCollector(BaseCollector):
    """Hämtar bolåneräntor från Compricer.se med flernivå-extraktion."""

    bank_name = "Compricer"
    list_rates_url = URL

    def collect_list_rates(self) -> list[RateResult]:
        html = self._fetch_compricer()
        if not html:
            logger.error("Compricer: kunde inte hämta sidan")
            return []

        # Strategy 1: Next.js __NEXT_DATA__
        results = self._from_next_data(html)
        if results:
            logger.info("Compricer __NEXT_DATA__: %d räntor", len(results))
            return results

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        # Strategy 2: Div-based comparison rows (React)
        results = self._from_divs(soup)
        if results:
            logger.info("Compricer div-tabell: %d räntor", len(results))
            return results

        # Strategy 3: Standard HTML tables (fallback)
        results = self._from_tables(soup)
        if results:
            logger.info("Compricer HTML-tabell: %d räntor", len(results))
        else:
            logger.warning("Compricer: inga räntor hittades i någon strategi")
        return results

    # ── Fetching ─────────────────────────────────────────────────────────────

    def _fetch_compricer(self) -> Optional[str]:
        """Fetch with Playwright, scrolling to trigger lazy-loaded content."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=REQUEST_HEADERS["User-Agent"],
                    locale="sv-SE",
                )
                page = ctx.new_page()
                page.goto(URL, timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except PWTimeout:
                    pass
                # Scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(1500)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                html = page.content()
                browser.close()
                logger.debug("Compricer HTML: %d chars", len(html))
                return html
        except Exception as exc:
            logger.warning("Playwright failed (%s) – falling back to requests", exc)
            return _fetch_with_requests(URL)

    # ── Strategy 1: Next.js __NEXT_DATA__ ────────────────────────────────────

    def _from_next_data(self, html: str) -> list[RateResult]:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
            html,
        )
        if not match:
            logger.debug("Compricer: ingen __NEXT_DATA__ hittad")
            return []
        try:
            data = json.loads(match.group(1))
            logger.debug("Compricer: __NEXT_DATA__ parsad (%d chars)", len(match.group(1)))
            results = self._search_json(data)
            logger.debug("Compricer: %d räntor från __NEXT_DATA__", len(results))
            return results
        except json.JSONDecodeError as exc:
            logger.debug("Compricer: __NEXT_DATA__ JSON-fel: %s", exc)
            return []

    def _search_json(self, root) -> list[RateResult]:
        """Recursively find rate objects (bank + period + rate) in JSON."""
        results = []
        seen: set = set()
        today = date.today()

        def walk(node, depth):
            if depth > 20 or not node:
                return
            if isinstance(node, list):
                for item in node:
                    walk(item, depth + 1)
            elif isinstance(node, dict):
                bank = self._bank_from_dict(node)
                period = self._period_from_dict(node)
                rate = self._rate_from_dict(node)
                if bank and rate and period:
                    key = (bank, period)
                    if key not in seen:
                        seen.add(key)
                        results.append(RateResult(
                            bank=bank,
                            rate_date=today,
                            period_key=period,
                            period_label=BINDING_PERIODS[period],
                            rate=rate,
                            rate_type="list",
                            source_url=URL,
                        ))
                else:
                    for v in node.values():
                        walk(v, depth + 1)

        walk(root, 0)
        return results

    def _bank_from_dict(self, d: dict) -> Optional[str]:
        for key, val in d.items():
            if key.lower() in _BANK_KEYS and isinstance(val, str):
                match = self._match_bank(val)
                if match:
                    return match
        return None

    def _period_from_dict(self, d: dict) -> Optional[str]:
        for key, val in d.items():
            if key.lower() in _PERIOD_KEYS and isinstance(val, (str, int)):
                match = self._match_period(str(val))
                if match:
                    return match
        return None

    def _rate_from_dict(self, d: dict) -> Optional[float]:
        for key, val in d.items():
            if key.lower() in _RATE_KEYS:
                try:
                    fval = float(str(val).replace(",", "."))
                    if 0.5 < fval < 20.0:
                        return round(fval, 4)
                except (ValueError, TypeError):
                    pass
        return None

    # ── Strategy 2: Div-based comparison rows ────────────────────────────────

    def _from_divs(self, soup) -> list[RateResult]:
        """Parse div/li/article elements that contain bank + rate + period."""
        results = []
        today = date.today()
        seen: set = set()

        row_pattern = re.compile(
            r"product[-_]?(?:row|item|card|list|entry)|"
            r"offer[-_]?(?:row|item|card)|"
            r"rate[-_]?(?:row|item|card)|"
            r"comparison[-_]?(?:row|item)|"
            r"provider[-_]?(?:row|item)|"
            r"loan[-_]?(?:row|item|card)",
            re.I,
        )

        candidates = (
            soup.find_all("div", class_=row_pattern)
            or soup.find_all("li", class_=row_pattern)
            or soup.find_all("article")
        )

        for elem in candidates:
            text = elem.get_text(" ", strip=True)
            bank = self._match_bank(text)
            if not bank:
                continue

            rate_hits = re.findall(r"(\d+[.,]\d+)\s*%", text)
            period = self._match_period_in_text(text)
            if not period or not rate_hits:
                continue

            for rate_str in rate_hits:
                try:
                    rate_val = float(rate_str.replace(",", "."))
                    if not (0.5 < rate_val < 20.0):
                        continue
                    key = (bank, period)
                    if key not in seen:
                        seen.add(key)
                        results.append(RateResult(
                            bank=bank,
                            rate_date=today,
                            period_key=period,
                            period_label=BINDING_PERIODS[period],
                            rate=round(rate_val, 4),
                            rate_type="list",
                            source_url=URL,
                        ))
                except ValueError:
                    continue

        return results

    # ── Strategy 3: HTML table ────────────────────────────────────────────────

    def _from_tables(self, soup) -> list[RateResult]:
        results = []
        today = date.today()

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
            period_cols = {i: self._match_period(h) for i, h in enumerate(headers) if self._match_period(h)}
            if not period_cols:
                continue

            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                bank = self._match_bank(cells[0].get_text(strip=True))
                if not bank:
                    continue
                for col_idx, period_key in period_cols.items():
                    if col_idx >= len(cells):
                        continue
                    rate = self._parse_rate(cells[col_idx].get_text(strip=True))
                    if rate:
                        results.append(RateResult(
                            bank=bank, rate_date=today,
                            period_key=period_key,
                            period_label=BINDING_PERIODS[period_key],
                            rate=rate, rate_type="list", source_url=URL,
                        ))
        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _match_period(self, text: str) -> Optional[str]:
        t = text.strip().lower()
        if t in PERIOD_MAP:
            return PERIOD_MAP[t]
        for label, key in PERIOD_MAP.items():
            if label.lower() in t:
                return key
        return None

    def _match_period_in_text(self, text: str) -> Optional[str]:
        for word in re.split(r"[\s,|/]+", text):
            match = self._match_period(word)
            if match:
                return match
        return None

    def _match_bank(self, text: str) -> Optional[str]:
        t = text.strip().lower()
        for alias, canonical in BANK_ALIASES.items():
            if alias in t:
                return canonical
        return None
