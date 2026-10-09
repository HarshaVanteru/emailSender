// Keep these layout rules aligned with backend/app/services/email_layout.py.
const listItem = /^\s*(?:[-*•]|\d+[.)])\s+/;
const greeting = /^(?:hi|hello|dear|hey)\b.*[,!:]$/i;
const closing = /^(?:best(?: regards| wishes)?|kind regards|regards|warm(?:est)? regards|sincerely|thanks(?: again)?|thank you|cheers|respectfully)[,!]?$/i;

export function reflowEmailBody(body: string): string {
  return body.replace(/\r\n?/g, '\n').trim().split(/\n[ \t]*\n+/).map(paragraph => {
    const lines = paragraph.split('\n').map(line => line.trim());
    let inSignature = false;
    return lines.reduce((formatted, line, index) => {
      if (!index) return line;
      const previous = lines[index - 1];
      inSignature = inSignature || closing.test(previous);
      const separator = inSignature || greeting.test(previous) || closing.test(line) || listItem.test(line) ? '\n' : ' ';
      return formatted + separator + line;
    }, '');
  }).join('\n\n');
}
