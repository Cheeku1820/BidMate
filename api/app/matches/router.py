"""Thin HTTP layer for symbol matches. router -> service -> models."""
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.matches import service
from app.matches.schemas import MatchBoxIn, MatchItemOut, MatchItemsIn, SymbolMatchOut
from app.takeoff import snapshot as snapshot_module
from app.takeoff.models import SymbolMatch
from app.takeoff.router import load_sheet
from app.takeoff.snapshot import item_out

router = APIRouter(prefix="/api", tags=["matches"])


def _out(m: SymbolMatch) -> SymbolMatchOut:
    return SymbolMatchOut(id=m.id, sheet_id=m.sheet_id, box=list(m.box), status=m.status,
                          count=len(m.matches or []), matches=[list(x) for x in (m.matches or [])], error=m.error,
                          suggested_name=m.suggested_name)


@router.post("/sheets/{sheet_id}/matches", response_model=SymbolMatchOut, status_code=201)
def create_match(sheet_id: uuid.UUID, payload: MatchBoxIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    sheet = load_sheet(sheet_id, db, user)
    match = service.create(db, user, sheet, [payload.x, payload.y, payload.w, payload.h])
    db.commit()
    return _out(match)


@router.get("/symbol-matches/{match_id}", response_model=SymbolMatchOut)
def get_match(match_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return _out(service.load_match(match_id, db, user))


@router.post("/symbol-matches/{match_id}/items", response_model=MatchItemOut, status_code=201)
def accept_match(match_id: uuid.UUID, payload: MatchItemsIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    match = service.load_match(match_id, db, user)
    project_id = match.project_id
    item, action = service.accept(db, user, match, name=payload.name, symbol=payload.symbol, system=payload.system,
                                  not_sure=payload.not_sure)
    db.commit()
    # The project snapshot version, not Item.version -- see
    # MatchItemOut's docstring: the client's mutateItem() treats this
    # response like any other item mutation's.
    version = snapshot_module.version(db, project_id)
    return MatchItemOut(label=action.label, version=version, item=item_out(db, item))


@router.delete("/symbol-matches/{match_id}", status_code=204)
def discard_match(match_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    match = service.load_match(match_id, db, user)
    service.discard(db, user, match)
    db.commit()
    return Response(status_code=204)
