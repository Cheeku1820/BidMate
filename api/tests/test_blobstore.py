"""The storage boundary. MemoryBlobStore is what every service test uses;
S3BlobStore is exercised against MinIO when it is reachable (compose
locally, a service container in CI) and skipped with a reason otherwise."""

import io
import os
import uuid

import pytest

from app.documents import blobstore


def test_memory_store_round_trips_and_forgets():
    store = blobstore.MemoryBlobStore()
    key = "orgs/o/projects/p/documents/d.pdf"
    assert not store.exists(key)
    store.put(key, io.BytesIO(b"%PDF-1.4 hello"), "application/pdf", 14)
    assert store.exists(key)
    assert store.open(key).read() == b"%PDF-1.4 hello"
    store.delete(key)
    assert not store.exists(key)
    with pytest.raises(blobstore.BlobNotFound):
        store.open(key)


def test_memory_store_delete_is_idempotent():
    store = blobstore.MemoryBlobStore()
    store.delete("never-there")  # no raise


def _minio_reachable() -> bool:
    import socket
    from urllib.parse import urlparse
    from app.config import settings
    u = urlparse(settings.blob_endpoint)
    try:
        with socket.create_connection((u.hostname, u.port or 9000), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _minio_reachable(), reason="MinIO not reachable at settings.blob_endpoint")
def test_s3_store_round_trips_against_minio():
    from app.config import settings
    store = blobstore.S3BlobStore(
        settings.blob_endpoint, settings.blob_access_key, settings.blob_secret_key,
        settings.blob_bucket, settings.blob_region,
    )
    key = f"tests/{uuid.uuid4().hex}.pdf"
    assert not store.exists(key)
    store.put(key, io.BytesIO(b"%PDF-1.4 minio"), "application/pdf", 14)
    assert store.exists(key)
    assert store.open(key).read() == b"%PDF-1.4 minio"
    store.delete(key)
    assert not store.exists(key)
    with pytest.raises(blobstore.BlobNotFound):
        store.open(key)


def test_get_blob_store_is_a_singleton():
    a = blobstore.get_blob_store()
    b = blobstore.get_blob_store()
    assert a is b
