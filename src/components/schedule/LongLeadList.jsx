/* ============================================================
   LongLeadList.jsx — every flagged item and what is known about its
   lead time.

   A number of weeks appears only when a row carries one: a supplier's
   quote, the estimator's own dated entry, or the firm's table. With
   none of those the row says so and draws no order-by date, because a
   date counted back from a lead time nobody quoted is exactly the
   confident wrong number this product exists to prevent.

   The item's own status renders through Pill — that is an item, and
   the four labels belong to it. The lead time's source is a tier tag.
   ============================================================ */

import { useState } from "react";
import Pill from "../Pill.jsx";
import { COPY } from "./scheduleCopy.js";
import { STAGES, stageLabel } from "./stages.js";

function shortDate(iso) {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function LeadTimeForm({ lead, onSave, onCancel }) {
  const [weeks, setWeeks] = useState(lead.leadWeeks == null ? "" : String(lead.leadWeeks));
  const [who, setWho] = useState(lead.source === "estimator" ? lead.sourceLabel : "");
  const [when, setWhen] = useState(today());

  return (
    <form
      className="lead-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ leadWeeks: Number(weeks), sourceLabel: who.trim(), quotedAt: when });
      }}
    >
      <label>
        {COPY.weeks}
        <input
          type="text"
          inputMode="numeric"
          className="tabular"
          value={weeks}
          onChange={(event) => setWeeks(event.target.value.replace(/\D/g, ""))}
        />
      </label>
      <label>
        {COPY.whoSaidSo}
        <input type="text" value={who} onChange={(event) => setWho(event.target.value)} />
      </label>
      <label>
        {COPY.quotedOn}
        <input type="date" value={when} onChange={(event) => setWhen(event.target.value)} />
      </label>
      <button type="submit" className="btn btn--primary" disabled={!weeks || !who.trim()}>
        {COPY.saveLeadTime}
      </button>
      <button type="button" className="btn" onClick={onCancel}>{COPY.dismiss}</button>
    </form>
  );
}

export default function LongLeadList({ schedule, items, onLeadTime }) {
  const [editing, setEditing] = useState(null);
  const [query, setQuery] = useState("");
  const flagged = new Set(schedule.leads.map((lead) => lead.itemId));
  const matches =
    query.trim().length >= 2
      ? items
          .filter((item) => !flagged.has(item.id) && item.name.toLowerCase().includes(query.toLowerCase()))
          .slice(0, 8)
      : [];

  return (
    <section className="long-lead" aria-label={COPY.longLead}>
      <h2>{COPY.longLead}</h2>

      {schedule.leads.length === 0 ? (
        <p className="muted">No long-lead items on this project yet.</p>
      ) : (
        <table className="long-lead__table">
          <thead>
            <tr>
              <th scope="col">Item</th>
              {schedule.multiPhase ? <th scope="col">{COPY.phaseField}</th> : null}
              <th scope="col">Status</th>
              <th scope="col">Lead time</th>
              <th scope="col">{COPY.neededFor}</th>
              <th scope="col">{COPY.orderBy}</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {schedule.leads.map((lead) => (
              <tr key={lead.itemId} className={lead.passed ? "long-lead__row--passed" : undefined}>
                <td>{lead.itemName}</td>
                {schedule.multiPhase ? <td>{lead.phaseName}</td> : null}
                <td><Pill status={lead.itemStatus} /></td>
                <td className="tabular">
                  {lead.leadWeeks == null ? (
                    <>
                      <span className="muted">{COPY.notYetQuoted}</span>
                      <div className="muted small">{COPY.notYetQuotedFix}</div>
                    </>
                  ) : (
                    <>
                      {lead.leadWeeks} wk{" "}
                      <span className="tier-tag">
                        {COPY.sourceTag(lead.source, lead.sourceLabel, shortDate(lead.quotedAt))}
                      </span>
                    </>
                  )}
                  {lead.warning ? (
                    <details className="warning-details">
                      <summary>{lead.warning.title}</summary>
                      <p>{lead.warning.found}</p>
                      <p>{lead.warning.why}</p>
                      <p>{lead.warning.fix}</p>
                      <p className="muted">{lead.warning.where}</p>
                    </details>
                  ) : null}
                  {editing === lead.itemId ? (
                    <LeadTimeForm
                      lead={lead}
                      onSave={(values) => {
                        onLeadTime(lead.itemId, values);
                        setEditing(null);
                      }}
                      onCancel={() => setEditing(null)}
                    />
                  ) : null}
                </td>
                <td>
                  <select
                    aria-label={`${COPY.neededFor} ${lead.itemName}`}
                    value={lead.neededForStage}
                    onChange={(event) => onLeadTime(lead.itemId, { neededForStage: event.target.value })}
                  >
                    {STAGES.map((stage) => (
                      <option key={stage} value={stage}>{stageLabel(stage)}</option>
                    ))}
                  </select>
                </td>
                <td className="tabular">
                  {lead.orderBy ? (
                    <>
                      {shortDate(lead.orderBy)}
                      {lead.passed ? <div className="small error-text">{lead.note}</div> : null}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <button type="button" className="link" onClick={() => setEditing(lead.itemId)}>
                    {COPY.typeLeadTime}
                  </button>
                  {lead.leadWeeks != null && lead.source === "estimator" ? (
                    <button type="button" className="link" onClick={() => onLeadTime(lead.itemId, { leadWeeks: null })}>
                      {COPY.clear}
                    </button>
                  ) : null}
                  <button type="button" className="link" onClick={() => onLeadTime(lead.itemId, { flagged: false })}>
                    {COPY.unflagLongLead}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <label className="long-lead__search">
        {COPY.flagLongLead}
        <input
          type="search"
          aria-label={COPY.flagLongLead}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {matches.length ? (
        <ul className="long-lead__matches">
          {matches.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="link"
                onClick={() => {
                  onLeadTime(item.id, { flagged: true });
                  setQuery("");
                }}
              >
                {item.name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
