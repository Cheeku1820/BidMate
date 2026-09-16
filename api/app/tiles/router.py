"""The rendered page, streamed (B3 plan). The worker renders a sheet's
tiles and thumbnail into the blob store under `sheet.render_key` -- a
prefix ending in `/` -- once `render_status` is "rendered" and `max_zoom`
is set (app/worker). This module is the one read path for those bytes:
`GET .../tiles/{z}/{x}/{y}.png` for one zoom-level tile, `GET .../thumb.png`
for the sheet-rail thumbnail.

Org-scoped the same way `POST /sheets/{sheet_id}/scale` is
(app/takeoff/mutations.py) -- through `load_sheet`, which defers to
`load_project` for the tenancy check, so there remains exactly one
function that decides whether a project belongs to the caller.

`CACHE` is the one carve-out from `no_shared_caching` (app/main.py): the
URL embeds `render_key`, which is derived from the rendered content
itself, so a given URL's bytes never change -- a tile is immutable per
URL and a browser may hold onto it. Still `private`, never a shared
cache: these are project drawings, not public assets.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session as DbSession
from starlette.background import BackgroundTask

from app.auth.dependencies import current_user
from app.db import get_db
from app.documents.blobstore import BlobNotFound, BlobStore, get_blob_store
from app.identity.models import User
from app.takeoff.models import Sheet
from app.takeoff.router import load_sheet, not_found

router = APIRouter(prefix="/api", tags=["tiles"])

CACHE = "private, max-age=604800, immutable"


def _stream(store: BlobStore, key: str) -> StreamingResponse:
    try:
        body = store.open(key)
    except BlobNotFound:
        raise not_found() from None
    return StreamingResponse(
        iter(lambda: body.read(1024 * 1024), b""),
        media_type="image/png",
        headers={"Cache-Control": CACHE},
        background=BackgroundTask(body.close),
    )


def _require_rendered(sheet: Sheet) -> None:
    if sheet.render_status != "rendered" or not sheet.render_key:
        raise not_found()


@router.get("/sheets/{sheet_id}/tiles/{z}/{x}/{y}.png")
def get_tile(
    sheet_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
) -> Response:
    sheet = load_sheet(sheet_id, db, user)
    # Plain `int` params rather than `Path(ge=0)`: FastAPI's own
    # validation on a negative value answers 422, but a negative tile
    # index isn't a malformed request -- it's the same "no such tile" as
    # any other coordinate outside the grid, so it gets the same 404 the
    # out-of-range and out-of-store cases below fall through to.
    if min(z, x, y) < 0:
        raise not_found()
    _require_rendered(sheet)
    if sheet.max_zoom is None or z > sheet.max_zoom:
        raise not_found()
    return _stream(store, f"{sheet.render_key}{z}/{x}_{y}.png")


@router.get("/sheets/{sheet_id}/thumb.png")
def get_thumb(
    sheet_id: uuid.UUID,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
) -> Response:
    sheet = load_sheet(sheet_id, db, user)
    _require_rendered(sheet)
    return _stream(store, f"{sheet.render_key}thumb.png")
