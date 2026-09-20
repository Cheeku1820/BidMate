"""price: a market estimate for every countable item on the project
(docs/specs/estimate-first-pricing.md §3). Cache first, then the
source, one call per distinct query; a cap per org per month; every
outcome written so the row can say what happened. A source failure
marks its items "failed" and the job still completes -- one dead feed
must not fail a run.

Two things keep paid calls from being lost. Every billed call's rows --
the `market_lookups` meter and the item's price -- are committed the
moment they are written, so a job the sandbox kills part-way keeps what
it paid for instead of rolling it all back and re-spending it on the
retry. And the job stops itself before the sandbox would: past
PRICE_JOB_BUDGET_SECONDS it marks itself done and queues another
`price` job for the same project, which skips the fresh rows and
carries on from where this one stopped."""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs import queue
from app.market.classify import classify_for_lookup, lookup_key
from app.takeoff.models import Item, ItemMarketPrice, Job, MarketLookup, Project
from app.takeoff.totals import countable_items
from app.worker.handlers import register
from app.worker.market_sources import SourceError, SourceResult, _cents, get_sources

CACHE_DAYS = 30
# The sandbox gives a price job a 120 s wall clock (jobs/schemas.py's
# timeout_for) and kills the child past it. Stopping at 90 s leaves room
# for a source call in flight (20 s timeout, market_sources.py) and the
# final commit, so the job ends on its own terms -- done, with the
# remainder queued -- rather than as a timeout the estimator reads as
# "Market estimate didn't complete".
PRICE_JOB_BUDGET_SECONDS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock() -> float:
    return time.monotonic()


def billed_this_month(db: Session, org_id) -> int:
    start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(MarketLookup).where(
        MarketLookup.org_id == org_id, MarketLookup.billed.is_(True), MarketLookup.fetched_at >= start)) or 0


def _fresh(lookup: MarketLookup | None) -> bool:
    return lookup is not None and lookup.fetched_at >= _now() - timedelta(days=CACHE_DAYS)


def _result_from_cache(lookup: MarketLookup, source_name: str) -> SourceResult:
    """Rebuild a SourceResult from a stored, trimmed result."""
    r = lookup.result or {}
    if lookup.status != "priced":
        return SourceResult(lookup.status, None, None, None, None, "", lookup.location_key, r)
    if source_name == "onebuild":
        m = r.get("matched") or {}
        price = _cents(m.get("materialRateUsdCents"))
        labor = _cents(m.get("laborRateUsdCents"))
        return SourceResult("priced", price, price, price, labor, m.get("uom") or "", f"ZIP {lookup.location_key}", r)
    prices = sorted(Decimal(str(s["price"])) for s in r.get("sellers") or [])
    median = Decimal(str(statistics.median(prices))).quantize(Decimal("0.01"))
    return SourceResult("priced", median, prices[0], prices[-1], None, "EA", lookup.location_key, r)


def _write(db: Session, item: Item, *, outcome: str, source: str | None, query: str, res: SourceResult | None,
           lookup: MarketLookup | None, run_id) -> None:
    row = db.get(ItemMarketPrice, item.id) or ItemMarketPrice(item_id=item.id)
    row.outcome, row.source, row.query, row.run_id = outcome, source, query[:300], run_id
    row.lookup_id = lookup.id if lookup is not None else None
    row.unit_price = res.unit_price if res else None
    row.price_low, row.price_high = (res.low, res.high) if res else (None, None)
    row.labor_rate_per_unit = res.labor_rate if res else None
    row.unit = (res.uom if res else "") or ""
    row.location_label = (res.location_label if res else "") or ""
    row.fetched_at = lookup.fetched_at if lookup is not None else None
    db.add(row)


@register("price")
def run(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    if project is None:
        return
    sources = get_sources()
    cap = settings.market_lookup_monthly_cap
    started = _clock()
    items = list(db.scalars(countable_items(project.id)))
    for item in items:
        if _clock() - started > PRICE_JOB_BUDGET_SECONDS:
            # Out of time. Every item before this one is written and
            # committed; this one and the rest are untouched (no row
            # yet, or the row they had). Done first, then the follow-on
            # job -- enqueue_price refuses while this one still reads
            # as running.
            queue.mark_done(db, job)
            queue.enqueue_price(db, project, job.requested_by, run_id=job.run_id)
            break
        existing = db.get(ItemMarketPrice, item.id)
        if existing is not None and existing.outcome == "priced" and existing.lookup_id is not None \
                and _fresh(db.get(MarketLookup, existing.lookup_id)):
            continue
        lookup = classify_for_lookup(item.name, item.description or "", item.unit)
        if lookup.source is None:
            _write(db, item, outcome="quote_required", source=None, query="", res=None, lookup=None, run_id=job.run_id)
            continue
        source = sources.get(lookup.source)
        if source is None:
            _write(db, item, outcome="unavailable", source=lookup.source, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        loc = source.location_key(project)
        if not loc:
            _write(db, item, outcome="location_needed", source=lookup.source, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        key = lookup_key(lookup.query)
        cached = db.scalars(select(MarketLookup).where(
            MarketLookup.source == source.name, MarketLookup.query_key == key, MarketLookup.location_key == loc)).first()
        if _fresh(cached):
            res = _result_from_cache(cached, source.name)
            _write(db, item, outcome=res.status, source=source.name, query=lookup.query, res=res if res.status == "priced" else None,
                   lookup=cached, run_id=job.run_id)
            continue
        # Re-read on every call, not once per job: two projects in the same
        # org can run on two workers at once, and a local counter here
        # would let both pass `used < cap` against the same stale count
        # and overshoot it together. A COUNT is cheap next to the network
        # call it gates, and the commit below makes this job's own calls
        # visible to its own next check and to the other worker's.
        if billed_this_month(db, project.org_id) >= cap:
            _write(db, item, outcome="over_budget", source=source.name, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        try:
            res = source.lookup(lookup.query, item.unit, loc)
        except SourceError:
            _write(db, item, outcome="failed", source=source.name, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        row = cached or MarketLookup(source=source.name, query_key=key, location_key=loc, org_id=project.org_id)
        # A stale row from another org is refreshed in place, and the
        # meter row belongs to whoever paid for the call that is on it
        # now -- so a refresh moves it to this project's org.
        row.org_id = project.org_id
        row.status, row.result, row.fetched_at, row.billed = res.status, res.result, _now(), True
        db.add(row)
        db.flush()
        _write(db, item, outcome=res.status, source=source.name, query=lookup.query,
               res=res if res.status == "priced" else None, lookup=row, run_id=job.run_id)
        # The call is paid for: commit its meter row and the item's
        # price now, so a kill later in the loop keeps them. The job row
        # stays `running`; handlers.run marks it done at the end.
        db.commit()
    db.flush()
