"""A small markdown renderer for exactly the markdown this repo generates.

Deliberately not a general one and deliberately not a CDN dependency: the
dashboard has to render correctly with no network at all, and the input is
markdown we control (our own two templates), so a focused renderer is both
smaller and more predictable than pulling in a parser.
"""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<![\*\w])\*([^\*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_RAW_HTML_LINE = re.compile(r"^\s*</?(sub|details|summary|div|span|br|img)\b", re.I)


def _inline(text: str) -> str:
    """Escape, then re-apply the inline markup. Order matters: code first so
    its contents are never re-parsed as markup."""
    placeholders: list[str] = []

    def stash(match: re.Match) -> str:
        placeholders.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _INLINE_CODE.sub(stash, text)
    # Inline raw tags we emit ourselves pass through; everything else escapes.
    parts = re.split(r"(</?(?:sub|em|strong|br|details|summary)\s*/?>)", text)
    text = "".join(p if i % 2 else html.escape(p) for i, p in enumerate(parts))
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" rel="noopener">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    for i, ph in enumerate(placeholders):
        text = text.replace(f"\x00{i}\x00", ph)
    return text


def render(md: str) -> str:
    """Markdown → HTML for the subset our templates emit."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            close_list()
            i += 1
            continue

        # Raw HTML we emit ourselves passes through. A <sub> line is the one
        # exception: it carries inline markdown (scores, rungs, links), so its
        # contents still need rendering — _inline keeps the <sub> tags intact.
        if _RAW_HTML_LINE.match(line):
            close_list()
            out.append(_inline(stripped) if stripped.startswith("<sub>") else line)
            i += 1
            continue

        if stripped.startswith("---") and set(stripped) == {"-"}:
            close_list()
            out.append("<hr>")
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        # Tables: a header row followed by a separator row.
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
            close_list()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head = "".join(f"<th>{_inline(c)}</th>" for c in header)
            body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            continue

        if stripped.startswith(">"):
            close_list()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
            continue

        task = re.match(r"^[-*]\s+\[( |x|X)\]\s+(.*)$", stripped)
        if task:
            if not in_list:
                out.append('<ul class="tasks">')
                in_list = True
            done = task.group(1).lower() == "x"
            mark = "checked" if done else ""
            out.append(
                f'<li class="task{" done" if done else ""}">'
                f'<span class="box" data-checked="{str(done).lower()}" aria-hidden="true"></span>'
                f"<span>{_inline(task.group(2))}</span></li>"
            )
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            i += 1
            continue

        close_list()
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^\s*(#{1,6}\s|[-*]\s|>|\||---)", lines[i]
        ) and not _RAW_HTML_LINE.match(lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")

    close_list()
    return "\n".join(out)
