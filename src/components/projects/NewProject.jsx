/* ============================================================
   NewProject.jsx — spec §6.1's guided form.

   Single column, persistent visible labels, and only the fields the spec
   names. Labor and pricing settings are deliberately absent: the spec
   excludes them, and every field here is one an estimator has to answer
   before they can start the work they came to do.
   ============================================================ */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";

const CONSTRUCTION_TYPES = [
  "Not sure",
  "Warehouse or distribution",
  "Office",
  "Healthcare",
  "Education",
  "Multifamily",
  "Industrial",
  "Retail",
];

export default function NewProject({ store }) {
  const navigate = useNavigate();
  const [values, setValues] = useState({
    name: "",
    number: "",
    customer: "",
    location: "",
    bidDueDate: "",
    constructionType: "Not sure",
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (key) => (event) => setValues({ ...values, [key]: event.target.value });

  async function onSubmit(event) {
    event.preventDefault();

    const errors = {};
    if (!values.name.trim()) errors.name = "Enter a project name.";
    if (!values.location.trim()) errors.location = "Enter a project address.";
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await store.createProject({
        name: values.name.trim(),
        location: values.location.trim(),
        number: values.number.trim(),
        customer: values.customer.trim(),
        bidDueDate: values.bidDueDate || null,
        // Collected above (the <select>) but was silently dropped here --
        // the estimator typed a value and it vanished with no trace.
        // ProjectCreateIn.construction_type (schemas.py) already accepts
        // and ignores it, by design, until a real column lands.
        constructionType: values.constructionType,
      });
      navigate(`/projects/${created.id}`);
    } catch (err) {
      // Values stay in the form. A failed submit that clears the form is
      // how an estimator stops trusting the tool in the first thirty
      // seconds (this task's brief) -- and the copy names a recovery
      // action rather than only reporting failure.
      setSubmitError(err?.message || "The project couldn't be created. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopBar title="New project" subtitle="Step 1 of 6 · Project details" />

      <div className="page page-narrow">
        <h1 className="page-heading">New project</h1>

        {submitError ? (
          <div className="warncard warncard--missing" role="alert">
            <p>{submitError}</p>
          </div>
        ) : null}

        <form className="form-column" onSubmit={onSubmit} noValidate>
          <Field
            id="project-name"
            label="Project name"
            required
            value={values.name}
            onChange={set("name")}
            error={fieldErrors.name}
          />
          <Field
            id="project-number"
            label="Internal number"
            hint="Your own job number, if you use one."
            value={values.number}
            onChange={set("number")}
          />
          <Field
            id="project-customer"
            label="Customer or general contractor"
            value={values.customer}
            onChange={set("customer")}
          />
          <Field
            id="project-location"
            label="Project address"
            required
            hint="Used to apply regional labor and pricing."
            value={values.location}
            onChange={set("location")}
            error={fieldErrors.location}
          />
          <Field
            id="project-bid-date"
            label="Bid due date"
            type="date"
            value={values.bidDueDate}
            onChange={set("bidDueDate")}
          />

          <div className="formfield">
            <label className="formfield-label" htmlFor="project-type">
              Construction type
            </label>
            <select
              id="project-type"
              className="field"
              value={values.constructionType}
              onChange={set("constructionType")}
            >
              {CONSTRUCTION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? "Creating…" : "Create project"}
            </button>
            <Link className="btn" to="/projects">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </>
  );
}

function Field({ id, label, hint, error, required, type = "text", value, onChange }) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="formfield">
      <label className="formfield-label" htmlFor={id}>
        {label}
        {required ? <span className="formfield-required"> (required)</span> : null}
      </label>
      {hint ? (
        <p className="formfield-hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      <input
        id={id}
        className={error ? "field field--error" : "field"}
        type={type}
        value={value}
        onChange={onChange}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        aria-invalid={error ? "true" : undefined}
      />
      {/* The error message sits adjacent to the field it belongs to,
          rather than in a summary elsewhere. */}
      {error ? (
        <p className="formfield-error" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
