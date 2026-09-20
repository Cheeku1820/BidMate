"""The two market tables and the columns this feature adds to existing
ones exist, with the shapes the spec sets out."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.jobs.schemas import JOB_KINDS, timeout_for
from app.documents.schemas import DOC_TYPES
from app.takeoff.models import ItemMarketPrice, MarketLookup, ProjectMaterialPrice


def test_market_lookup_is_unique_per_source_query_location(db, org):
    row = MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701",
                       status="priced", result={"rate": 1}, fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(row); db.flush()
    dup = MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701",
                       status="priced", result={}, fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_item_market_price_is_one_per_item_and_cascades(db, item, org):
    lookup = MarketLookup(source="onebuild", query_key="q", location_key="78701", status="priced", result={},
                          fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(lookup); db.flush()
    mp = ItemMarketPrice(item_id=item.id, lookup_id=lookup.id, outcome="priced", source="onebuild", query="q",
                         unit_price=Decimal("12.40"), price_low=Decimal("12.40"), price_high=Decimal("12.40"),
                         unit="ea", location_label="Travis County, TX", fetched_at=datetime.now(timezone.utc))
    db.add(mp); db.flush()
    db.delete(item); db.flush()
    assert db.scalars(select(ItemMarketPrice).where(ItemMarketPrice.item_id == item.id)).first() is None


def test_project_material_price_carries_supplier_fields(db, item):
    row = ProjectMaterialPrice(item_id=item.id, price_override=Decimal("9.10"), source="supplier_quote",
                               supplier_name="Codale", quote_date=date(2026, 9, 18))
    db.add(row); db.flush()
    db.refresh(row)
    assert row.supplier_name == "Codale" and row.quote_date == date(2026, 9, 18)


def test_project_has_postal_code(project):
    assert project.postal_code is None


def test_job_kinds_and_doc_types_gained_their_values():
    assert "price" in JOB_KINDS and "price_sheet" in JOB_KINDS
    assert timeout_for("price") == 120 and timeout_for("price_sheet") == 60
    assert "Pricing" in DOC_TYPES
