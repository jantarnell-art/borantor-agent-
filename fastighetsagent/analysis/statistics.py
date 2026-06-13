"""Market statistics and analysis utilities."""
import statistics as _stats
from typing import Optional


def avg_da_krav(deals: list[dict]) -> Optional[float]:
    vals = [d["da_krav_pct"] for d in deals if d.get("da_krav_pct")]
    return round(_stats.mean(vals), 2) if vals else None


def avg_kr_per_kvm(deals: list[dict], typ: Optional[str] = None) -> Optional[float]:
    filtered = [d for d in deals if d.get("kr_per_kvm") and (typ is None or d.get("fastighetstyp") == typ)]
    vals = [d["kr_per_kvm"] for d in filtered]
    return round(_stats.mean(vals), 0) if vals else None


def total_volume_msek(deals: list[dict]) -> float:
    return sum(d["kopeskilling_msek"] for d in deals if d.get("kopeskilling_msek"))


def deals_by_type(deals: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for d in deals:
        typ = d.get("fastighetstyp") or "Okänd"
        result[typ] = result.get(typ, 0) + 1
    return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))


def deals_by_region(deals: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for d in deals:
        region = d.get("region") or d.get("ort") or "Okänd"
        result[region] = result.get(region, 0) + 1
    return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))
