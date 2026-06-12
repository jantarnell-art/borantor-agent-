"""
Warning engine: checks conditions and generates structured warnings.

All thresholds are configurable at the top of this module.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from storage import database as db

logger = logging.getLogger(__name__)

# Configurable thresholds
MARGIN_INCREASE_THRESHOLD_PP = 0.10   # warn if spread increases by more than 0.10 pp
DISCOUNT_DECREASE_THRESHOLD_PP = 0.05 # warn if my discount shrinks by more than 0.05 pp
RATE_INCREASE_ABOVE_LIST_THRESHOLD_PP = 0.05
BETTER_BANK_THRESHOLD_PP = 0.20       # warn if another bank is ≥ 0.20 pp cheaper


def _save(
    category: str,
    message: str,
    severity: str,
    bank: Optional[str] = None,
    period_key: Optional[str] = None,
):
    db.insert_warning(
        warning_date=date.today(),
        category=category,
        message=message,
        severity=severity,
        bank=bank,
        period_key=period_key,
    )
    level = logging.WARNING if severity == "WARNING" else logging.INFO
    logger.log(level, "[%s] %s", category, message)


def check_all() -> int:
    """Run all warning checks. Returns number of new warnings generated."""
    count = 0
    count += _check_rate_vs_list()
    count += _check_rate_vs_avg()
    count += _check_discount_trend()
    count += _check_margin_trend()
    count += _check_better_bank_available()
    count += _check_margin_vs_references()
    return count


# ── My rate vs list rate ──────────────────────────────────────────────────────

def _check_rate_vs_list() -> int:
    count = 0
    offers = db.get_my_offers()
    if not offers:
        return 0

    latest_list = {
        (r["bank"], r["period_key"]): r["rate"]
        for r in db.get_latest_list_rates()
    }

    for offer in offers:
        key = (offer["bank"], offer["period_key"])
        list_rate = latest_list.get(key)
        if list_rate is None:
            continue

        discount = list_rate - offer["offered_rate"]
        if discount < 0:
            _save(
                category="RATE_ABOVE_LIST",
                message=(
                    f"{offer['bank']} ({offer['period_label']}): "
                    f"din ränta {offer['offered_rate']:.2f}% är {abs(discount):.2f} pp "
                    f"HÖGRE än listräntan {list_rate:.2f}%"
                ),
                severity="WARNING",
                bank=offer["bank"],
                period_key=offer["period_key"],
            )
            count += 1

    return count


# ── My rate vs avg rate ───────────────────────────────────────────────────────

def _check_rate_vs_avg() -> int:
    count = 0
    offers = db.get_my_offers()
    if not offers:
        return 0

    with db._conn() as con:
        avg_rows = con.execute("""
            SELECT ar.bank, ar.period_key, ar.rate
            FROM avg_rates ar
            INNER JOIN (
                SELECT bank, period_key, MAX(rate_date) AS max_date
                FROM avg_rates GROUP BY bank, period_key
            ) latest
            ON ar.bank=latest.bank AND ar.period_key=latest.period_key
               AND ar.rate_date=latest.max_date
        """).fetchall()

    latest_avg = {(r["bank"], r["period_key"]): r["rate"] for r in avg_rows}

    for offer in offers:
        key = (offer["bank"], offer["period_key"])
        avg_rate = latest_avg.get(key)
        if avg_rate is None:
            continue

        diff = offer["offered_rate"] - avg_rate
        if diff > 0:
            _save(
                category="RATE_ABOVE_AVG",
                message=(
                    f"{offer['bank']} ({offer['period_label']}): "
                    f"din ränta {offer['offered_rate']:.2f}% är {diff:.2f} pp "
                    f"HÖGRE än snitträntan {avg_rate:.2f}%"
                ),
                severity="WARNING",
                bank=offer["bank"],
                period_key=offer["period_key"],
            )
            count += 1

    return count


# ── Discount trend (is my discount shrinking?) ────────────────────────────────

def _check_discount_trend() -> int:
    count = 0
    offers = db.get_my_offers()
    if not offers:
        return 0

    latest_list = {
        (r["bank"], r["period_key"]): r["rate"]
        for r in db.get_latest_list_rates()
    }

    # Group offers by (bank, period_key) and look at the last two
    from collections import defaultdict
    grouped: dict[tuple, list] = defaultdict(list)
    for o in sorted(offers, key=lambda x: x["offer_date"]):
        grouped[(o["bank"], o["period_key"])].append(o)

    for (bank, period_key), history in grouped.items():
        if len(history) < 2:
            continue
        prev, curr = history[-2], history[-1]
        list_rate = latest_list.get((bank, period_key))
        if list_rate is None:
            continue

        prev_discount = list_rate - prev["offered_rate"]
        curr_discount = list_rate - curr["offered_rate"]
        discount_change = curr_discount - prev_discount

        if discount_change < -DISCOUNT_DECREASE_THRESHOLD_PP:
            _save(
                category="DISCOUNT_SHRINKING",
                message=(
                    f"{bank} ({period_key}): din rabatt mot listräntan har "
                    f"minskat med {abs(discount_change):.2f} pp "
                    f"(från {prev_discount:.2f} pp till {curr_discount:.2f} pp)"
                ),
                severity="WARNING",
                bank=bank,
                period_key=period_key,
            )
            count += 1

    return count


# ── Bank margin trend ─────────────────────────────────────────────────────────

def _check_margin_trend() -> int:
    """
    Compare current list rates to list rates 30 days ago.
    If list rates rose more than reference rates, the bank is widening its margin.
    """
    count = 0
    with db._conn() as con:
        # Latest list rates per bank+period
        current_rows = con.execute("""
            SELECT lr.bank, lr.period_key, lr.rate
            FROM list_rates lr
            INNER JOIN (
                SELECT bank, period_key, MAX(rate_date) AS max_date
                FROM list_rates GROUP BY bank, period_key
            ) l ON lr.bank=l.bank AND lr.period_key=l.period_key AND lr.rate_date=l.max_date
        """).fetchall()

        # List rates ~30 days ago
        old_rows = con.execute("""
            SELECT lr.bank, lr.period_key, lr.rate
            FROM list_rates lr
            INNER JOIN (
                SELECT bank, period_key, MAX(rate_date) AS max_date
                FROM list_rates
                WHERE rate_date <= date('now', '-28 days')
                GROUP BY bank, period_key
            ) l ON lr.bank=l.bank AND lr.period_key=l.period_key AND lr.rate_date=l.max_date
        """).fetchall()

        # Latest reference rate change (policy rate)
        ref_rows = con.execute("""
            SELECT series_key, rate, rate_date FROM reference_rates
            WHERE series_key='policy_rate'
            ORDER BY rate_date DESC LIMIT 2
        """).fetchall()

    ref_change = 0.0
    if len(ref_rows) >= 2:
        ref_change = ref_rows[0]["rate"] - ref_rows[1]["rate"]

    old_map = {(r["bank"], r["period_key"]): r["rate"] for r in old_rows}

    for row in current_rows:
        key = (row["bank"], row["period_key"])
        old_rate = old_map.get(key)
        if old_rate is None:
            continue
        list_change = row["rate"] - old_rate
        margin_change = list_change - ref_change
        if margin_change > MARGIN_INCREASE_THRESHOLD_PP:
            _save(
                category="BANK_MARGIN_INCREASING",
                message=(
                    f"{row['bank']} ({row['period_key']}): bankens marginal har "
                    f"ökat med {margin_change:.2f} pp de senaste 30 dagarna "
                    f"(listränta +{list_change:.2f} pp, styrränta {ref_change:+.2f} pp)"
                ),
                severity="WARNING",
                bank=row["bank"],
                period_key=row["period_key"],
            )
            count += 1

    return count


# ── Better bank available ─────────────────────────────────────────────────────

def _check_better_bank_available() -> int:
    count = 0
    offers = db.get_my_offers()
    if not offers:
        return 0

    # Get the latest offer per (bank, period_key)
    from collections import defaultdict
    latest_offer: dict[tuple, dict] = {}
    for o in sorted(offers, key=lambda x: x["offer_date"]):
        latest_offer[(o["bank"], o["period_key"])] = o

    latest_list = db.get_latest_list_rates()
    list_by_period: dict[str, list[dict]] = defaultdict(list)
    for r in latest_list:
        list_by_period[r["period_key"]].append(r)

    for (my_bank, period_key), my_offer in latest_offer.items():
        competitors = list_by_period.get(period_key, [])
        for comp in competitors:
            if comp["bank"] == my_bank:
                continue
            diff = my_offer["offered_rate"] - comp["rate"]
            if diff >= BETTER_BANK_THRESHOLD_PP:
                _save(
                    category="BETTER_BANK_AVAILABLE",
                    message=(
                        f"{comp['bank']} erbjuder {period_key} till {comp['rate']:.2f}% "
                        f"– {diff:.2f} pp lägre än ditt erbjudande från {my_bank} "
                        f"({my_offer['offered_rate']:.2f}%)"
                    ),
                    severity="INFO",
                    bank=comp["bank"],
                    period_key=period_key,
                )
                count += 1

    return count


# ── Margin vs reference rates ─────────────────────────────────────────────────

def _check_margin_vs_references() -> int:
    """Warn if spread between my rate and STIBOR/styrränta is growing."""
    count = 0
    offers = db.get_my_offers()
    if not offers:
        return 0

    ref_rates = {r["series_key"]: r["rate"] for r in db.get_latest_reference_rates()}

    for ref_key, ref_label in [
        ("policy_rate", "styrräntan"),
        ("stibor_3m", "STIBOR 3M"),
    ]:
        ref = ref_rates.get(ref_key)
        if ref is None:
            continue

        for offer in offers:
            spread = offer["offered_rate"] - ref
            if spread > 2.50:  # warn when spread exceeds 2.50 pp
                _save(
                    category="HIGH_MARGIN_VS_REFERENCE",
                    message=(
                        f"{offer['bank']} ({offer['period_label']}): "
                        f"din räntemarginal mot {ref_label} är {spread:.2f} pp "
                        f"(din ränta {offer['offered_rate']:.2f}%, "
                        f"{ref_label} {ref:.2f}%)"
                    ),
                    severity="INFO",
                    bank=offer["bank"],
                    period_key=offer["period_key"],
                )
                count += 1

    return count
