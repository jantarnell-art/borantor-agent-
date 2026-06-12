"""
Financial calculations for the mortgage rate agent.

All monetary amounts are in SEK. Rates are in percent (e.g. 3.5 means 3.5 %).
"""

from __future__ import annotations

from typing import Optional


def discount_vs_list(offered_rate: float, list_rate: float) -> float:
    """Positive value = offered is lower than list (a discount). In percentage points."""
    return round(list_rate - offered_rate, 4)


def spread_vs_reference(my_rate: float, reference_rate: float) -> float:
    """My rate minus the reference rate. Positive = I pay more than the reference."""
    return round(my_rate - reference_rate, 4)


def monthly_cost(loan_amount: int, annual_rate_pct: float) -> float:
    """Simple interest monthly cost (not amortization)."""
    return round(loan_amount * (annual_rate_pct / 100) / 12, 2)


def annual_cost(loan_amount: int, annual_rate_pct: float) -> float:
    return round(loan_amount * (annual_rate_pct / 100), 2)


def rate_change(current: float, previous: float) -> float:
    """Change in percentage points."""
    return round(current - previous, 4)


def savings_vs_alternative(
    my_rate: float,
    alternative_rate: float,
    loan_amount: int,
) -> dict:
    """
    Calculate annual and monthly savings if switching to an alternative rate.
    Positive savings = alternative is cheaper.
    """
    diff = my_rate - alternative_rate  # positive = my rate is higher
    annual = annual_cost(loan_amount, diff)
    return {
        "rate_diff_pp": round(diff, 4),
        "annual_savings_sek": round(annual, 2),
        "monthly_savings_sek": round(annual / 12, 2),
    }


def margin_analysis(
    my_rate: float,
    reference_rates: dict[str, float],
    loan_amount: Optional[int] = None,
) -> dict:
    """
    Returns a dict of spread between my_rate and each reference rate.
    reference_rates: {"policy_rate": 2.5, "stibor_3m": 2.65, ...}
    """
    analysis = {}
    for key, ref_rate in reference_rates.items():
        spread = spread_vs_reference(my_rate, ref_rate)
        entry = {
            "reference_rate": ref_rate,
            "spread_pp": spread,
        }
        if loan_amount:
            entry["annual_cost_sek"] = annual_cost(loan_amount, spread)
        analysis[key] = entry
    return analysis


def market_summary(list_rates: list[dict]) -> dict:
    """
    Summarise the market from a list of list_rate dicts.
    Each dict must have 'bank', 'period_key', 'rate'.
    Returns per-period: min, max, avg across banks.
    """
    from collections import defaultdict

    by_period: dict[str, list[float]] = defaultdict(list)
    for r in list_rates:
        by_period[r["period_key"]].append(r["rate"])

    summary = {}
    for period, rates in by_period.items():
        summary[period] = {
            "min": round(min(rates), 4),
            "max": round(max(rates), 4),
            "avg": round(sum(rates) / len(rates), 4),
            "count": len(rates),
        }
    return summary


def weekly_change(history: list[dict]) -> Optional[float]:
    """
    Given a list of {"rate_date": date, "rate": float} sorted ascending,
    returns the change over the last 7 days (or None if insufficient data).
    """
    if len(history) < 2:
        return None
    from datetime import timedelta
    latest = history[-1]
    cutoff = latest["rate_date"] - timedelta(days=7)
    older = [h for h in history if h["rate_date"] <= cutoff]
    if not older:
        return None
    return round(latest["rate"] - older[-1]["rate"], 4)


def monthly_change(history: list[dict]) -> Optional[float]:
    if len(history) < 2:
        return None
    from datetime import timedelta
    latest = history[-1]
    cutoff = latest["rate_date"] - timedelta(days=30)
    older = [h for h in history if h["rate_date"] <= cutoff]
    if not older:
        return None
    return round(latest["rate"] - older[-1]["rate"], 4)
