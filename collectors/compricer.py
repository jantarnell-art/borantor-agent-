"""
Dedicated collector for Compricer.se mortgage rate comparison.

Compricer shows a full comparison table of mortgage rates from multiple banks.
The page is JavaScript-rendered (React/Tailwind), so we use Playwright and try
multiple extraction strategies:
  0. JavaScript DOM extraction (reads column headers + child-row data directly)
  1. Next.js __NEXT_DATA__ embedded JSON (all rates pre-loaded server-side)
  2. Div-based comparison rows (React-rendered, lazy-loaded after scroll)
  3. Standard HTML table parsing (fallback)
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
    "rörlig": "3_man", "rörlig ränta": "3_man", "variabel": "3_man",
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

# JavaScript to extract structured rate data directly from the DOM.
# Compricer uses a Tailwind CSS div-table where:
#   - Period headers are somewhere in the container (possibly not inside child-rows)
#   - Each bank has one or more "child-row" divs with rate values
_JS_EXTRACT = r"""
() => {
    const result = { headers: [], rows: [], debug: [] };

    // ── Collect period-like leaf texts to find column headers ──────────────
    const periodPat = /^\s*(\d+\s*(mån|månader|år)|rörlig|variabel)\s*$/i;
    const headersSeen = new Set();
    document.querySelectorAll('*').forEach(el => {
        if (el.children.length > 0) return;
        const text = (el.innerText || el.textContent || '').trim();
        if (periodPat.test(text) && !headersSeen.has(text)) {
            headersSeen.add(text);
            result.headers.push(text);
        }
    });

    // ── Collect child-row elements ─────────────────────────────────────────
    const childRows = document.querySelectorAll('[class*="child-row"]');
    result.debug.push('child-rows found: ' + childRows.length);

    childRows.forEach(row => {
        const rowData = {
            bankText: (row.innerText || row.textContent || '').trim().substring(0, 150),
            leafTexts: [],
        };

        // Collect all leaf-element texts (no children = actual text nodes)
        row.querySelectorAll('*').forEach(el => {
            if (el.children.length > 0) return;
            const t = (el.innerText || el.textContent || '').trim();
            if (t && rowData.leafTexts.length < 30) rowData.leafTexts.push(t);
        });

        result.rows.push(rowData);
    });

    // ── Also try table-based extraction as fallback ────────────────────────
    result.tables = [];
    document.querySelectorAll('table').forEach(tbl => {
        const tableData = { headers: [], rows: [] };
        const rows = tbl.querySelectorAll('tr');
        rows.forEach((tr, idx) => {
            const cells = Array.from(tr.querySelectorAll('td,th')).map(
                c => (c.innerText || c.textContent || '').trim()
            );
            if (idx === 0) tableData.headers = cells;
            else tableData.rows.push(cells);
        });
        result.tables.push(tableData);
    });

    return result;
}
"""


class CompricerCollector(BaseCollector):
    """Hämtar bolåneräntor från Compricer.se med flernivå-extraktion."""

    bank_name = "Compricer"
    list_rates_url = URL

    def __init__(self):
        super().__init__()
        self._js_extracted: dict = {}

    def collect_list_rates(self) -> list[RateResult]:
        self._js_extracted = {}
        html = self._fetch_compricer()
        if not html:
            logger.error("Compricer: kunde inte hämta sidan")
            return []

        self._log_html_diagnostics(html)

        # Strategy 0: JavaScript DOM extraction (runs during Playwright fetch)
        if self._js_extracted.get("rows"):
            results = self._from_js_data()
            if results:
                logger.info("Compricer JS-extraktion: %d räntor", len(results))
                return results

        # Strategy 1: Next.js __NEXT_DATA__
        results = self._from_next_data(html)
        if results:
            logger.info("Compricer __NEXT_DATA__: %d räntor", len(results))
            return results

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        # Strategy 2: Div-based comparison rows (React / child-row)
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

    def _log_html_diagnostics(self, html: str) -> None:
        logger.info("Compricer HTML: %d chars", len(html))
        logger.info("Compricer __NEXT_DATA__: %s", "JA" if "__NEXT_DATA__" in html else "NEJ")
        tables = len(re.findall(r"<table", html, re.I))
        logger.info("Compricer <table>-element: %d", tables)
        rate_divs = re.findall(
            r'class=["\']([^"\']*(?:product|offer|rate|loan|bolan|ranta|ränta|row|card|list|child)[^"\']*)["\']',
            html, re.I
        )
        if rate_divs:
            unique = sorted(set(rate_divs))[:10]
            logger.info("Compricer relevanta div-klasser: %s", " | ".join(unique))
        if self._js_extracted:
            logger.info("Compricer JS headers: %s", self._js_extracted.get("headers", [])[:10])
            logger.info("Compricer JS child-rows: %d", len(self._js_extracted.get("rows", [])))
            for d in self._js_extracted.get("debug", []):
                logger.info("Compricer JS debug: %s", d)
        for bank in ["Handelsbanken", "Swedbank", "Nordea", "SBAB", "SEB", "Skandia"]:
            count = html.lower().count(bank.lower())
            if count:
                logger.info("Compricer: '%s' nämns %d gånger i HTML", bank, count)

    # ── Fetching ─────────────────────────────────────────────────────────────

    def _fetch_compricer(self) -> Optional[str]:
        """Fetch with Playwright; also runs JS DOM extraction for structured data."""
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

                # Extract structured data via JavaScript before getting HTML
                try:
                    self._js_extracted = page.evaluate(_JS_EXTRACT)
                except Exception as js_exc:
                    logger.debug("Compricer JS extraction failed: %s", js_exc)
                    self._js_extracted = {}

                html = page.content()
                browser.close()
                return html
        except Exception as exc:
            logger.warning("Playwright failed (%s) – falling back to requests", exc)
            self._js_extracted = {}
            return _fetch_with_requests(URL)

    # ── Strategy 0: JavaScript DOM extraction ────────────────────────────────

    def _from_js_data(self) -> list[RateResult]:
        """Parse the structured data extracted via JavaScript."""
        data = self._js_extracted
        results = []
        today = date.today()
        seen: set = set()

        # Parse period headers into ordered list
        raw_headers = data.get("headers", [])
        period_order: list[str] = []
        for h in raw_headers:
            p = self._match_period(h)
            if p and p not in period_order:
                period_order.append(p)

        logger.info("Compricer JS: raw headers=%s → period_order=%s", raw_headers[:8], period_order)

        # If we can't detect period order, try to extract per-row with inline periods
        if not period_order:
            return self._from_js_rows_inline(data, today, seen)

        for row_data in data.get("rows", []):
            bank_text = row_data.get("bankText", "")
            bank = self._match_bank(bank_text)
            if not bank:
                continue

            leaf_texts = row_data.get("leafTexts", [])

            # Extract numeric rate values from leaf texts in order
            rates: list[float] = []
            for t in leaf_texts:
                # Match "3.40%" or "3,40 %" or just "3.40"
                m = re.search(r"\b(\d+[.,]\d+)\s*%?\s*$", t.strip())
                if m:
                    try:
                        rv = float(m.group(1).replace(",", "."))
                        if 0.5 < rv < 20.0:
                            rates.append(rv)
                    except ValueError:
                        pass

            logger.debug("Compricer JS: %s → rates=%s (period_order=%s)", bank, rates[:6], period_order)

            for i, period in enumerate(period_order):
                if i < len(rates):
                    key = (bank, period)
                    if key not in seen:
                        seen.add(key)
                        results.append(RateResult(
                            bank=bank,
                            rate_date=today,
                            period_key=period,
                            period_label=BINDING_PERIODS[period],
                            rate=round(rates[i], 4),
                            rate_type="list",
                            source_url=URL,
                        ))

        # Also try the inline table data from JS
        for table_data in data.get("tables", []):
            table_results = self._from_js_table(table_data, today, seen)
            results.extend(table_results)

        return results

    def _from_js_rows_inline(self, data: dict, today, seen: set) -> list[RateResult]:
        """Fallback: each child-row contains inline period+rate pairs."""
        results = []
        for row_data in data.get("rows", []):
            bank_text = row_data.get("bankText", "")
            bank = self._match_bank(bank_text)
            if not bank:
                continue
            leaf_texts = row_data.get("leafTexts", [])
            for t in leaf_texts:
                period = self._match_period_in_text(t)
                if not period:
                    continue
                m = re.search(r"(\d+[.,]\d+)\s*%", t)
                if not m:
                    continue
                try:
                    rv = float(m.group(1).replace(",", "."))
                    if 0.5 < rv < 20.0:
                        key = (bank, period)
                        if key not in seen:
                            seen.add(key)
                            results.append(RateResult(
                                bank=bank, rate_date=today,
                                period_key=period, period_label=BINDING_PERIODS[period],
                                rate=round(rv, 4), rate_type="list", source_url=URL,
                            ))
                except ValueError:
                    pass
        return results

    def _from_js_table(self, table_data: dict, today, seen: set) -> list[RateResult]:
        """Parse a <table> extracted via JavaScript."""
        results = []
        headers = table_data.get("headers", [])
        period_cols = {i: self._match_period(h) for i, h in enumerate(headers) if self._match_period(h)}
        if not period_cols:
            return []
        for row in table_data.get("rows", []):
            if not row:
                continue
            bank = self._match_bank(row[0]) if row else None
            if not bank:
                continue
            for col_idx, period_key in period_cols.items():
                if col_idx < len(row):
                    rate = self._parse_rate(row[col_idx])
                    if rate:
                        key = (bank, period_key)
                        if key not in seen:
                            seen.add(key)
                            results.append(RateResult(
                                bank=bank, rate_date=today,
                                period_key=period_key, period_label=BINDING_PERIODS[period_key],
                                rate=rate, rate_type="list", source_url=URL,
                            ))
        return results

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
            return self._search_json(data)
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
        """Parse div/li/article elements including Compricer's child-row structure."""
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

        # Compricer-specific: child-row elements
        child_rows = soup.find_all(True, class_=re.compile(r"(?:^|\s)child-row(?:\s|$)"))
        if child_rows:
            logger.info("Compricer divs: %d child-row element", len(child_rows))
            # Try to detect period column order from surrounding context
            period_order = self._detect_period_column_order(soup)
            if period_order:
                logger.info("Compricer divs: period-ordning=%s", period_order)
                for row in child_rows:
                    text = row.get_text(" ", strip=True)
                    bank = self._match_bank(text)
                    if not bank:
                        continue
                    rates = self._extract_rate_values_in_order(row)
                    for i, period in enumerate(period_order):
                        if i < len(rates) and rates[i] is not None:
                            key = (bank, period)
                            if key not in seen:
                                seen.add(key)
                                results.append(RateResult(
                                    bank=bank, rate_date=today,
                                    period_key=period, period_label=BINDING_PERIODS[period],
                                    rate=round(rates[i], 4), rate_type="list",
                                    source_url=URL,
                                ))
                if results:
                    return results

            # Fallback: look for inline period labels within each child-row
            for row in child_rows:
                text = row.get_text(" ", strip=True)
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
                                bank=bank, rate_date=today,
                                period_key=period, period_label=BINDING_PERIODS[period],
                                rate=round(rate_val, 4), rate_type="list",
                                source_url=URL,
                            ))
                    except ValueError:
                        continue
            if results:
                return results

        # Generic div/li/article fallback
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
                            bank=bank, rate_date=today,
                            period_key=period, period_label=BINDING_PERIODS[period],
                            rate=round(rate_val, 4), rate_type="list",
                            source_url=URL,
                        ))
                except ValueError:
                    continue

        return results

    def _detect_period_column_order(self, soup) -> list[str]:
        """Try to find the header row with period column labels."""
        # Look for elements that have 2+ period labels as sibling leaf nodes
        period_labels_in_order: list[str] = []

        # Search in likely header containers
        for candidate_class in ["contents-table-container", "contents-table", "table-header", "header-row"]:
            container = soup.find(True, class_=re.compile(rf"\b{candidate_class}\b"))
            if not container:
                continue
            # Collect all leaf text blocks that look like periods
            leaf_texts = []
            for el in container.find_all(True):
                if el.find(True):
                    continue  # skip non-leaves
                text = el.get_text(strip=True)
                p = self._match_period(text)
                if p:
                    leaf_texts.append(p)
            if len(leaf_texts) >= 2:
                # Deduplicate while preserving order
                seen_p: set = set()
                for p in leaf_texts:
                    if p not in seen_p:
                        period_labels_in_order.append(p)
                        seen_p.add(p)
                break

        return period_labels_in_order

    def _extract_rate_values_in_order(self, row) -> list[Optional[float]]:
        """Extract rate values from a row element in DOM leaf order."""
        rates: list[Optional[float]] = []
        for el in row.find_all(True):
            if el.find(True):
                continue  # skip non-leaf
            text = el.get_text(strip=True)
            m = re.search(r"^(\d+[.,]\d+)\s*%?\s*$", text)
            if m:
                try:
                    rv = float(m.group(1).replace(",", "."))
                    rates.append(rv if 0.5 < rv < 20.0 else None)
                except ValueError:
                    rates.append(None)
        return rates

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
