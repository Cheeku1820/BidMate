"""The takeoff engine: PDF drawing set -> priced Division 26 takeoff.

Five agents, each one nature (CLAUDE.md): Documents (read the sheets),
Counting (find and count, deterministically), Classification (name what
was found), Pricing (attach cost), and Conversation (route an utterance
to a typed proposal). The public entry point for the whole pipeline is
`pipeline.run(path)`.

This package must stay importable without pulling in `pipeline` (and
through it `pymupdf`, the vision call, and the rest of the document
pipeline) merely because something imported a lighter submodule --
`app.takeoff.resolve` imports `app.engine.conversation`,
`app.engine.resolve`, and `app.engine.catalog` from inside the API
process, and Python runs this file before any submodule import.
`test_api_import_boundary.py` guards the invariant this exists to
protect: `app.main` must never import the engine's heavy pipeline, so a
bug in `counting.py` or a missing `pymupdf` wheel is a worker problem,
never an API-process-won't-boot problem. `run` is still reachable as
`app.engine.run` -- `python -m app.engine` (`__main__.py`) imports
`pipeline` itself rather than relying on this -- but only loads
`pipeline` if something actually asks for it.
"""


def __getattr__(name: str):
    if name == "run":
        from .pipeline import run

        return run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["run"]
