/* ============================================================
   ConfidenceBar.jsx — how much an estimator should trust one line,
   1 to 10, drawn as ten steps.

   docs/specs/estimate-without-asking.md, "The confidence scale". This
   is the one place in the product where a confidence figure renders,
   by the estimator's explicit decision against a stated objection, and
   two things are what make it admissible rather than a violation of
   `product-spec.md` §3:

   1. **It explains itself.** The score is a sum of named reasons
      (api/app/takeoff/confidence.py), and those sentences are in the
      accessible label and the tooltip. An unexplained figure is what
      the spec bans; this one can always answer "why is this a 4".
   2. **It is a meter, not a probability.** "4 out of 10", never
      "40%". A percentage is a number an estimator could multiply by
      the total, which is the anti-goal the spec names second.

   The estimator chose a bar over a digit, which moves the entire text
   channel into the label — CLAUDE.md requires a text alternative for
   every status channel and forbids conveying anything by colour or
   shape alone, so the label carries the number *and* the reasons. A bar
   with a bare "4" label would be decoration.

   Deliberately NOT painted in a review-status hue. The meter is a third
   axis, like counted/assumed, and `--amber` belongs to *Needs
   attention* — see src/components/estimate/originColors.test.js, which
   guards the same rule for the origin tags.
   ============================================================ */

const STEPS = 10;

export default function ConfidenceBar({ value, reasons }) {
  const scored = Number.isFinite(value) && value > 0;
  // Clamped rather than trusted: the API closes the range too
  // (`ck_items_confidence`), and a bar drawn past its own end is worse
  // than a clamped one.
  const filled = scored ? Math.max(0, Math.min(STEPS, Math.round(value))) : 0;

  const label = scored
    ? [`Confidence ${filled} out of 10`, ...(reasons || [])].join(". ")
    : "Confidence not scored yet. This line was processed before scoring existed; the next run will score it.";

  return (
    <span
      className={`conf-bar${scored ? "" : " conf-bar--unscored"}`}
      role="img"
      aria-label={label}
      // The same sentence for a sighted mouse user. The digit lives
      // here and in the label and nowhere else, which is what the
      // estimator asked for.
      title={label}
    >
      {Array.from({ length: STEPS }, (_, i) => (
        <span key={i} className={`conf-step${i < filled ? " conf-step--on" : ""}`} />
      ))}
    </span>
  );
}
