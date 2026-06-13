"""Shared HTML parsing helpers reused by all collectors."""
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup


def parse_date(soup: BeautifulSoup) -> Optional[date]:
    for sel in ["time[datetime]", ".article-date", ".published", ".entry-date", ".post-date", ".date"]:
        el = soup.select_one(sel)
        if el:
            raw = el.get("datetime") or el.get_text(strip=True)
            try:
                return datetime.fromisoformat(raw[:10]).date()
            except Exception:
                pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", soup.get_text())
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except Exception:
            pass
    return None


def extract_text(soup: BeautifulSoup) -> str:
    for sel in ["article", ".article-content", ".entry-content", ".post-content", ".article-body", "main"]:
        el = soup.select_one(sel)
        if el:
            parts = [p.get_text(" ", strip=True) for p in el.find_all(["p", "h2", "h3", "li"])]
            text = "\n".join(t for t in parts if len(t) > 20)
            if len(text) > 100:
                return text
    parts = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    return "\n".join(t for t in parts if len(t) > 20)
