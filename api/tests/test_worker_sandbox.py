"""Every job body runs in a spawned child with a hard timeout. The parent
learns one of four outcomes and never an exception class name."""
from app.jobs import copy
from app.worker import sandbox


def test_ok_outcome():
    assert sandbox.run_in_child("app.worker.sandbox._probe", ("ok",), timeout=10) == ("ok", "")


def test_terminal_and_transient_carry_their_copy():
    assert sandbox.run_in_child("app.worker.sandbox._probe", ("terminal",), timeout=10) == ("terminal", "Couldn't read this file.")
    assert sandbox.run_in_child("app.worker.sandbox._probe", ("transient",), timeout=10) == ("transient", "storage down")


def test_an_unexpected_exception_is_terminal_without_its_class_name():
    kind, msg = sandbox.run_in_child("app.worker.sandbox._probe", ("boom",), timeout=10)
    assert kind == "terminal" and "ZeroDivisionError" not in msg and msg


def test_a_hung_child_is_killed():
    kind, _ = sandbox.run_in_child("app.worker.sandbox._probe", ("hang",), timeout=1)
    assert kind == "timeout"


def test_the_generic_terminal_copy_is_the_shared_unreadable_string():
    assert sandbox.GENERIC_TERMINAL == copy.UNREADABLE


def test_a_child_that_reports_then_lingers_keeps_its_outcome():
    """The body finished and said so; a process that will not exit
    afterwards is disposed of, not mistaken for a hung job."""
    assert sandbox.run_in_child("app.worker.sandbox._probe", ("linger",), timeout=10) == ("ok", "")
