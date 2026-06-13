import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import DEAL_KEYWORDS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class ArticleResult:
    source: str
    url: str
    headline: str
    published_date: Optional[date]
    text: str
    raw_html: str = field(default="", repr=False)


class BaseCollector(ABC):
    def __init__(self, source_key: str, source_name: str, base_url: str, paths: list[str]):
        self.source_key = source_key
        self.source_name = source_name
        self.base_url = base_url
        self.paths = paths
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def _get(self, url: str) -> Optional[requests.Response]:
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt + 1} failed ({url}): {e}")
                if attempt < 2:
                    time.sleep(wait)
        return None

    @abstractmethod
    def collect_article_urls(self) -> list[str]:
        pass

    @abstractmethod
    def _parse_article(self, url: str, soup: BeautifulSoup) -> Optional[ArticleResult]:
        pass

    def fetch_article(self, url: str) -> Optional[ArticleResult]:
        resp = self._get(url)
        if not resp:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse_article(url, soup)

    def _is_deal_article(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in DEAL_KEYWORDS)

    def collect_all(self) -> list[ArticleResult]:
        results = []
        try:
            urls = self.collect_article_urls()
            logger.info(f"{self.source_name}: hittade {len(urls)} kandidatartiklar")
            for url in urls:
                article = self.fetch_article(url)
                if article and len(article.text) > 200:
                    results.append(article)
                time.sleep(1.5)
        except Exception as e:
            logger.error(f"{self.source_name}: fel vid insamling: {e}", exc_info=True)
        logger.info(f"{self.source_name}: {len(results)} artiklar hämtades")
        return results
