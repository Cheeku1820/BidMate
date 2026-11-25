#!/usr/bin/env python3
"""The real bid corpus, distributed without entering git history.

`bid_examples/` holds real contractor bid sets -- NDA'd drawings, named
firms -- and `.gitignore` keeps them out of the repo for the reason
ROADMAP.md 3.3 gives. That left the engine regression tests pointing at
one machine's disk: `api/tests/bid_set.py` skips every assertion when the
corpus is absent, so on any other checkout the guards on a defect that
silently zeroed 43 of 45 items passed by not running.

This script is the path between those two facts. The sets live in an
S3-compatible bucket whose access is granted per person; a checkout runs
`fetch` and gets the same corpus the assertions were written against.
Nothing confidential reaches the repo -- what is committed is
`corpus-manifest.json`: names, sizes, and SHA-256 digests.

    pack              build one archive per set under .corpus-cache/,
                      write the manifest. No credentials, no network.
    upload            pack, then put each archive in the bucket.
    fetch [set ...]   download the named sets (default: all), verify each
                      digest, extract into bid_examples/.
    verify            check what is on disk against the manifest.

Configuration, all by environment:

    CORPUS_BUCKET        bucket name                      (upload, fetch)
    CORPUS_ACCESS_KEY    access key                       (upload, fetch)
    CORPUS_SECRET_KEY    secret key                       (upload, fetch)
    CORPUS_ENDPOINT      S3-compatible endpoint; omit for AWS S3 itself
    CORPUS_REGION        default us-east-1
    CORPUS_PREFIX        key prefix, default bid-corpus/v1
    CORPUS_BASE_URL      fetch over plain HTTPS from this base instead of
                         the S3 API -- for a presigned or reader-role URL,
                         so a collaborator needs no credentials at all

A digest mismatch is a hard failure: a truncated download is worse than
no download, because the tests would run against it and report numbers
nobody could reproduce.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# BIDMATE_CORPUS, not a name of this script's own: api/tests/bid_set.py
# already reads that variable to find the sets, so pointing the tests and
# the fetcher at one directory stays a single decision.
CORPUS = Path(os.environ.get("BIDMATE_CORPUS") or ROOT / "bid_examples")
CACHE = Path(os.environ.get("CORPUS_CACHE") or ROOT / ".corpus-cache")
MANIFEST = Path(__file__).resolve().parent / "corpus-manifest.json"

# Directories under bid_examples/ that are not bid sets. `_derived` holds
# generated notes, not source drawings, and is cheap to regenerate.
NOT_A_SET = {"_derived"}

# Noise macOS leaves in a directory tree. Excluded from every archive so
# a digest does not change because someone opened a folder in Finder.
JUNK_NAMES = {".DS_Store", "__MACOSX", ".Spotlight-V100", ".fseventsd"}

# What each set is for, mirrored from api/tests/bid_set.py so the manifest
# records which sets the regression assertions actually need. `vector`
# sets get counted placements; `raster` sets must report every page
# unreadable. A set absent from both is corpus material without an
# assertion yet.
ROLES = {
    "Unalaska Bid": "vector",
    "Kittles Saxony": "vector",
    "Pulte Sagebriar Clubhouse": "vector",
    "TSC Nutrition & Technology Renovations": "vector",
    "United Utility Supply": "vector",
    "FedEx Office Bid": "raster",
    "Gerber Collision & Glass Bid": "raster",
}

CHUNK = 1024 * 1024


def _size(n: int) -> str:
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _sets_on_disk() -> list[str]:
    if not CORPUS.is_dir():
        return []
    return sorted(
        p.name for p in CORPUS.iterdir()
        if p.is_dir() and p.name not in NOT_A_SET and not p.name.startswith(".")
    )


def _archive_name(set_name: str) -> str:
    """A key-safe filename for a set whose name carries spaces and `&`."""
    return set_name.replace(" & ", "-and-").replace(" ", "-").lower() + ".tar.gz"


def _clean(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(tarinfo.name).parts
    if any(part in JUNK_NAMES for part in parts):
        return None
    # Ownership and access times are machine detail; dropping them keeps a
    # re-pack on another checkout byte-identical.
    tarinfo.uid = tarinfo.gid = 0
    tarinfo.uname = tarinfo.gname = ""
    tarinfo.mtime = 0
    return tarinfo


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        sys.exit(f"no manifest at {MANIFEST} -- run `pack` on a checkout that has the sets")
    return json.loads(MANIFEST.read_text())


# --- pack -------------------------------------------------------------


def pack(only: list[str] | None = None) -> dict:
    names = _sets_on_disk()
    if not names:
        sys.exit(f"no bid sets under {CORPUS} -- nothing to pack")
    if only:
        missing = [n for n in only if n not in names]
        if missing:
            sys.exit("not on disk: " + ", ".join(missing))
        names = [n for n in names if n in only]

    CACHE.mkdir(exist_ok=True)
    entries: dict[str, dict] = {}
    existing = _load_manifest()["sets"] if MANIFEST.exists() else {}

    for name in names:
        archive = CACHE / _archive_name(name)
        source = CORPUS / name
        files = [p for p in source.rglob("*") if p.is_file() and p.name not in JUNK_NAMES]
        raw = sum(p.stat().st_size for p in files)
        print(f"packing {name} -- {len(files)} files, {_size(raw)}", flush=True)

        # Deterministic: same files in, same digest out, so re-packing an
        # untouched set does not churn the manifest and a digest can be
        # reproduced on another machine. `tarfile.open("w:gz")` is not
        # enough -- it stamps the current time into the gzip header, which
        # changes the digest on every run -- so the gzip layer is built
        # explicitly with mtime=0. compresslevel=1 because the corpus is
        # almost entirely PDFs, whose streams are already deflated; level 9
        # spends minutes of CPU per set to beat level 1 by about a percent.
        with archive.open("wb") as raw_out:
            with gzip.GzipFile(fileobj=raw_out, mode="wb", compresslevel=1, mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tf:
                    # Sorted, so directory iteration order on one machine
                    # cannot change the archive either.
                    for path in sorted(p for p in source.rglob("*") if p.name not in JUNK_NAMES):
                        tf.add(path, arcname=str(Path(name) / path.relative_to(source)),
                               recursive=False, filter=_clean)

        entries[name] = {
            "archive": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": _digest(archive),
            "files": len(files),
            "unpacked_bytes": raw,
            "role": ROLES.get(name, "unassigned"),
        }
        print(f"  -> {archive.name}  {_size(entries[name]['bytes'])}", flush=True)

    merged = {**existing, **entries}
    MANIFEST.write_text(json.dumps(
        {
            "version": 1,
            "prefix": os.environ.get("CORPUS_PREFIX", "bid-corpus/v1"),
            "sets": dict(sorted(merged.items())),
        },
        indent=2,
    ) + "\n")
    print(f"\nmanifest: {MANIFEST.relative_to(ROOT)}  ({len(merged)} sets)")
    return merged


# --- the bucket -------------------------------------------------------


def _client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.exit("boto3 missing -- use the repo venv: .enginevenv/bin/python scripts/corpus.py ...")

    bucket = os.environ.get("CORPUS_BUCKET")
    key = os.environ.get("CORPUS_ACCESS_KEY")
    secret = os.environ.get("CORPUS_SECRET_KEY")
    if not (bucket and key and secret):
        sys.exit("set CORPUS_BUCKET, CORPUS_ACCESS_KEY, CORPUS_SECRET_KEY (see this file's docstring)")

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("CORPUS_ENDPOINT") or None,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=os.environ.get("CORPUS_REGION", "us-east-1"),
        # Path-style for the same reason app/documents/blobstore.py uses it:
        # a virtual-host bucket name will not resolve against MinIO or a
        # plain compose alias.
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    ), bucket


def upload(only: list[str] | None = None) -> None:
    manifest = pack(only)
    client, bucket = _client()
    prefix = os.environ.get("CORPUS_PREFIX", "bid-corpus/v1").strip("/")

    names = only or list(manifest)
    for name in names:
        entry = manifest[name]
        archive = CACHE / entry["archive"]
        key = f"{prefix}/{entry['archive']}"
        print(f"uploading {key}  ({_size(entry['bytes'])})", flush=True)
        client.upload_file(
            str(archive), bucket, key,
            ExtraArgs={"ContentType": "application/gzip", "Metadata": {"sha256": entry["sha256"]}},
        )

    key = f"{prefix}/corpus-manifest.json"
    client.upload_file(str(MANIFEST), bucket, key, ExtraArgs={"ContentType": "application/json"})
    print(f"\nuploaded {len(names)} set(s) + manifest to s3://{bucket}/{prefix}/")
    print("commit scripts/corpus-manifest.json so a checkout knows what to fetch.")


def _download(entry: dict, dest: Path) -> None:
    base = os.environ.get("CORPUS_BASE_URL")
    if base:
        url = base.rstrip("/") + "/" + entry["archive"]
        try:
            with urllib.request.urlopen(url) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
        except urllib.error.HTTPError as e:
            sys.exit(f"{url} -> HTTP {e.code}. If the bucket is private, use the S3 credentials instead.")
        return

    client, bucket = _client()
    prefix = os.environ.get("CORPUS_PREFIX", "bid-corpus/v1").strip("/")
    client.download_file(bucket, f"{prefix}/{entry['archive']}", str(dest))


def fetch(only: list[str] | None = None, force: bool = False) -> None:
    manifest = _load_manifest()
    sets = manifest["sets"]
    os.environ.setdefault("CORPUS_PREFIX", manifest.get("prefix", "bid-corpus/v1"))

    names = only or list(sets)
    unknown = [n for n in names if n not in sets]
    if unknown:
        sys.exit("not in the manifest: " + ", ".join(unknown) + "\nknown: " + ", ".join(sets))

    CORPUS.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    fetched = skipped = 0

    for name in names:
        entry = sets[name]
        target = CORPUS / name
        if target.exists() and not force:
            print(f"have {name} -- skipping (--force to replace)")
            skipped += 1
            continue

        archive = CACHE / entry["archive"]
        if archive.exists() and _digest(archive) == entry["sha256"]:
            print(f"cached {entry['archive']}")
        else:
            print(f"downloading {entry['archive']}  ({_size(entry['bytes'])})", flush=True)
            fd, tmp_name = tempfile.mkstemp(dir=CACHE, suffix=".part")
            os.close(fd)
            tmp = Path(tmp_name)
            try:
                _download(entry, tmp)
                got = _digest(tmp)
                if got != entry["sha256"]:
                    tmp.unlink(missing_ok=True)
                    sys.exit(
                        f"{entry['archive']}: digest mismatch\n"
                        f"  manifest {entry['sha256']}\n  download {got}\n"
                        "Refusing to extract -- the tests would run against it and "
                        "report numbers nobody could reproduce."
                    )
                tmp.replace(archive)
            finally:
                tmp.unlink(missing_ok=True)

        if target.exists():
            shutil.rmtree(target)
        print(f"  extracting into {target}{os.sep}", flush=True)
        with tarfile.open(archive, "r:gz") as tf:
            # filter="data" refuses absolute paths, `..`, and device nodes.
            # These archives are ours, but the corpus is exactly the kind of
            # thing that gets re-hosted, and an archive is untrusted input.
            try:
                tf.extractall(CORPUS, filter="data")
            except TypeError:  # Python < 3.12
                tf.extractall(CORPUS)
        fetched += 1

    print(f"\n{fetched} fetched, {skipped} already present -> {CORPUS}")
    if fetched:
        print("the engine regression tests read from here via api/tests/bid_set.py")


def verify() -> None:
    manifest = _load_manifest()["sets"]
    on_disk = set(_sets_on_disk())
    bad = 0

    for name, entry in manifest.items():
        if name not in on_disk:
            print(f"absent   {name}")
            continue
        files = [p for p in (CORPUS / name).rglob("*") if p.is_file() and p.name not in JUNK_NAMES]
        raw = sum(p.stat().st_size for p in files)
        if len(files) == entry["files"] and raw == entry["unpacked_bytes"]:
            print(f"ok       {name}  ({entry['files']} files, {_size(raw)}, {entry['role']})")
        else:
            print(
                f"DIFFERS  {name}  on disk {len(files)} files / {_size(raw)};"
                f" manifest {entry['files']} files / {_size(entry['unpacked_bytes'])}"
            )
            bad += 1

    extra = on_disk - set(manifest)
    for name in sorted(extra):
        print(f"unlisted {name}  -- run `pack` to add it")

    if bad:
        sys.exit(f"\n{bad} set(s) differ from the manifest")
    print(f"\n{len(on_disk & set(manifest))} of {len(manifest)} sets present and matching")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pack, upload, and fetch the real bid corpus.",
        epilog="Credentials and endpoint come from the environment -- see scripts/corpus.py.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="build archives + manifest locally")
    p.add_argument("sets", nargs="*")
    p = sub.add_parser("upload", help="pack, then push to the bucket")
    p.add_argument("sets", nargs="*")
    p = sub.add_parser("fetch", help="download and extract into bid_examples/")
    p.add_argument("sets", nargs="*")
    p.add_argument("--force", action="store_true", help="replace sets already on disk")
    sub.add_parser("verify", help="check bid_examples/ against the manifest")
    sub.add_parser("list", help="show the sets the manifest knows")

    args = ap.parse_args()
    if args.cmd == "pack":
        pack(args.sets or None)
    elif args.cmd == "upload":
        upload(args.sets or None)
    elif args.cmd == "fetch":
        fetch(args.sets or None, args.force)
    elif args.cmd == "verify":
        verify()
    elif args.cmd == "list":
        m = _load_manifest()
        print(f"prefix: {m.get('prefix')}\n")
        for name, e in m["sets"].items():
            print(f"{_size(e['bytes']):>9}  {e['role']:<10}  {name}")
        print(f"\ntotal {_size(sum(e['bytes'] for e in m['sets'].values()))}")


if __name__ == "__main__":
    main()
