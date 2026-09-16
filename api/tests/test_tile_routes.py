"""The tile routes (B3 plan) -- streaming a rendered sheet's tiles and
thumbnail out of the blob store, org-scoped through `load_sheet` like
`POST /sheets/{sheet_id}/scale`, and cacheable per content hash: the URL
carries `render_key`, which changes whenever the rendered pixels do, so
this is the one place in the API that lets a client (and a shared cache)
hold onto a response -- see the `no_shared_caching` middleware's docstring
in app/main.py for why every other route stays `no-store`.
"""
import io

import pytest

from app.documents import blobstore
from app.documents.blobstore import MemoryBlobStore
from app.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 16


@pytest.fixture
def store():
    s = MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


def _rendered(db, sheet, store, max_zoom=2):
    sheet.render_key = f"orgs/o/projects/p/sheets/{sheet.id}/abcdef0123456789/"
    sheet.render_status, sheet.max_zoom = "rendered", max_zoom
    db.flush()
    for k in ("0/0_0.png", "2/3_1.png", "thumb.png"):
        store.put(sheet.render_key + k, io.BytesIO(PNG), "image/png", len(PNG))


def test_a_tile_streams_with_a_long_private_cache(client, db, sheet, store, signed_in_user):
    _rendered(db, sheet, store)
    res = client.get(f"/api/sheets/{sheet.id}/tiles/2/3/1.png")
    assert res.status_code == 200 and res.content == PNG and res.headers["content-type"] == "image/png"
    assert res.headers["cache-control"] == "private, max-age=604800, immutable"
    assert res.headers["vary"] == "Cookie"


def test_the_thumbnail_streams(client, db, sheet, store, signed_in_user):
    _rendered(db, sheet, store)
    res = client.get(f"/api/sheets/{sheet.id}/thumb.png")
    assert res.status_code == 200 and res.content == PNG


def test_404_when_pending_out_of_zoom_or_missing_tile(client, db, sheet, store, signed_in_user):
    assert client.get(f"/api/sheets/{sheet.id}/tiles/0/0/0.png").status_code == 404   # pending
    _rendered(db, sheet, store, max_zoom=2)
    assert client.get(f"/api/sheets/{sheet.id}/tiles/3/0/0.png").status_code == 404   # z > max_zoom
    assert client.get(f"/api/sheets/{sheet.id}/tiles/1/0/0.png").status_code == 404   # not in store
    assert client.get(f"/api/sheets/{sheet.id}/tiles/0/-1/0.png").status_code == 404  # negative


def test_every_other_route_keeps_no_store(client, project, signed_in_user):
    assert client.get(f"/api/projects/{project.id}/snapshot").headers["cache-control"] == "private, no-store"
