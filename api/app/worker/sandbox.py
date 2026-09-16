"""Every job body runs in a spawned child with a hard timeout. A parser
that hangs or eats memory kills the child; the worker survives and the
job fails with estimator copy. This is the minimum sandbox ROADMAP §2.2
asks for."""
from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
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
    try:
        module, name = target.rsplit(".", 1)
        getattr(importlib.import_module(module), name)(*args)
        conn.send(("ok", ""))
    except Transient as exc:
        conn.send(("transient", str(exc)))
    except Terminal as exc:
        conn.send(("terminal", str(exc)))
    except Exception as exc:  # noqa: BLE001 -- the class name is logged, never sent
        logger.exception("job body raised %s", type(exc).__name__)
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
    outcome: Outcome | None = None
    if parent.poll(timeout):
        try:
            outcome = parent.recv()
        except EOFError:
            outcome = None
    proc.join(1)
    if proc.is_alive():
        proc.kill()
        proc.join(5)
        return ("timeout", "")
    if outcome is None:  # the child died without reporting (OOM kill, segfault)
        return ("terminal", GENERIC_TERMINAL)
    return outcome


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
