#!/usr/bin/env python3
"""
Boränteagent Sverige – huvudskript

Användning:
  python main.py collect          # samla in räntor nu
  python main.py backfill         # hämta historiska referensräntor (1 år)
  python main.py dashboard        # visa terminal-dashboard
  python main.py export           # exportera Excel-rapport
  python main.py warnings         # kör varningskontroller
  python main.py add-offer        # lägg till eget erbjudande (interaktivt)
  python main.py run              # kör allt (collect + warnings + export + dashboard)
"""

import argparse
import logging
import sys
from datetime import date

from config import BINDING_PERIODS, LOG_PATH, BANKS
from storage.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("borantor")


# ── Collectors registry ───────────────────────────────────────────────────────

def _build_collectors():
    from collectors.finansportalen import FinansportalenCollector
    from collectors.sbab import SBABCollector
    from collectors.swedbank import SwedbankCollector
    from collectors.handelsbanken import HandelsbankenCollector
    from collectors.seb import SEBCollector
    from collectors.nordea import NordeaCollector
    from collectors.danske_bank import DanskeBankCollector
    from collectors.lansforsakringar import LansforsakringarCollector
    from collectors.skandia import SkandiaCollector

    return [
        # Finansportalen hämtar alla banker på en gång (Playwright-baserad)
        FinansportalenCollector(),
        # Bankspecifika som komplement/fallback
        SBABCollector(),
        SwedbankCollector(),
        HandelsbankenCollector(),
        SEBCollector(),
        NordeaCollector(),
        DanskeBankCollector(),
        LansforsakringarCollector(),
        SkandiaCollector(),
    ]


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_collect() -> None:
    """Collect bank list rates and reference rates, save to database."""
    from storage.database import upsert_list_rate, upsert_avg_rate, upsert_reference_rate
    from collectors.reference_rates import collect_latest_reference_rates

    collectors = _build_collectors()
    total_saved = 0

    for collector in collectors:
        results = collector.collect_all()
        for r in results:
            if r.rate_type == "list":
                upsert_list_rate(
                    rate_date=r.rate_date,
                    bank=r.bank,
                    period_key=r.period_key,
                    period_label=r.period_label,
                    rate=r.rate,
                    source_url=r.source_url,
                )
            else:
                upsert_avg_rate(
                    rate_date=r.rate_date,
                    bank=r.bank,
                    period_key=r.period_key,
                    period_label=r.period_label,
                    rate=r.rate,
                    source_url=r.source_url,
                )
            total_saved += 1

    # Reference rates
    ref_results = collect_latest_reference_rates()
    for r in ref_results:
        upsert_reference_rate(
            rate_date=r["rate_date"],
            series_key=r["series_key"],
            series_label=r["series_label"],
            rate=r["rate"],
            source=r.get("source"),
        )

    logger.info(
        "Insamling klar: %d bankräntor sparade, %d referensräntor sparade",
        total_saved, len(ref_results),
    )


def cmd_backfill() -> None:
    """Fetch 1 year of historical reference rates from Riksbanken."""
    from storage.database import upsert_reference_rate
    from collectors.reference_rates import collect_reference_rate_history

    logger.info("Hämtar historiska referensräntor (365 dagar)…")
    results = collect_reference_rate_history(days=365)
    for r in results:
        upsert_reference_rate(
            rate_date=r["rate_date"],
            series_key=r["series_key"],
            series_label=r["series_label"],
            rate=r["rate"],
            source=r.get("source"),
        )
    logger.info("Backfill klar: %d observationer sparade", len(results))


def cmd_dashboard() -> None:
    from dashboard.report import show_dashboard
    show_dashboard()


def cmd_export() -> None:
    from storage.excel_exporter import export_all
    from config import EXCEL_PATH
    export_all()
    print(f"\nExcel-rapport sparad: {EXCEL_PATH}")


def cmd_warnings() -> None:
    from analysis.warnings import check_all
    count = check_all()
    logger.info("Varningskontroll klar: %d nya varningar genererade", count)


