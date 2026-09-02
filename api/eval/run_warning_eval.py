"""Run the grounded-warnings eval set against the current prompt in
app/engine/llm.py, and print per-criterion pass rates.

Usage (from api/, with ANTHROPIC_API_KEY set):
    python -m eval.run_warning_eval

This is a development-time gate, not a CI test: it makes real API calls
(one classification call plus one judge call per non-"ready" item), and
its purpose is to compare quality across a prompt change -- run it before
and after editing app/engine/llm.py's _prompt(), and read the diff in
pass rates, not just whether it printed 100%.

Before trusting the printed rates: grade 15-20 warnings by hand and
check them against the judge's verdicts (design doc section D,
"Calibration"). If they disagree, fix the rubric wording in rubric.py --
don't override the judge's score case by case.
"""

from __future__ import annotations

import sys

from app.engine import llm
from eval.rubric import CRITERIA, grade
from eval.warning_eval_cases import CASES


def main() -> int:
    if not llm.available():
        print("ANTHROPIC_API_KEY is not set -- this eval makes real model calls and needs it.")
        return 1

    totals = {c: [0, 0] for c in CRITERIA}  # criterion -> [passes, total]
    warned = 0

    for case in CASES:
        try:
            result = llm.estimate(case["tags"], case["schedule_text"], case["location"])
        except Exception as exc:  # noqa: BLE001 -- report and keep going
            print(f"[{case['id']}] classification call failed: {exc}")
            continue

        for item in result.get("items", []):
            warning = item.get("warning")
            # Reported on its own line, deliberately outside the pass-rate
            # totals: a warning firing where none belongs is a regression
            # in WHETHER a warning fires, not in the quality of one that
            # did, and averaging the two together hides both.
            if warning is not None and not case.get("expect_warning", True):
                print(f"[{case['id']}] tag {item.get('tag')}: expected no warning, but one was generated")
            if not warning:
                continue
            try:
                verdict = grade(case["tags"], case["schedule_text"], warning)
            except Exception as exc:  # noqa: BLE001 -- one bad judge call must not stop the run
                print(f"[{case['id']}] tag {item.get('tag')}: judge call failed: {exc}")
                continue
            # Counted only once a verdict actually exists, so the printed
            # total never overstates how many warnings were graded.
            warned += 1
            print(f"[{case['id']}] tag {item.get('tag')}: {verdict}")
            for c in CRITERIA:
                totals[c][1] += 1
                if verdict[c] == "pass":
                    totals[c][0] += 1

    print(f"\n{warned} warnings graded across {len(CASES)} cases.\n")
    for c in CRITERIA:
        passes, total = totals[c]
        rate = f"{passes}/{total}" if total else "no warnings graded"
        print(f"  {c}: {rate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
