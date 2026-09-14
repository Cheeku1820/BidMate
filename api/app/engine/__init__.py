"""The takeoff engine: PDF drawing set -> priced Division 26 takeoff.

Five agents, each one nature (CLAUDE.md): Documents (read the sheets),
Counting (find and count, deterministically), Classification (name what
was found), Pricing (attach cost), and -- not built here yet --
Conversation. The public entry point is `pipeline.run(path)`.
"""

from .pipeline import run

__all__ = ["run"]
