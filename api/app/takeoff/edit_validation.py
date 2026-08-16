"""Input validation for `review.edit_item()`'s `changes` dict, split out
of `review.py` so this task's concurrency additions could land there
without pushing that module further past this project's ~300-line
guideline (task-13b-brief.md: "split rather than extend," the same call
`bulk.py`/`scale.py`/`undo_apply.py`/`concurrency.py` already made).

This is a materially different concern from everything else `review.py`
does: rules a field's JSON type alone can't express (an empty category is
semantically "no category," a quantity string that parses but overflows
`Numeric(12, 2)`), not the review-state-transition rules `review.py`
itself enforces. Nothing here touches a row, locks anything, or knows
about `Item.version` -- it validates a plain dict before `review.py` ever
reaches the database.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.errors import DomainError

# The only fields a generic edit may touch. Status changes go through
# approve/reject/unreject instead, so "status" is deliberately absent --
# a caller trying to smuggle a status change through edit_item() gets
# refused here rather than silently bypassing the approval rule.
EDITABLE_FIELDS = {"system", "category", "quantity", "notes", "symbol"}

# Fields that must be non-empty, non-null text -- an empty string is not
# a real value for any of these, and letting one through would (for
# category, concretely) satisfy the "no longer unclassified" check in
# review.py and silently promote a Needs attention item to Ready to
# review.
REQUIRED_TEXT_FIELDS = {"system", "category", "symbol"}

# The largest magnitude Item.quantity (Numeric(12, 2)) can actually
# store: 12 total digits, 2 after the decimal point, so 10 before it.
# Decimal.is_finite() alone lets "1E+15" through -- finite, positive, and
# still too large by ten orders of magnitude -- and the failure then
# surfaces as a bare psycopg numeric field overflow at flush, with no
# recovery copy. Checking the bound here turns that into the same
# DomainError every other refused edit produces.
MAX_QUANTITY = Decimal("9999999999.99")


def validate_edit(changes: dict) -> None:
    """Rules a field's JSON type alone can't express, so they live here
    rather than at the API boundary. An empty category is semantically
    "no category," not a valid one, and a Pydantic string field can't
    know that distinction -- it has to be a service-level rule.
    """
    for field in REQUIRED_TEXT_FIELDS & changes.keys():
        value = changes[field]
        if not isinstance(value, str) or not value.strip():
            raise DomainError(
                "field_cannot_be_empty",
                f"{field.capitalize()} cannot be blank. Enter a value before saving this edit.",
            )

    if "notes" in changes and changes["notes"] is None:
        raise DomainError(
            "field_cannot_be_empty",
            "Notes cannot be removed entirely. Send an empty value instead of no value, to clear it.",
        )

    if "quantity" in changes:
        try:
            parsed = Decimal(str(changes["quantity"]))
        except (InvalidOperation, ValueError, TypeError):
            raise DomainError(
                "invalid_quantity",
                "Quantity must be a number, such as 14 or 3.5. Correct it and save the edit again.",
            )
        # Decimal("NaN") / Decimal("Infinity") / Decimal("-Infinity") all
        # parse without raising, and Postgres numeric happily stores NaN
        # -- one edit like that poisons every SUM downstream, which is
        # exactly the drawer total and export figure a contractor bids
        # off. is_finite() rejects NaN and both infinities in one check.
        # A quantity is also a count or a measured length, and there is
        # no such thing as a negative one -- but zero is a legitimate
        # intermediate state (an item counted at zero while a run is
        # still being traced, say), so it stays accepted and the copy
        # says "cannot be negative" rather than "must be positive."
        if not parsed.is_finite() or parsed < 0:
            raise DomainError(
                "invalid_quantity",
                "Quantity cannot be negative. Enter zero or a positive number, such as 14 or 3.5.",
            )
        # is_finite() lets "1E+15" through -- finite, non-negative, and
        # still ten orders of magnitude past what Item.quantity
        # (Numeric(12, 2)) can store. Left unchecked, that value passes
        # every validator here and fails only at flush, as a bare
        # psycopg numeric field overflow with no recovery copy.
        if parsed > MAX_QUANTITY:
            raise DomainError(
                "invalid_quantity",
                f"Quantity must be {MAX_QUANTITY:,} or less. Correct it and save the edit again.",
            )
        # Item.quantity is Numeric(12, 2) -- at most two digits after the
        # decimal point. Postgres would round a third-decimal-place value
        # silently on write, and SessionLocal's expire_on_commit=False
        # means a mutation response built right after would echo back
        # the value this function was handed (184.559), not what landed
        # in the row (184.56) -- a review finding. Refusing here keeps
        # the rounding decision with the person, not Postgres or a lossy
        # JSON round-trip. as_tuple().exponent is an int by this point --
        # is_finite() above already ruled out NaN/Infinity, whose
        # exponent is a sentinel string ('n'/'N'/'F'), not a digit count.
        if parsed.as_tuple().exponent < -2:
            rounded = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            raise DomainError(
                "invalid_quantity",
                f"Quantity supports two decimal places. Round to {rounded} and save again.",
            )
