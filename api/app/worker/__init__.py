"""The worker: the only process that opens a PDF. `python -m app.worker`
polls the jobs table and runs each job in a spawned child with a hard
timeout. Nothing here is imported by the API, and nothing here imports
the API (test_worker_import_boundary.py)."""
