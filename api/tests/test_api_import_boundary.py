"""Guards ROADMAP invariant 7 (processing internals stop at the API
boundary) at the process level, not just the response-shape level:
importing `app.main` -- the FastAPI app every API worker boots -- must
never pull in `app.engine`.

`app/engine/__init__.py` eagerly does `from .pipeline import run`, which
imports `documents`, `counting`, `classification`, `pricing`,
`title_block`, `page_frame`, and `pymupdf`. If anything reachable from
`app.main` imported `app.engine`, a bug anywhere in that pipeline (a
broken `counting.py`, a missing `pymupdf` wheel) would stop the API
container from booting, not just the engine. `ingest.py` is the one
module that used to risk this -- see its own `SHEET_KINDS` comment for
why it carries a mirrored copy of `app/engine/sheet_kind.py`'s closed set
instead of importing it.
"""
import os
import subprocess
import sys


def test_the_api_process_does_not_import_the_engine():
    """A bug in counting.py must not stop the API container booting.
    Run in a subprocess so this test's own imports don't pollute it."""
    code = (
        "import sys; import app.main; "
        "print(sorted(m for m in sys.modules if m.startswith('app.engine') or m == 'pymupdf'))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ},
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert out.stdout.strip() == "[]", out.stdout