def cmd_add_offer() -> None:
    """Interactive wizard to register a personal mortgage offer."""
    from storage.database import insert_my_offer, get_latest_list_rates, upsert_list_rate

    print("\n=== Registrera eget ränteerbjudande ===\n")

    # Bank
    bank_names = list(BANKS.keys())
    for i, b in enumerate(bank_names, 1):
        print(f"  {i}. {b}")
    while True:
        try:
            choice = int(input("\nVälj bank (nummer): "))
            bank = bank_names[choice - 1]
            break
        except (ValueError, IndexError):
            print("Ogiltigt val, försök igen.")

    # Period
    period_keys = list(BINDING_PERIODS.keys())
    print()
    for i, (k, v) in enumerate(BINDING_PERIODS.items(), 1):
        print(f"  {i}. {v}")
    while True:
        try:
            choice = int(input("\nVälj bindningstid (nummer): "))
            period_key = period_keys[choice - 1]
            period_label = BINDING_PERIODS[period_key]
            break
        except (ValueError, IndexError):
            print("Ogiltigt val, försök igen.")

    # Offered rate
    while True:
        try:
            offered_rate = float(input("\nErbjuden ränta (ex: 3.25): ").replace(",", "."))
            if 0 < offered_rate < 25:
                break
            print("Räntan måste vara mellan 0 och 25.")
        except ValueError:
            print("Ange ett tal, ex: 3.25")

    # Loan amount (optional)
    loan_str = input("\nLånebelopp i kr (tryck Enter om du vill hoppa över): ").strip()
    loan_amount = None
    if loan_str:
        try:
            loan_amount = int(loan_str.replace(" ", "").replace(",", ""))
        except ValueError:
            print("Ogiltigt belopp, hoppar över.")

    # Comment
    comment = input("\nKommentar (valfritt): ").strip() or None

    # Source
    source = input("Källa (valfritt, ex: 'Telefonsamtal med rådgivare'): ").strip() or None

    # Offer date
    date_str = input(f"\nDatum (YYYY-MM-DD, tryck Enter för idag {date.today()}): ").strip()
    if date_str:
        try:
            offer_date = date.fromisoformat(date_str)
        except ValueError:
            print("Ogiltigt datum, använder idag.")
            offer_date = date.today()
    else:
        offer_date = date.today()

    # Calculate discount vs list
    latest = {(r["bank"], r["period_key"]): r["rate"] for r in get_latest_list_rates()}
    list_rate = latest.get((bank, period_key))
    discount = None
    if list_rate:
        discount = round(list_rate - offered_rate, 4)
        print(f"\nListränta för {bank} {period_label}: {list_rate:.2f}%")
        print(f"Din rabatt mot listräntan: {discount:+.2f} pp")

    row_id = insert_my_offer(
        offer_date=offer_date,
        bank=bank,
        period_key=period_key,
        period_label=period_label,
        offered_rate=offered_rate,
        loan_amount=loan_amount,
        discount_vs_list=discount,
        comment=comment,
        source=source,
    )
    print(f"\nErbjudande sparat (id={row_id}).")

    # Monthly cost summary
    if loan_amount:
        from analysis.calculator import monthly_cost, annual_cost
        mc = monthly_cost(loan_amount, offered_rate)
        ac = annual_cost(loan_amount, offered_rate)
        print(f"Räntekostnad: {mc:,.0f} kr/månad  |  {ac:,.0f} kr/år")


def cmd_run() -> None:
    """Full daily run: collect → warnings → export → dashboard."""
    logger.info("=== Daglig körning startar ===")
    cmd_collect()
    cmd_warnings()
    cmd_export()
    cmd_dashboard()
    logger.info("=== Daglig körning klar ===")


def cmd_list_series() -> None:
    """List available series in Riksbanken's API (for finding correct series IDs)."""
    from collectors.reference_rates import list_available_series
    import sys

    search = sys.argv[2] if len(sys.argv) > 2 else ""
    series = list_available_series(search)
    if not series:
        print("Inga serier hittades (eller kunde inte ansluta till Riksbankens API).")
        return
    print(f"\n{'Serie-ID':<20} {'Beskrivning'}")
    print("-" * 80)
    for s in series[:100]:
        sid = s.get("seriesid", s.get("seriesId", ""))
        desc = s.get("description", s.get("name", ""))
        print(f"{sid:<20} {desc}")
    if len(series) > 100:
        print(f"\n... och {len(series) - 100} till. Sök med: python main.py list-series <sökord>")


# ── CLI entry point ───────────────────────────────────────────────────────────

COMMANDS = {
    "collect": cmd_collect,
    "backfill": cmd_backfill,
    "dashboard": cmd_dashboard,
    "export": cmd_export,
    "warnings": cmd_warnings,
    "add-offer": cmd_add_offer,
    "run": cmd_run,
    "list-series": cmd_list_series,
}


def main():
    init_db()

    parser = argparse.ArgumentParser(
        description="Boränteagent Sverige – samla, analysera och bevaka svenska bolåneräntor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k:<12} {v.__doc__}" for k, v in COMMANDS.items()),
    )
    parser.add_argument(
        "command",
        choices=list(COMMANDS.keys()),
        help="Kommando att köra",
    )
    args = parser.parse_args()
    COMMANDS[args.command]()


if __name__ == "__main__":
    main()
