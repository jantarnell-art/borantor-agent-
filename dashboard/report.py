"""
Terminal dashboard using the Rich library.

Shows market overview, reference rates, my loan situation and active warnings.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule

from analysis.calculator import (
    market_summary,
    monthly_cost,
    annual_cost,
    discount_vs_list,
    spread_vs_reference,
    weekly_change,
    monthly_change,
)
from config import BINDING_PERIODS
from storage import database as db

console = Console()


def _trend_arrow(value: Optional[float]) -> str:
    if value is None:
        return ""
    if value > 0:
        return f"[red]▲ +{value:.2f}[/red]"
    if value < 0:
        return f"[green]▼ {value:.2f}[/green]"
    return "[dim]━ 0.00[/dim]"


def _rate_color(rate: float) -> str:
    if rate < 3.0:
        return "green"
    if rate < 4.0:
        return "yellow"
    return "red"


def show_dashboard() -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold white]Boränteagent Sverige[/bold white]  "
            f"[dim]{date.today().strftime('%A %d %B %Y')}[/dim]",
            border_style="blue",
        )
    )

    _show_reference_rates()
    _show_market_overview()
    _show_my_loan_situation()
    _show_warnings()


# ── Reference rates ───────────────────────────────────────────────────────────

def _show_reference_rates() -> None:
    console.print(Rule("[bold]Referensräntor[/bold]"))
    rows = db.get_latest_reference_rates()
    if not rows:
        console.print("[dim]Inga referensräntor insamlade ännu.[/dim]")
        return

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold blue")
    tbl.add_column("Ränta", style="bold")
    tbl.add_column("Värde", justify="right")
    tbl.add_column("Datum", justify="center", style="dim")

    for r in rows:
        tbl.add_row(
            r["series_label"],
            f"[{_rate_color(r['rate'])}]{r['rate']:.2f}%[/{_rate_color(r['rate'])}]",
            str(r["rate_date"]),
        )
    console.print(tbl)


# ── Market overview ───────────────────────────────────────────────────────────

def _show_market_overview() -> None:
    console.print(Rule("[bold]Marknadsöversikt – listräntor[/bold]"))
    latest = db.get_latest_list_rates()
    if not latest:
        console.print("[dim]Inga listräntor insamlade ännu.[/dim]")
        return

    summary = market_summary(latest)

    # Summary table (min/max/avg per period)
    tbl_sum = Table(
        title="Marknadssammanfattning", box=box.SIMPLE_HEAVY,
        show_header=True, header_style="bold blue",
    )
    tbl_sum.add_column("Bindningstid")
    tbl_sum.add_column("Lägst", justify="right")
    tbl_sum.add_column("Högst", justify="right")
    tbl_sum.add_column("Snitt", justify="right")
    tbl_sum.add_column("Antal", justify="right")

    for period_key, label in BINDING_PERIODS.items():
        s = summary.get(period_key)
        if not s:
            continue
        tbl_sum.add_row(
            label,
            f"[green]{s['min']:.2f}%[/green]",
            f"[red]{s['max']:.2f}%[/red]",
            f"{s['avg']:.2f}%",
            str(s["count"]),
        )
    console.print(tbl_sum)

    # Per-bank rate table
    banks = sorted({r["bank"] for r in latest})
    tbl_bank = Table(
        title="Listräntor per bank", box=box.SIMPLE_HEAVY,
        show_header=True, header_style="bold blue",
    )
    tbl_bank.add_column("Bank", style="bold")
    for label in BINDING_PERIODS.values():
        tbl_bank.add_column(label, justify="right")

    for bank in banks:
        bank_rates = {r["period_key"]: r["rate"] for r in latest if r["bank"] == bank}
        cells = []
        for period_key in BINDING_PERIODS:
            rate = bank_rates.get(period_key)
            if rate is None:
                cells.append("[dim]–[/dim]")
            else:
                cells.append(f"[{_rate_color(rate)}]{rate:.2f}%[/{_rate_color(rate)}]")
        tbl_bank.add_row(bank, *cells)

    console.print(tbl_bank)


# ── My loan situation ─────────────────────────────────────────────────────────

def _show_my_loan_situation() -> None:
    console.print(Rule("[bold]Min lånesituation[/bold]"))
    offers = db.get_my_offers()
    if not offers:
        console.print(
            "[dim]Inga egna erbjudanden registrerade ännu. "
            "Använd [bold]python main.py add-offer[/bold] för att lägga till.[/dim]"
        )
        return

    latest_list = {(r["bank"], r["period_key"]): r["rate"] for r in db.get_latest_list_rates()}
    ref_rates = {r["series_key"]: r["rate"] for r in db.get_latest_reference_rates()}

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold blue")
    tbl.add_column("Datum", style="dim")
    tbl.add_column("Bank", style="bold")
    tbl.add_column("Bindningstid")
    tbl.add_column("Min ränta", justify="right")
    tbl.add_column("Listränta", justify="right")
    tbl.add_column("Rabatt (pp)", justify="right")
    tbl.add_column("vs Styrränta", justify="right")
    tbl.add_column("vs STIBOR 3M", justify="right")
    tbl.add_column("Månads-\nkostnad", justify="right")

    for o in sorted(offers, key=lambda x: x["offer_date"], reverse=True):
        key = (o["bank"], o["period_key"])
        list_rate = latest_list.get(key)
        disc_str = ""
        if list_rate:
            disc = discount_vs_list(o["offered_rate"], list_rate)
            color = "green" if disc > 0 else "red"
            disc_str = f"[{color}]{disc:+.2f}[/{color}]"

        policy = ref_rates.get("policy_rate")
        stibor = ref_rates.get("stibor_3m")
        policy_str = (
            f"{spread_vs_reference(o['offered_rate'], policy):+.2f}" if policy else "–"
        )
        stibor_str = (
            f"{spread_vs_reference(o['offered_rate'], stibor):+.2f}" if stibor else "–"
        )

        loan = o["loan_amount"]
        mc_str = (
            f"{monthly_cost(loan, o['offered_rate']):,.0f} kr"
            if loan else "–"
        )

        tbl.add_row(
            str(o["offer_date"]),
            o["bank"],
            o["period_label"],
            f"[bold]{o['offered_rate']:.2f}%[/bold]",
            f"{list_rate:.2f}%" if list_rate else "–",
            disc_str,
            policy_str,
            stibor_str,
            mc_str,
        )

    console.print(tbl)

    # Savings potential
    if offers and latest_list:
        _show_savings_potential(offers, latest_list)


def _show_savings_potential(offers, latest_list) -> None:
    from analysis.calculator import savings_vs_alternative

    console.print()
    console.print("[bold]Besparingspotential[/bold]")

    for o in sorted(offers, key=lambda x: x["offer_date"], reverse=True)[:3]:
        if not o["loan_amount"]:
            continue
        alternatives = [
            (bank_period, rate)
            for bank_period, rate in latest_list.items()
            if bank_period[1] == o["period_key"] and bank_period[0] != o["bank"]
        ]
        if not alternatives:
            continue
        best_bank, best_rate = min(alternatives, key=lambda x: x[1])
        if best_rate < o["offered_rate"]:
            sav = savings_vs_alternative(o["offered_rate"], best_rate, o["loan_amount"])
            console.print(
                f"  {o['bank']} → {best_bank[0]}: "
                f"[green]{sav['annual_savings_sek']:,.0f} kr/år[/green] "
                f"([green]{sav['monthly_savings_sek']:,.0f} kr/mån[/green]) "
                f"vid byte ({sav['rate_diff_pp']:.2f} pp)"
            )


# ── Warnings ──────────────────────────────────────────────────────────────────

def _show_warnings() -> None:
    console.print(Rule("[bold]Aktiva varningar[/bold]"))
    warnings = db.get_warnings(acknowledged=False, limit=20)
    if not warnings:
        console.print("[green]Inga aktiva varningar.[/green]")
        return

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    tbl.add_column("Datum", style="dim")
    tbl.add_column("Typ")
    tbl.add_column("Bank")
    tbl.add_column("Meddelande")

    for w in warnings:
        sev_color = "red" if w["severity"] == "WARNING" else "yellow"
        tbl.add_row(
            str(w["warning_date"]),
            f"[{sev_color}]{w['category']}[/{sev_color}]",
            w["bank"] or "–",
            w["message"],
        )
    console.print(tbl)
