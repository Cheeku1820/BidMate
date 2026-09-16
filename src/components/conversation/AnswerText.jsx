/* ============================================================
   AnswerText.jsx — an answer, rendered.

   Paragraphs, "- " lists, bold, italic. That is the whole grammar the
   prompt allows the answer to use, so that is the whole grammar this
   renders -- no headings, tables, code, links, or raw HTML. Text is
   only ever placed as text nodes; nothing from the model reaches
   innerHTML.
   ============================================================ */

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;

function inline(text, keyBase) {
  return text.split(INLINE).map((part, n) => {
    const key = `${keyBase}-${n}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={key}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export default function AnswerText({ text }) {
  const blocks = (text ?? "").split(/\n\s*\n/).filter((b) => b.trim());
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split("\n");
        if (lines.every((l) => l.startsWith("- "))) {
          return (
            <ul key={b}>
              {lines.map((l, n) => <li key={n}>{inline(l.slice(2), `${b}-${n}`)}</li>)}
            </ul>
          );
        }
        return <p key={b}>{inline(block, `${b}`)}</p>;
      })}
    </>
  );
}
