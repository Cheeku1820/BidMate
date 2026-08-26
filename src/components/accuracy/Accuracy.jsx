/* ============================================================
   Accuracy.jsx — spec §5 screen I.

   Compares the platform takeoff against an estimator-approved reference.
   That reference is a benchmark corpus that does not exist yet
   (ROADMAP.md 3.4: "Without it, accuracy claims are unsupportable and
   the screen cannot ship"), so the honest state today is that there is
   nothing to compare against -- shown as a named empty state that
   explains what builds the benchmark (spreadsheet import at project
   start), not a fabricated 95% badge.

   The structure the screen will carry is laid out so its shape is legible
   (spec §5 I sections), and the one rule that outlives the empty state is
   stated where it will apply: every figure shows its sample size, and no
   accuracy badge appears unless its category and cohort passed the
   defined threshold (spec §5 I).
   ============================================================ */

import { Link } from "react-router-dom";
import { Target } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";

const SECTIONS = [
  "Count accuracy by category",
  "Length variance by system",
  "Missing items",
  "Incorrect additions",
  "Review time vs. manual baseline",
  "Drawing conditions and known limitations",
];

export default function Accuracy() {
  return (
    <>
      <AppTopBar title="Accuracy" />

      <div className="page">
        <h1 className="page-heading">Accuracy comparison</h1>
        <p className="muted">
          Compare a completed takeoff against an estimator-approved reference, by category and by system.
        </p>

        <div className="empty-state">
          <Target aria-hidden="true" size={28} />
          <h2>No benchmark set yet</h2>
          <p>
            Accuracy is measured against takeoffs a person has approved. Import a finished takeoff at the start of a
            project — its drawings plus the estimator's own numbers — and it becomes the reference this screen compares
            against. Until at least one exists, there is nothing to measure, and a single headline percentage would say
            more than the data supports.
          </p>
          <Link className="btn btn--primary" to="/projects">
            Back to projects
          </Link>
        </div>

        <section className="card">
          <h2>What this will show</h2>
          <p className="muted">
            Once a benchmark set exists, each figure carries its sample size, and no accuracy badge appears for a
            category until that category and cohort clear the defined threshold.
          </p>
          <ul className="plain-list">
            {SECTIONS.map((section) => (
              <li key={section}>{section}</li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
