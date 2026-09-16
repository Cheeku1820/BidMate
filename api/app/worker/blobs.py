"""Blob -> temp file. The worker never streams a PDF into memory -- pymupdf
wants a path (or the whole file in RAM), so a stored document is copied to
a temp file first and cleaned up after the read job is done with it."""
from __future__ import annotations

import contextlib
import os
import tempfile

from app.documents.blobstore import BlobNotFound, get_blob_store  # re-exported so tests can patch it here
from app.jobs import copy
from app.worker.sandbox import Terminal, Transient


@contextlib.contextmanager
def blob_to_tempfile(key: str, filename: str = "this file"):
    """Copy `key`'s bytes to a temp file and yield its path, deleting it
    on the way out. `get_blob_store` is looked up on this module at call
    time (not captured at import time) so a test can monkeypatch
    `blobs.get_blob_store` and have this function pick up the patch."""
    store = get_blob_store()
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        try:
            with os.fdopen(fd, "wb") as out, store.open(key) as body:
                for chunk in iter(lambda: body.read(1 << 20), b""):
                    out.write(chunk)
        except BlobNotFound:
            raise Terminal(f"{filename} isn't available any more. Upload it again to include it in this takeoff.") from None
        except (OSError, ConnectionError) as exc:
            raise Transient(copy.UNAVAILABLE) from exc
        except Exception as exc:  # noqa: BLE001 -- botocore's own error classes: unreachable endpoint, throttling
            if "botocore" in type(exc).__module__ or "boto" in type(exc).__module__:
                raise Transient(copy.UNAVAILABLE) from exc
            raise
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
