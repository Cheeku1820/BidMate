"""The ROM estimate: what the documents said, what had to be assumed.

docs/specs/rom-estimate.md. This package holds the assumption record,
the generators that produce one per section, the budget range they
imply, and the assembly the Estimate summary workspace reads.

Nothing here opens a file. Generation runs inside `app.worker`, which
is the only process that parses a PDF; this package is importable from
both the API and the worker, and `tests/test_api_import_boundary.py`
is what keeps that true.
"""
