"""The mirror of test_api_import_boundary.py: the worker is the only
process that opens a PDF, and it must never pull in the FastAPI app or
any router. A worker that imported `app.main` would boot the API's
dependency graph in every child, and a router imported from a job body
would be one refactor away from a route that opens an upload in the API
process."""
import os
import subprocess
import sys

_API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modules_after(code: str) -> str:
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ},
        cwd=_API_DIR,
    )
    return out.stdout.strip()


def test_the_worker_process_does_not_import_the_api_or_a_router():
    code = (
        "import sys; import app.worker.handlers; import app.worker.__main__; "
        "print(sorted(m for m in sys.modules if m == 'app.main' or 'router' in m))"
    )
    assert _modules_after(code) == "[]"


def test_the_shared_queue_imports_neither_side():
    """`app.jobs.queue` is imported by the API and the worker both, so it
    may import no engine (the API would boot it) and no router."""
    code = (
        "import sys; import app.jobs.queue; import app.jobs.copy; "
        "print(sorted(m for m in sys.modules if m == 'app.main' or 'router' in m "
        "or m.startswith('app.engine') or m == 'pymupdf'))"
    )
    assert _modules_after(code) == "[]"


def test_the_worker_process_can_resolve_every_foreign_key_on_its_own():
    """`python -m app.worker` never imports the API, so nothing there
    registers the identity models unless the takeoff models do it
    themselves. Sorting the metadata resolves every ForeignKey the way
    the unit of work does at claim_next's flush -- no database needed
    -- and used to raise NoReferencedTableError on jobs.requested_by ->
    users.id in the real worker while every in-process test, which
    imports app.main first, passed."""
    code = (
        "import app.worker.handlers; import app.worker.__main__; "
        "from app.db import Base; print(len(Base.metadata.sorted_tables) > 0)"
    )
    assert _modules_after(code) == "True"
