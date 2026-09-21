"""Guards ROADMAP invariant 7 (processing internals stop at the API
boundary) at the process level, not just the response-shape level: the
API process must never pull in the engine's document/PDF pipeline.

The boundary is narrower than "no app.engine at all" (say-what-it-is
spec, `docs/specs/say-what-it-is.md`): `POST /items/{id}/resolve` makes
a live classification call synchronously from the API process, through
`engine.conversation`, `engine.resolve`, `engine.llm`, and
`engine.catalog` -- the language-side agents, which read already-
extracted text and never open a file. What this test still bans is the
document/PDF pipeline itself: `app/engine/__init__.py` eagerly did `from
.pipeline import run`, which pulled in `documents`, `counting`,
`classification`, `pricing`, `sheet`, `tiles`, `title_block`,
`page_frame`, and `pymupdf` the moment anything imported `app.engine` at
all -- so if the API process ever reached any of those, a bug anywhere
in that pipeline (a broken `counting.py`, a missing `pymupdf` wheel)
would stop the API container from booting, not just the engine. The API
never opens a PDF (that's `app/worker`'s job, inside `sandbox.py`'s
sandboxed child process) -- that fact is the actual invariant, and it is
what this test still enforces.

`ingest.py` is the one module that used to risk pulling the pipeline in
by mistake -- see its own `SHEET_KINDS` comment for why it carries a
mirrored copy of `app/engine/sheet_kind.py`'s closed set instead of
importing it.
"""
import os
import subprocess
import sys

# Every module under app/engine/ that touches a PDF (imports pymupdf,
# directly or transitively) or exists only in support of the document
# pipeline -- i.e. everything except the language-side agents
# (conversation, resolve, llm, catalog), their shared contracts, and the
# package's own __init__. Listed by hand rather than derived, so a new
# pipeline module has to be added here deliberately -- the same
# discipline CLAUDE.md asks of the closed sets in schemas.py.
_PDF_PIPELINE_MODULES = (
    "pymupdf",
    "app.engine.pipeline",
    "app.engine.documents",
    "app.engine.counting",
    "app.engine.classification",
    "app.engine.sheet",
    "app.engine.tiles",
    "app.engine.pricing",
    "app.engine.title_block",
    "app.engine.page_frame",
    "app.engine.assemblies",
    "app.engine.context",
    "app.engine.estimate",
    "app.engine.legend",
    "app.engine.regions",
    "app.engine.rows",
    "app.engine.scope",
    "app.engine.sheet_kind",
    "app.engine.__main__",
)


def test_the_api_process_does_not_import_the_pdf_pipeline():
    """A bug in counting.py, or a missing pymupdf wheel, must not stop
    the API container booting. Run in a subprocess so this test's own
    imports don't pollute it."""
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
    imported = eval(out.stdout.strip())  # noqa: S307 -- our own printed list literal
    banned = [m for m in imported if m in _PDF_PIPELINE_MODULES]
    assert not banned, f"app.main pulled in the PDF pipeline: {banned}"


def test_the_api_process_may_import_the_language_side_agents():
    """The converse of the test above, so a future tightening of
    _PDF_PIPELINE_MODULES can't silently start banning the modules
    `POST /items/{id}/resolve` actually needs without a test noticing.
    `app.engine.conversation` and `app.engine.resolve` are imported by
    `app.takeoff.resolve`, reachable from `app.main` through the
    mutations router."""
    code = (
        "import sys; import app.main; "
        "print(sorted(m for m in sys.modules if m.startswith('app.engine')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ},
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    imported = eval(out.stdout.strip())  # noqa: S307 -- our own printed list literal
    assert "app.engine.conversation" in imported
    assert "app.engine.resolve" in imported
