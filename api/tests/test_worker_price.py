"""The price job, with both sources faked in-process (estimate-first-
pricing §3, §10 'Worker, sources stubbed')."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.jobs import queue
from app.takeoff.models import Item, ItemMarketPrice, Job, MarketLookup, ReviewStatus
from app.worker import __main__ as worker, market_sources, price_job
from app.worker.market_sources import SourceError, SourceResult
from tests.conftest import TestSession
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


def test_cap_is_reread_before_each_call_so_a_concurrent_jobs_row_counts(db, project, sheet, dana, org, monkeypatch):
    """Two projects in the same org can run their price jobs on two
    workers at once; enqueue_price only serialises jobs per project, so
    the cap has to be re-read against the database before every call,
    not tracked as a local counter for the job's own lifetime. Here a
    second job's billed call is simulated landing -- via a side effect
    of this job's own first source call -- in between this job's two
    items; with cap=2 the local job's own count alone (1) would not
    trip an old, per-job-local counter, so a correct re-read is what
    makes the second item resolve over_budget, not the local run having
    made two calls of its own."""
    project.postal_code = "78701"

    class RacySource(FakeSource):
        def lookup(self, query, unit, loc):
            self.calls.append(query)
            db.add(MarketLookup(source="onebuild", query_key="a concurrent job's item", location_key="78701",
                                status="priced", result={}, fetched_at=datetime.now(timezone.utc),
                                billed=True, org_id=org.id))
            db.flush()
            return self._answer

    src = RacySource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src}, cap=2)
    a = _item(db, project, sheet, "Item 1")
    b = _item(db, project, sheet, "Item 2")
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "done"
    assert src.calls == ["Item 1"]   # the second item's own call never happens
    assert db.get(ItemMarketPrice, a.id).outcome == "priced"
    assert db.get(ItemMarketPrice, b.id).outcome == "over_budget"
    assert db.scalar(select(func.count()).select_from(MarketLookup).where(MarketLookup.billed.is_(True))) == 2


def test_each_paid_call_is_committed_before_the_next_so_a_kill_keeps_it(db, project, sheet, dana, monkeypatch):
    """The sandbox kills a price job past its wall clock, and a kill is a
    rollback of whatever the child has not committed. If the whole job
    were one transaction, every paid call -- the meter row and the
    price it bought -- would be lost and re-spent on the retry. So the
    rows a call writes are committed before the next call is made: at
    the moment the second item's lookup runs, a *separate* session (the
    view a kill would leave behind) already sees the first item's
    billed lookup and its price."""
    project.postal_code = "78701"
    seen = []

    class CommittedSource(FakeSource):
        def lookup(self, query, unit, loc):
            self.calls.append(query)
            other = TestSession()
            try:
                seen.append((other.scalar(select(func.count()).select_from(MarketLookup).where(MarketLookup.billed.is_(True))),
                             other.scalar(select(func.count()).select_from(ItemMarketPrice))))
            finally:
                other.close()
            return self._answer

    src = CommittedSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    _item(db, project, sheet, "Item 1"); _item(db, project, sheet, "Item 2")
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "done" and src.calls == ["Item 1", "Item 2"]
    assert seen == [(0, 0), (1, 1)]


def test_a_job_past_its_budget_stops_marks_itself_done_and_queues_the_remainder(db, project, sheet, dana, monkeypatch):
    """Ninety seconds in, the loop stops on its own rather than letting
    the sandbox's 120 s kill it: the items it has priced are written,
    the job is done, and a second price job for the same project and
    run is queued to carry on -- which, because a re-run skips items
    with a fresh row, prices exactly the ones this job never reached."""
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    # One reading at the start of the job, one at the top of each item:
    # the third item is where the budget has run out.
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    items = [_item(db, project, sheet, f"Item {n}") for n in range(4)]
    run_id = uuid.uuid4()
    first = queue.enqueue_price(db, project, dana.id, run_id=run_id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and src.calls == ["Item 0", "Item 1"]
    assert [db.get(ItemMarketPrice, i.id) is not None for i in items] == [True, True, False, False]
    queued = db.scalars(select(Job).where(Job.kind == "price", Job.project_id == project.id, Job.status == "queued")).one()
    assert queued.id != first.id and queued.run_id == run_id and queued.requested_by == dana.id

    # The follow-on job, with the clock back in budget, finishes the set
    # without re-spending on the two already priced.
    monkeypatch.setattr(price_job, "_clock", lambda: 0)
    _run_all(db)
    db.refresh(queued)
    assert queued.status == "done" and src.calls == ["Item 0", "Item 1", "Item 2", "Item 3"]
    assert all(db.get(ItemMarketPrice, i.id).outcome == "priced" for i in items)


def test_refreshing_another_orgs_stale_row_moves_the_meter_to_the_org_that_paid(db, project, sheet, dana, org, monkeypatch):
    """The cache is shared across orgs -- public market data -- but the
    meter row counts against whoever paid for the call it records. A
    stale row org B fetched, refreshed by org A's job, is org A's call
    now: leaving `org_id` on B would bill B for A's lookup and leave
    A's own cap untouched."""
    from app.identity.models import Org
    other = Org(name="Other Electric")
    db.add(other); db.flush()
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    stale = MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701", status="priced",
                         result={}, fetched_at=datetime.now(timezone.utc) - timedelta(days=31), billed=True, org_id=other.id)
    db.add(stale); db.flush()
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert mp.lookup_id == stale.id and src.calls == ["20A duplex receptacle"]
    db.refresh(stale)
    assert stale.org_id == project.org_id == org.id and stale.billed is True
    assert db.scalar(select(func.count()).select_from(MarketLookup)) == 1


def test_a_run_whose_source_calls_all_failed_stops_without_a_follow_on(db, project, sheet, dana, monkeypatch):
    """A source that is down turns every run into `failed` rows and a
    follow-on that does the same -- forever, with Refresh disabled the
    whole time. At the budget, a run that got no answer from any source
    call marks itself done and queues nothing: the rows read 'Market
    estimate didn't complete', and Refresh is the estimator's retry."""
    project.postal_code = "78701"
    src = FakeSource("onebuild", SourceError("timeout"))
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    items = [_item(db, project, sheet, f"Item {n}") for n in range(4)]
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and src.calls == ["Item 0", "Item 1"]
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id)) == 1
    rows = [db.get(ItemMarketPrice, i.id) for i in items]
    assert [r.outcome if r is not None else None for r in rows] == ["failed", "failed", None, None]


def test_a_run_with_one_answer_among_failures_still_queues_the_follow_on(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    answers = iter([SourceError("timeout"), SourceError("timeout"), _priced()])

    class Flaky(FakeSource):
        def lookup(self, query, unit, loc):
            self.calls.append(query)
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return a

    src = Flaky("onebuild")
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    for n in range(5):
        _item(db, project, sheet, f"Item {n}")
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and len(src.calls) == 3
    assert db.scalar(select(func.count()).select_from(Job).where(
        Job.kind == "price", Job.project_id == project.id, Job.status == "queued")) == 1


def test_a_run_past_budget_that_made_no_source_call_still_queues_the_follow_on(db, project, sheet, dana, monkeypatch):
    """Nothing this run did was the problem -- quote-required items cost
    no call -- so the remainder is safe to continue."""
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    _item(db, project, sheet, "Switch Board MSBS"); _item(db, project, sheet, "Transformer T1"); _item(db, project, sheet, "Item 2")
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and src.calls == []
    assert db.scalar(select(func.count()).select_from(Job).where(
        Job.kind == "price", Job.project_id == project.id, Job.status == "queued")) == 1
