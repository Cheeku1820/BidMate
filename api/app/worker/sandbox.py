"""Every job body runs in a spawned child with a hard timeout. A parser
that hangs or eats memory kills the child; the worker survives and the
job fails with estimator copy. This is the minimum sandbox ROADMAP §2.2
asks for."""
from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import threading
import time

from app.jobs import copy

logger = logging.getLogger(__name__)
GENERIC_TERMINAL = copy.UNREADABLE

Outcome = tuple[str, str]   # ("ok" | "transient" | "terminal" | "timeout", estimator copy)


class Transient(Exception):
    """Retry later: storage, database, or the classification service was unavailable."""


class Terminal(Exception):
    """Do not retry: the message is the estimator-facing reason."""


def _entry(target: str, args: tuple, conn) -> None:
    """Runs in the child. Whatever happens, the parent hears one outcome
    and never an exception class name -- that is logged here and stays
    here."""
    if not logging.getLogger().handlers:   # a spawned child starts with no logging configured
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        module, name = target.rsplit(".", 1)
        getattr(importlib.import_module(module), name)(*args)
        conn.send(("ok", ""))
    except Transient as exc:
        conn.send(("transient", str(exc)))
    except Terminal as exc:
        conn.send(("terminal", str(exc)))
    except Exception as exc:  # noqa: BLE001 -- the class name is logged, never sent
        logger.exception("job body %s%r raised %s", target, args, type(exc).__name__)
        conn.send(("terminal", GENERIC_TERMINAL))
    finally:
        conn.close()


def run_in_child(target: str, args: tuple, timeout: float) -> Outcome:
    """Import `target` (a dotted path) in a fresh child and call it with
    `args`. A child that has not reported by `timeout` is killed."""
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_entry, args=(target, args, child), daemon=True)
    proc.start()
    child.close()
    outcome = _receive(parent, timeout)
    proc.join(1)
    if proc.is_alive():
        # Either the body hung (no outcome: a timeout) or it reported and
        # the process is lingering on the way out (a non-daemon thread,
        # an atexit hook) -- an outcome that arrived is the job's result
        # and is kept; only the process is disposed of.
        proc.kill()
        proc.join(5)
        if outcome is None:
            return ("timeout", "")
    elif outcome is None:
        # The child exited during the join. It may have reported in the
        # window between the poll timing out and its exit; one more look
        # before declaring it died silently (OOM kill, segfault).
        outcome = _receive(parent, 0)
    if outcome is None:
        return ("terminal", GENERIC_TERMINAL)
    return outcome


def _receive(parent, timeout: float) -> Outcome | None:
    if not parent.poll(timeout):
        return None
    try:
        return parent.recv()
    except EOFError:   # the pipe closed without a report
        return None


def _probe(mode: str) -> None:
    """Exists for test_worker_sandbox.py."""
    if mode == "terminal":
        raise Terminal("Couldn't read this file.")
    if mode == "transient":
        raise Transient("storage down")
    if mode == "boom":
        1 / 0
    if mode == "hang":
        time.sleep(60)
    if mode == "linger":   # reports ok, then the process cannot exit: a non-daemon thread is still running
        threading.Thread(target=time.sleep, args=(60,), daemon=False).start()
