"""The estimator-facing words for every line this product guessed.

Sibling of `app/estimate/copy.py`, same discipline and same register:
one voice for the whole document, held in one file, so a new completion
case cannot quietly introduce a second. Nothing here names a model, a
processing stage, or a percentage of trust.

These lines carry a harder job than the rest of the ROM's copy. An
assumption beside a total says "this number rests on something"; a
completion line says "**this number is money we added that nobody
counted.**" The licence to do that at all comes entirely from saying so
plainly, which is why every case answers the same four questions a
warning answers -- what was found, why it matters, what to check, and
where the evidence lives.

Sentence case. No exclamation marks, no "please", no "successfully".
"""
from __future__ import annotations

# Case 1 -- a cluster counted but never identified. The most common gap
# and the only one where the quantity is solid and the money is not.
UNIDENTIFIED = {
    "name": "Allowance — unidentified devices on {sheet}",
    "title": "Devices counted on {sheet} with no price",
    "found": (
        "{devices} were counted on {sheet}, but nothing on the set named what they are, "
        "so none of them carry a price."
    ),
    "why": (
        "Without this allowance those devices would sit in the takeoff at nothing, "
        "and the estimate would read as if that part of the sheet were free."
    ),
    "fix": (
        "Open {sheet}, say what the symbol is on the item panel, and this allowance "
        "drops away in favour of the real price."
    ),
    "where": "{sheet}, and the legend or schedule that should define the symbol",
}

# Case 2 -- measured runs on a sheet with no confirmed scale. The sheet's
# scale is deliberately NOT written: a stored scale is indistinguishable
# from a confirmed one, and writing it would release every blocked item
# on the sheet.
UNSCALED = {
    "name": "Allowance — measured runs on {sheet}, scale unconfirmed",
    "title": "Measured runs on {sheet} with no confirmed scale",
    "found": (
        "{lines} on {sheet} were measured off the drawing, but the sheet has no single "
        "confirmed scale, so the lengths cannot be converted with confidence."
    ),
    "why": (
        "Wire and conduit are a large share of material cost. Leaving these runs out "
        "of the number would understate the job by whatever that footage is worth."
    ),
    "fix": (
        "Set or calibrate the scale on {sheet}. The measured lines are still marked "
        "Missing information and still block the export until somebody does."
    ),
    "where": "{sheet} title block, and the enlarged plan notes",
}

# Case 3 -- a sheet counted far below its siblings.
THIN = {
    "name": "Allowance — shortfall against the other sheets on {sheet}",
    "title": "{sheet} counted well below the other sheets",
    "found": (
        "{sheet} counted {counted} where the other plan sheets on this set typically "
        "carry {median}. This allowance covers the {shortfall} difference."
    ),
    "why": (
        "A sheet that read thin looks finished and is not. Counting it as drawn would "
        "quietly remove that work from the estimate."
    ),
    "fix": (
        "Open {sheet} and check whether the devices are really there. If the sheet is "
        "genuinely sparse, delete this allowance."
    ),
    "where": "{sheet}, compared against {sheets}",
}

# Case 4 -- a plan sheet that produced nothing at all. The thin case with
# a count of zero, so it shares the whole calculation.
EMPTY = {
    "name": "Allowance — nothing counted on {sheet}",
    "title": "Nothing was counted on {sheet}",
    "found": (
        "{sheet} is an electrical plan sheet and no devices were counted on it at all. "
        "This allowance assumes it carries about what the other plan sheets do, {median}."
    ),
    "why": (
        "A sheet with nothing on it is indistinguishable from a sheet that costs nothing. "
        "Silence reads as completeness, and that is the one way this estimate can be "
        "badly wrong without looking wrong."
    ),
    "fix": (
        "Open {sheet}. If it carries no Division 26 work, delete this allowance; if it "
        "does, say what is on it and the real count replaces this."
    ),
    "where": "{sheet}, compared against {sheets}",
}

# Case 5 -- a system a job of this kind carries and this one never found.
# The weakest rung, and the copy says so.
SYSTEM = {
    "name": "Allowance — {system}, nothing found on the drawings",
    "title": "No {system} work was found on this set",
    "found": "{evidence}",
    "why": (
        "A job of this kind normally carries {system} work. Leaving it out entirely "
        "would hand over a number for a smaller job than the one being bid."
    ),
    "fix": (
        "Check whether {system} is this contractor's scope. If another trade carries it, "
        "say so on the scope list and this allowance comes out of the number."
    ),
    "where": (
        "No sheet counted this work, so this line is attached to {sheet} as a nominal "
        "location rather than a place it was read from. {basis}"
    ),
}

# The three strengths of evidence a system allowance can rest on, in the
# spec's own order -- strongest first. The third is the weakest thing
# this product is willing to guess from, and it has to say so on the
# line rather than reading like the other two.
SYSTEM_EVIDENCE_DOCUMENT = (
    "The documents name {system} work — \"{quote}\" — and no {system} devices "
    "were counted anywhere on the set."
)
SYSTEM_EVIDENCE_BUILDING_TYPE = (
    "No {system} devices were counted anywhere on the set. {reading}"
)

SYSTEM_BASIS_DOCUMENT = "The amount is a share of the {system} work typical for this kind of job."
SYSTEM_BASIS_BUILDING_TYPE = (
    "Nothing on the drawings asked for this line — it rests on the kind of building "
    "alone, which is the weakest basis on this document."
)


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
