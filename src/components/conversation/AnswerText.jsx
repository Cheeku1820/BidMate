/* ============================================================
   AnswerText.jsx — an answer, rendered.

   Paragraphs, "- " lists, bold, italic. That is the whole grammar the
   prompt allows the answer to use, so that is the whole grammar this
   renders -- no headings, tables, code, links, or raw HTML. Text is
   only ever placed as text nodes; nothing from the model reaches
   innerHTML.
   ============================================================ */

const INLINE = /((?<!\w)\*\*(?!\s)[^*\n]+?(?<!\s)\*\*(?!\w)|(?<!\w)\*(?!\s)[^*\n]+?(?<!\s)\*(?!\w))/g;

function inline(text, keyBase) {
  const parts = text.split(INLINE).filter(Boolean);
  if (parts.length === 0) return null;
  if (parts.length === 1 && typeof parts[0] === "string") return parts[0];
  return parts.map((part, n) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={`${keyBase}-${n}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={`${keyBase}-${n}`}>{part.slice(1, -1)}</em>;
    return <span key={`${keyBase}-${n}`}>{part}</span>;
  });
}

export default function AnswerText({ text }) {
  const blocks = (text ?? "").split(/\n\s*\n/).filter((b) => b.trim());
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split("\n");
        const elements = [];
        let i = 0;
        let elemKey = 0;

        while (i < lines.length) {
          if (lines[i].startsWith("- ")) {
            // Collect consecutive list lines
            const listLines = [];
            while (i < lines.length && lines[i].startsWith("- ")) {
              listLines.push(lines[i]);
              i++;
            }
            elements.push(
              <ul key={`${b}-${elemKey}`}>
                {listLines.map((l, n) => <li key={`${b}-${elemKey}-${n}`}>{inline(l.slice(2), `${b}-${elemKey}-${n}`)}</li>)}
              </ul>
            );
            elemKey++;
          } else {
            // Collect consecutive non-list lines
            const paraLines = [];
            while (i < lines.length && !lines[i].startsWith("- ")) {
              paraLines.push(lines[i]);
              i++;
            }
            const paraText = paraLines.join(" ");
            if (paraText.trim()) {
              elements.push(<p key={`${b}-${elemKey}`}>{inline(paraText, `${b}-${elemKey}`)}</p>);
              elemKey++;
            }
          }
        }

        return <div key={b} style={{ display: "contents" }}>{elements}</div>;
      })}
    </>
  );
}
