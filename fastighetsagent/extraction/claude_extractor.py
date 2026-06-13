import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import anthropic

from collectors.base_collector import ArticleResult

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
Du är en expert på svenska fastighetsaffärer. Analysera följande artikeltext och extrahera information om varje fastighetsaffär (köp/försäljning) som beskrivs.

Returnera ett JSON-objekt med denna exakta struktur:
{{
  "affarer": [
    {{
      "kopare": "köparens namn/bolag (string eller null)",
      "saljare": "säljarens namn/bolag (string eller null)",
      "fastighetstyp": "en av: Kontor, Handel, Logistik, Bostäder, Hotell, Industri, Samhällsfastighet, Blandat, Mark, Övrigt (string eller null)",
      "adress": "fastighetens gatuadress (string eller null)",
      "ort": "stad eller ort (string eller null)",
      "region": "region t.ex. Stockholm, Göteborg, Malmö, Skåne, Västra Götaland (string eller null)",
      "kope_datum": "datum för köpet i YYYY-MM-DD (string eller null)",
      "kopeskilling_msek": "köpeskilling i miljoner SEK som number – konvertera t.ex. 500 mkr→5500, 1,2 mdr→1200 (number eller null)",
      "loa_kvm": "uthyrbar area i kvadratmeter som heltal (number eller null)",
      "boa_kvm": "bostadsarea i kvadratmeter som heltal, används för bostäder (number eller null)",
      "kr_per_kvm": "pris per kvadratmeter i SEK som heltal – räkna ut om möjligt (number eller null)",
      "da_krav_pct": "direktavkastningskrav i procent som number, t.ex. 4.5 för 4,5% (number eller null)",
      "uthyrningsgrad_pct": "uthyrningsgrad i procent som number (number eller null)",
      "beskrivning": "kort sammanfattning på svenska, max 200 tecken (string)"
    }}
  ],
  "confidence": "high om tydlig affärsinformation finns, medium om viss osäkerhet, low om mycket begränsad info"
}}

Regler:
- Om artikeln INTE handlar om en konkret fastighetsaffär: returnera {{\"affarer\": [], \"confidence\": \"high\"}}
- En artikel kan innehålla flera affärer – inkludera alla
- Räkna ut kr_per_kvm om kopeskilling_msek och loa_kvm/boa_kvm är kända: (kopeskilling_msek * 1000000) / area
- Returnera ENDAST giltig JSON, absolut ingenting annat

Artikel att analysera:
---
RUBRIK: {headline}

{text}
---"""


@dataclass
class DealResult:
    artikel_url: str
    kalla: str
    artikel_rubrik: str
    artikel_datum: Optional[date]
    kopare: Optional[str]
    saljare: Optional[str]
    fastighetstyp: Optional[str]
    adress: Optional[str]
    ort: Optional[str]
    region: Optional[str]
    kope_datum: Optional[date]
    kopeskilling_msek: Optional[float]
    loa_kvm: Optional[int]
    boa_kvm: Optional[int]
    kr_per_kvm: Optional[int]
    da_krav_pct: Optional[float]
    uthyrningsgrad_pct: Optional[float]
    beskrivning: Optional[str]
    confidence: str
    raw_text: str


class ClaudeExtractor:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY saknas – sätt den i .env eller miljövariabler")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

    def extract(self, article: ArticleResult) -> list["DealResult"]:
        prompt = EXTRACTION_PROMPT.format(
            headline=article.headline,
            text=article.text[:8000],
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rstrip("`")
            data = json.loads(raw)
        except Exception as e:
            logger.error(f"Claude-extraktion misslyckades ({article.url}): {e}")
            return []

        results = []
        confidence = data.get("confidence", "low")
        for deal in data.get("affarer", []):
            kope_datum = None
            if deal.get("kope_datum"):
                try:
                    kope_datum = datetime.strptime(deal["kope_datum"], "%Y-%m-%d").date()
                except Exception:
                    pass

            kr_kvm = _to_int(deal.get("kr_per_kvm"))
            if not kr_kvm and deal.get("kopeskilling_msek"):
                area = _to_int(deal.get("loa_kvm")) or _to_int(deal.get("boa_kvm"))
                if area and area > 0:
                    kr_kvm = int(_to_float(deal["kopeskilling_msek"]) * 1_000_000 / area)

            results.append(DealResult(
                artikel_url=article.url,
                kalla=article.source,
                artikel_rubrik=article.headline,
                artikel_datum=article.published_date,
                kopare=deal.get("kopare"),
                saljare=deal.get("saljare"),
                fastighetstyp=deal.get("fastighetstyp"),
                adress=deal.get("adress"),
                ort=deal.get("ort"),
                region=deal.get("region"),
                kope_datum=kope_datum,
                kopeskilling_msek=_to_float(deal.get("kopeskilling_msek")),
                loa_kvm=_to_int(deal.get("loa_kvm")),
                boa_kvm=_to_int(deal.get("boa_kvm")),
                kr_per_kvm=kr_kvm,
                da_krav_pct=_to_float(deal.get("da_krav_pct")),
                uthyrningsgrad_pct=_to_float(deal.get("uthyrningsgrad_pct")),
                beskrivning=deal.get("beskrivning"),
                confidence=confidence,
                raw_text=article.text[:2000],
            ))
        return results


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _to_int(v) -> Optional[int]:
    try:
        return int(float(v)) if v is not None else None
    except Exception:
        return None
