"""Niche push quality filter (founder, 2026-06-10): last 8 months, not sold."""
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from push_niche_to_fub import drop_reason  # noqa: E402

TODAY = date(2026, 6, 10)


def test_recent_unsold_kept():
    assert drop_reason({"date": "2026-06-04", "saleStatus": None}, TODAY) is None


def test_old_filing_dropped():
    assert drop_reason({"date": "2024-03-01", "saleStatus": None}, TODAY) == "old"


def test_missing_date_dropped():
    assert drop_reason({"date": None}, TODAY) == "old"
    assert drop_reason({}, TODAY) == "old"


def test_boundary_eight_months():
    # 244 days before 2026-06-10 = 2025-10-09 (inclusive)
    assert drop_reason({"date": "2025-10-09"}, TODAY) is None
    assert drop_reason({"date": "2025-10-08"}, TODAY) == "old"


def test_sold_dropped_any_case():
    assert drop_reason({"date": "2026-05-01", "saleStatus": "Sold"}, TODAY) == "sold"
    assert drop_reason({"date": "2026-05-01", "saleStatus": "sold"}, TODAY) == "sold"


def test_auction_passed_without_status_dropped():
    rec = {"date": "2026-01-15", "dateOfSale": "2026-05-01", "saleStatus": None}
    assert drop_reason(rec, TODAY) == "auction-passed"


def test_future_auction_kept():
    rec = {"date": "2026-06-04", "dateOfSale": "2026-06-18", "saleStatus": None}
    assert drop_reason(rec, TODAY) is None


def test_cancelled_or_postponed_auction_kept_even_if_past():
    # cancelled/postponed means the sale did NOT happen — still a live lead
    for status in ("cancelled", "postponed"):
        rec = {"date": "2026-02-01", "dateOfSale": "2026-03-01", "saleStatus": status}
        assert drop_reason(rec, TODAY) is None


def test_datetime_strings_truncated():
    rec = {"date": "2026-06-04 11:05:12", "dateOfSale": "2026-06-18 10:00:00"}
    assert drop_reason(rec, TODAY) is None


# --- change detection / alerts ------------------------------------------------
from push_niche_to_fub import describe_changes, equity, is_high_value, sale_meta  # noqa: E402


def test_sale_meta_normalizes():
    rec = {"dateOfSale": "2026-06-18 10:00:00", "saleStatus": "Postponed"}
    assert sale_meta(rec) == {"dateOfSale": "2026-06-18", "saleStatus": "postponed"}
    assert sale_meta({}) == {"dateOfSale": "", "saleStatus": ""}


def test_describe_changes():
    old = {"dateOfSale": "2026-06-18", "saleStatus": ""}
    new = {"dateOfSale": "2026-07-30", "saleStatus": "postponed"}
    assert describe_changes(old, new) == [
        "Sale date: 2026-06-18 -> 2026-07-30",
        "Sale status: n/a -> postponed",
    ]
    assert describe_changes(new, new) == []


def test_equity_and_high_value():
    rec = {"propertyDetails": {"estimatedAvailableEquity": "152195.00"}}
    assert equity(rec) == 152195.0
    assert is_high_value(rec)  # default threshold 100k
    assert not is_high_value({"propertyDetails": {"estimatedAvailableEquity": "-5000"}})
    assert not is_high_value({})  # unknown equity never alerts
