#!/usr/bin/env python3
import argparse
import logging
import sys

from config import LOG_PATH
from storage.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH),
    ],
)
logger = logging.getLogger(__name__)


def _build_collectors():
    from collectors.fastighetsnytt import FastighetsNyttCollector
    from collectors.fastighetsvarlden import FastighetsVarldenCollector
    from collectors.brandt_media import BrandtMediaCollector
    from collectors.di_fastighet import DiFastighetCollector
    return [
        FastighetsNyttCollector(),
        FastighetsVarldenCollector(),
        BrandtMediaCollector(),
        DiFastighetCollector(),
    ]


def cmd_collect(args=None):
    from extraction.claude_extractor import ClaudeExtractor
    from storage.database import article_already_processed, save_article, save_deal

    collectors = _build_collectors()
    extractor = ClaudeExtractor()
    total_articles = 0
    total_deals = 0

    for collector in collectors:
        articles = collector.collect_all()
        for article in articles:
            if article_already_processed(article.url):
                logger.info(f"Hoppar över redan processad: {article.url}")
                continue
            total_articles += 1
            deals = extractor.extract(article)
            artikel_id = save_article(
                article.url, article.source, article.headline,
                article.published_date, article.text[:2000],
            )
            for deal in deals:
                save_deal(artikel_id, deal)
                total_deals += 1
                logger.info(
                    f"  Affär: {deal.kopare or '?'} ← {deal.saljare or '?'} "
                    f"| {deal.kopeskilling_msek or '?'} MSEK | {deal.ort or '?'}"
                )

    logger.info(f"=== Insamling klar: {total_articles} nya artiklar → {total_deals} affärer ===")


def cmd_stats(args=None):
    from storage.database import get_deal_stats
    stats = get_deal_stats()
    print(f"\n{'='*50}")
    print(f"  Fastighetsaffärer – Statistik")
    print(f"{'='*50}")
    print(f"Totalt: {stats['total']} affärer i databasen\n")
    print("Per fastighetstyp:")
    for r in stats["by_type"]:
        avg = f"  snitt {r['avg_pris']:.0f} MSEK" if r["avg_pris"] else ""
        kvm = f"  {r['avg_kvm']:.0f} kr/kvm" if r["avg_kvm"] else ""
        print(f"  {r['fastighetstyp'] or 'Okänd'}: {r['n']} st{avg}{kvm}")
    print("\nPer källa:")
    for r in stats["by_source"]:
        print(f"  {r['kalla']}: {r['n']} affärer")
    print("\nToppköpare (antal förvärv):")
    for r in stats["top_buyers"]:
        total = f"  totalt {r['total_msek']:.0f} MSEK" if r["total_msek"] else ""
        print(f"  {r['kopare']}: {r['n']} förvärv{total}")


def cmd_dashboard(args=None):
    import subprocess
    subprocess.run(["streamlit", "run", "dashboard/web_app.py"], check=False)


def cmd_run(args=None):
    logger.info("=== Daglig körning startar ===")
    cmd_collect()
    cmd_stats()
    logger.info("=== Daglig körning klar ===")


def main():
    init_db()
    parser = argparse.ArgumentParser(
        description="Fastighetsagent – daglig insamling av svenska fastighetsaffärer"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("collect", help="Samla in och extrahera affärer från alla källor")
    sub.add_parser("stats", help="Visa statistik från databasen")
    sub.add_parser("dashboard", help="Starta Streamlit-dashboard (port 8501)")
    sub.add_parser("run", help="Kör hela dagliga flödet: collect + stats")

    args = parser.parse_args()
    commands = {
        "collect": cmd_collect,
        "stats": cmd_stats,
        "dashboard": cmd_dashboard,
        "run": cmd_run,
    }
    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
