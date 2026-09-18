/* The empty state's three starter questions per screen, from the spec.
   Each is a real question the context for that screen can answer. */

const QUESTIONS = {
  overview: ["What stage is this project at?", "What's left before export?", "When is the bid due?"],
  documents: ["What have I uploaded so far?", "Which files failed and why?", "What should I upload first?"],
  confirm: ["What does the scope say is excluded?", "Which sheets have no scale?", "What's in the spec about fixtures?"],
  processing: ["What's still running?", "Which sheets need attention?", "Can I start reviewing yet?"],
  takeoff: ["What's blocking export on this sheet?", "What do the warnings on this sheet say?", "What's on the luminaire schedule?"],
  spreadsheet: ["What's blocking export on this sheet?", "What do the warnings on this sheet say?", "What's on the luminaire schedule?"],
  notes: ["Which notes are used in the estimate?", "Are any notes waiting to be applied?", "What did I note about scope?"],
  labor: ["Where does the labor rate come from?", "Which system costs the most?", "What's the material factor based on?"],
  pricing: ["Where does the labor rate come from?", "Which system costs the most?", "What's the material factor based on?"],
  export: ["What's still blocking export?", "What allowances are acknowledged?", "What's excluded from scope?"],
  settings: ["What revision set is active?", "Which settings override company defaults?", "What's the project address?"],
};

export function exampleQuestions(name) {
  return QUESTIONS[name] ?? [];
}
