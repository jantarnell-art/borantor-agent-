import logging
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors._article_utils import extract_text, parse_date
from collectors.base_collector import ArticleResult, BaseCollector
from config import SOURCES

logger = logging.getLogger(__name__)
CFG = SOURCES["brandt_media"]


class BrandtMediaCollector(BaseCollector):
    def __init__(self):
        super().__init__(
            source_key="brandt_media",
            source_name=CFG["name"],
            base_url=CFG["base_url"],
            paths=CFG["paths"],
        )

    def collect_article_urls(self) -> list[str]:
        urls: set[str] = set()
        for path in self.paths:
            resp = self._get(self.base_url + path)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full = urljoin(self.base_url, href)
                if full.startswith(self.base_url) and "/" in href[1:]:
                    link_text = a.get_text(" ", strip=True)
                    if self._is_deal_article(link_text) or self._is_deal_article(href):
                        urls.add(full)
        return list(urls)[:40]

    def _parse_article(self, url: str, soup: BeautifulSoup) -> Optional[ArticleResult]:
        headline = ""
        for tag in ["h1", "h2"]:
            el = soup.find(tag)
            if el:
                headline = el.get_text(strip=True)
                break
        pub_date = parse_date(soup)
        text = extract_text(soup)
        if not text or len(text) < 100:
            return None
        return ArticleResult(
            source=self.source_name,
            url=url,
            headline=headline,
            published_date=pub_date,
            text=text,
        )
