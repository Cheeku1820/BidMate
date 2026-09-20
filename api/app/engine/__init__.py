"""The takeoff engine: PDF drawing set -> priced Division 26 takeoff.

Five agents, each one nature (CLAUDE.md): Documents (read the sheets),
Counting (find and count, deterministically), Classification (name what
was found), Pricing (attach cost), and Conversation (route an utterance
to a typed proposal). The public entry point for the whole pipeline is
`pipeline.run(path)`.

This package must stay importable without pulling in `pipeline` (and
through it `pymupdf`, the vision call, and the rest of the document
pipeline) merely because something imported a lighter submodule.
`app.takeoff.resolve` imports `app.engine.conversation`,
`app.engine.resolve`, and `app.engine.catalog` from inside the API
process -- `POST /items/{id}/resolve` makes a live classification call
synchronously from the request handler (say-what-it-is spec) -- and
Python runs this file before any submodule import.

The boundary `test_api_import_boundary.py` guards is not "the API
process never imports app.engine" -- it is narrower and more precise:
the API may import the language-side agents (`conversation`, `resolve`,
`llm`, `catalog`), which read already-extracted text and open no file,
but never the document/PDF pipeline (`documents`, `counting`,
`classification`, `pricing`, `sheet`, `tiles`, `title_block`,
`page_frame`, and `pymupdf` itself). A bug in `counting.py`, or a
missing `pymupdf` wheel, must stay a worker problem, never an
API-process-won't-boot problem -- the API never opens a PDF; the worker
does that inside `sandbox.py`'s sandboxed child process. `run` is still
reachable as `app.engine.run` -- `python -m app.engine` (`__main__.py`)
imports `pipeline` itself rather than relying on this -- but only loads
`pipeline` if something actually asks for it, which is what keeps
importing this package at all cheap enough for the API process to do.
"""


def __getattr__(name: str):
    if name == "run":
        from .pipeline import run

        return run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["run"]
