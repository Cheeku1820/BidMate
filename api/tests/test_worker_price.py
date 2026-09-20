"""The price job, with both sources faked in-process (estimate-first-
pricing §3, §10 'Worker, sources stubbed')."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.jobs import queue
from app.takeoff.models import Item, ItemMarketPrice, MarketLookup, ReviewStatus
from app.worker import market_sources, price_job
from app.worker.market_sources import SourceError, SourceResult
from tests.test_worker_read import _run_all, inline  # noqa: F401


class FakeSource:
    def __init__(self, name, answer=None, loc="78701"):
        self.name, self.calls, self._answer, self._loc = name, [], answer, loc

    def location_key(self, project):
        return self._loc

    def lookup(self, query, unit, loc):
        self.calls.append(query)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _priced(p="12.40", low=None, high=None, labor="22.50"):
    return SourceResult("priced", Decimal(p), Decimal(low or p), Decimal(high or p), Decimal(labor), "EA",
                        "Travis County, TX", {"matched": {"name": "x"}})


def _wire(monkeypatch, db, sources, cap=2000):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    monkeypatch.setattr(market_sources, "get_sources", lambda: sources)
    monkeypatch.setattr(price_job, "get_sources", lambda: sources)
    monkeypatch.setattr("app.config.settings.market_lookup_monthly_cap", cap)


def _item(db, project, sheet, name, description="", unit="EA"):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name, description=description,
             system="Power", category="Devices", quantity=2, unit=unit, status=ReviewStatus.READY, x=1, y=1)
    db.add(i); db.flush()
    return i


def test_prices_by_name_through_onebuild_and_writes_the_row(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert mp.outcome == "priced" and mp.unit_price == Decimal("12.40") and mp.labor_rate_per_unit == Decimal("22.50")
    assert mp.source == "onebuild" and mp.location_label == "Travis County, TX" and mp.query == "20A duplex receptacle"
    assert db.get(MarketLookup, mp.lookup_id).billed is True and src.calls == ["20A duplex receptacle"]


def test_model_numbers_go_to_shopping(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    shop = FakeSource("shopping", SourceResult("priced", Decimal("169.95"), Decimal("156.75"), Decimal("303.33"), None, "EA", "Austin, TX", {"sellers": []}))
    _wire(monkeypatch, db, {"onebuild": FakeSource("onebuild", _priced()), "shopping": shop})
    i = _item(db, project, sheet, "Luminaire", "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert mp.source == "shopping" and shop.calls == ["Current CVT8-LSCS-MV"]
    assert (mp.price_low, mp.unit_price, mp.price_high) == (Decimal("156.75"), Decimal("169.95"), Decimal("303.33"))


def test_quote_required_spends_nothing(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "Switch Board MSBS")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "quote_required" and src.calls == []


def test_cache_hit_within_30_days_calls_nothing_and_is_not_billed(db, project, sheet, dana, org, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    db.add(MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701", status="priced",
                        result={"matched": {"name": "x", "uom": "EA", "materialRateUsdCents": 999, "laborRateUsdCents": 100}},
                        fetched_at=datetime.now(timezone.utc) - timedelta(days=10), billed=True, org_id=org.id))
    db.flush()
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert src.calls == [] and mp.unit_price == Decimal("9.99")
    assert db.scalar(select(func.count()).select_from(MarketLookup)) == 1


def test_stale_cache_is_refetched(db, project, sheet, dana, org, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    db.add(MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701", status="priced",
                        result={}, fetched_at=datetime.now(timezone.utc) - timedelta(days=31), billed=True, org_id=org.id))
    db.flush()
    _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert src.calls == ["20A duplex receptacle"]


def test_cap_marks_the_rest_over_budget_and_the_job_completes(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src}, cap=2)
    items = [_item(db, project, sheet, f"Item {n}") for n in range(4)]
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    outcomes = sorted(db.get(ItemMarketPrice, i.id).outcome for i in items)
    assert outcomes == ["over_budget", "over_budget", "priced", "priced"] and job.status == "done"


def test_no_key_marks_unavailable(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    _wire(monkeypatch, db, {})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "unavailable"


def test_no_zip_marks_location_needed(db, project, sheet, dana, monkeypatch):
    project.postal_code = None
    src = FakeSource("onebuild", _priced(), loc=None)
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "location_needed" and src.calls == []


def test_source_error_marks_failed_and_continues(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    _wire(monkeypatch, db, {"onebuild": FakeSource("onebuild", SourceError("timeout"))})
    a = _item(db, project, sheet, "A"); b = _item(db, project, sheet, "B")
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "done"
    assert {db.get(ItemMarketPrice, a.id).outcome, db.get(ItemMarketPrice, b.id).outcome} == {"failed"}


def test_rerun_prices_only_items_without_a_fresh_row(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    a = _item(db, project, sheet, "A")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    b = _item(db, project, sheet, "B")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert src.calls == ["A", "B"]
