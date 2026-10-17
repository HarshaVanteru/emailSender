"""Reflow email prose without imposing a fixed reading width."""

import re
from html import escape


LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
GREETING = re.compile(r"^(?:hi|hello|dear|hey)\b.*[,!:]$", re.IGNORECASE)
CLOSING = re.compile(
    r"^(?:best(?: regards| wishes)?|kind regards|regards|warm(?:est)? regards|"
    r"sincerely|thanks(?: again)?|thank you|cheers|respectfully)[,!]?$",
    re.IGNORECASE,
)


def reflow_email_body(body: str) -> str:
    """Join hard-wrapped prose; retain intentional paragraph/list/sign-off breaks."""
    paragraphs = re.split(r"\n[ \t]*\n+", body.replace("\r\n", "\n").replace("\r", "\n").strip())
    result = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.split("\n")]
        formatted = ""
        in_signature = False
        for index, line in enumerate(lines):
            if index:
                previous = lines[index - 1]
                in_signature = in_signature or bool(CLOSING.match(previous))
                keep_break = (
                    in_signature
                    or GREETING.match(previous)
                    or CLOSING.match(line)
                    or LIST_ITEM.match(line)
                )
                separator = "\n" if keep_break else " "
                formatted += separator
            formatted += line
        result.append(formatted)
    return "\n\n".join(result)


def render_email_html(body: str) -> str:
    """Escape all content and use fluid, Gmail-compatible inline styling."""
    paragraphs = reflow_email_body(body).split("\n\n")
    content = "".join(
        '<p style="margin:0 0 16px;white-space:normal;overflow-wrap:anywhere;word-wrap:break-word;">'
        + escape(paragraph).replace("\n", "<br>")
        + "</p>"
        for paragraph in paragraphs
    )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
        '</head><body style="margin:0;padding:0;">'
        '<div style="width:100%;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:1.5;overflow-wrap:anywhere;word-wrap:break-word;">'
        + content
        + "</div></body></html>"
    )
