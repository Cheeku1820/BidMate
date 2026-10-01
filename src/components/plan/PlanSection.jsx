/* One section of the plan: a heading, one sentence, and either the
   lines or the sentence that says there are none. Every section stays
   on the page when empty so the shape of the plan is visible even when
   most of it is -- the scanned-set case. */

export default function PlanSection({ id, title, description, emptyText, children, footer = null }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : [];
  return (
    <section className="scope-card plan-section" aria-labelledby={id}>
      <header className="scope-head">
        <h2 id={id}>{title}</h2>
        {description ? <p className="muted">{description}</p> : null}
      </header>
      {items.length === 0 ? <p className="muted scope-state">{emptyText}</p> : <ul className="scope-list">{items}</ul>}
      {footer}
    </section>
  );
}
