"""The queue's closed sets and per-kind limits. Imported by models.py
(check constraints), queue.py, and the worker -- never retyped."""
import os

JOB_KINDS = ("read", "classify", "sheet", "render")
JOB_STATUSES = ("queued", "running", "done", "failed")

# B3: the closed set for Sheet.render_status -- a sheet property on its
# own axis (like `kind`), never one of the four review labels.
RENDER_STATUSES = ("pending", "rendered", "failed")

_DEFAULT_TIMEOUTS = {"read": 120, "classify": 300, "sheet": 180, "render": 300}


def timeout_for(kind: str) -> int:
    """Seconds a job of `kind` may run before its child is killed.
    WORKER_TIMEOUT_<KIND> overrides, for the corpus tests."""
    return int(os.environ.get(f"WORKER_TIMEOUT_{kind.upper()}", _DEFAULT_TIMEOUTS[kind]))


MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 30
STALE_GRACE_SECONDS = 60
