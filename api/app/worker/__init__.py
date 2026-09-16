"""The worker: the only process that opens a PDF. `python -m app.worker`
polls the jobs table and runs each job in a spawned child with a hard
timeout. Nothing here is imported by the API, and nothing here imports
the API (test_worker_import_boundary.py)."""

# Job.requested_by is a foreign key to users.id. The API process always
# has the identity models loaded (every router imports them); the worker
# process, on its own, never did -- so the first query against `jobs`
# in `python -m app.worker` raised NoReferencedTableError before a
# single job could be claimed. Registering the table here covers the
# polling parent and the spawned child both, since each imports
# something under this package. A model module, not a router:
# test_worker_import_boundary.py still holds.
import app.identity.models  # noqa: E402, F401
