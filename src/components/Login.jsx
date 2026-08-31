import { useState } from "react";
import { login } from "../lib/store/api.js";

/* ============================================================
   Login.jsx — the sign-in gate (task-16-brief.md, Step 5). App.jsx
   renders Login whenever the store's me() rejects with not_signed_in.

   Plain email/password, persistent visible labels, error copy adjacent
   to the fields (DESIGN.md) rather than a toast or a dialog, sentence
   case, no "please" (CLAUDE.md). Nothing here mentions models,
   confidence, or processing internals — this is a sign-in form, not a
   place that needed that rule, but the same product-language
   discipline applies everywhere.
   ============================================================ */

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const user = await login(email.trim(), password);
      onSignedIn(user);
    } catch (err) {
      setError(err?.message || "Sign-in failed. Check what you entered and try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={handleSubmit}>
        <h1 className="login__title">Takeoff review</h1>
        <p className="login__subtitle">Sign in to review this project's Division 26 takeoff.</p>

        <label className="label" htmlFor="login-email">Email</label>
        <input
          id="login-email"
          className="field"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          aria-invalid={error ? "true" : undefined}
        />

        <label className="label" htmlFor="login-password">Password</label>
        <input
          id="login-password"
          className="field"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          aria-invalid={error ? "true" : undefined}
        />

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}

        <button className="btn btn--primary btn--block" type="submit" disabled={submitting} style={{ marginTop: 16 }}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
