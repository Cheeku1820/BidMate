"""Where uploaded documents live.

A `BlobStore` is the only thing the rest of the API knows about storage.
`S3BlobStore` talks to MinIO locally and to S3 in deployment through the
same API; `MemoryBlobStore` is what tests use. The interface exists so a
presigned direct-to-storage upload can be a second `put` path later
rather than a redesign (docs/specs/documents-stored.md §5).

Keys are built by app/documents/service.py from the caller's org and
the project it owns -- never from anything the client sends -- which is
what makes storage tenant-scoped by construction rather than by policy.
"""

from __future__ import annotations

import io
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


class BlobNotFound(Exception):
    """`open()` on a key that holds nothing."""


class BlobStore(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class MemoryBlobStore:
    """In-process store for tests. Holds bytes; forgets on delete."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None:
        self.blobs[key] = (stream.read(), content_type)

    def open(self, key: str) -> BinaryIO:
        try:
            return io.BytesIO(self.blobs[key][0])
        except KeyError:
            raise BlobNotFound(key) from None

    def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.blobs


class S3BlobStore:
    """MinIO or S3. Path-style addressing because MinIO's default is
    path-style and a virtual-host bucket name would not resolve against
    a compose alias."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None:
        self.client.upload_fileobj(stream, self.bucket, key, ExtraArgs={"ContentType": content_type})

    def open(self, key: str) -> BinaryIO:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise BlobNotFound(key) from None
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise


_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    """FastAPI dependency. One client per process; tests override it with
    `app.dependency_overrides[get_blob_store] = lambda: MemoryBlobStore()`."""
    global _store
    if _store is None:
        _store = S3BlobStore(
            settings.blob_endpoint, settings.blob_access_key, settings.blob_secret_key,
            settings.blob_bucket, settings.blob_region,
        )
    return _store
