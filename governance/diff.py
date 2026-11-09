"""Changed texts as a diff: the words removed and added, rendered as Markdown

The sources are compared line by line (paragraphs, list items), changed
lines word by word (mentions, links and URLs as one word each). Markers go
into the source and become ``<del>`` and ``<ins>`` after rendering; they
never span a line break or come before a line's block syntax (a list's
bullet, a heading's ``#``), so that paragraphs and lists stay what they
are. Texts which have little in common are shown removed and added as a
whole.
"""

import re
from difflib import SequenceMatcher

from django.utils.html import format_html
from django.utils.safestring import mark_safe


TOKEN = re.compile(
    r"@\[[^\]]*\]\(role:\d+\)"  # Mentions
    r"|\[[^\]]*\]\([^)\s]*\)"  # Links
    r"|https?://\S+"
    r"|\w+|\s+|([^\w\s])\1*"
)
BLOCK = re.compile(r"\s*(?:[-*+]|\d+[.)]|#{1,6}|>)\s+")
# Private use characters, Markdown leaves them alone; ``-line`` for whole
# lines, whose list bullets are colored too (main.css)
MARKERS = {
    "del": ("", ""),
    "ins": ("", ""),
    "del-line": ("", ""),
    "ins-line": ("", ""),
}


def tokens(text):
    return [match[0] for match in TOKEN.finditer(text)]


def similar(old, new):
    """Whether the texts have enough words in common for a diff"""
    words = [[token for token in tokens(text) if token.strip()] for text in (old, new)]
    return SequenceMatcher(None, *words, autojunk=False).ratio() >= 0.4


def mark(text, tag):
    start, end = MARKERS[tag]
    return f"{start}{text}{end}" if text.strip() else text


def mark_line(line, tag):
    """The whole line marked, after its block syntax"""
    prefix = match[0] if (match := BLOCK.match(line)) else ""
    return prefix + mark(line[len(prefix) :], f"{tag}-line")


def mark_text(text, tag):
    return "\n".join(mark_line(line, tag) for line in text.split("\n"))


def diff_line(old, new):
    """One line changed: its words marked"""
    old_prefix = match[0] if (match := BLOCK.match(old)) else ""
    new_prefix = match[0] if (match := BLOCK.match(new)) else ""
    if old_prefix.strip() != new_prefix.strip():
        return f"{mark_line(old, 'del')} {mark(new, 'ins')}"
    old, new = tokens(old[len(old_prefix) :]), tokens(new[len(new_prefix) :])
    result = [new_prefix]
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            result.append("".join(new[j1:j2]))
        else:
            result.extend((
                mark("".join(old[i1:i2]), "del"),
                mark("".join(new[j1:j2]), "ins"),
            ))
    return "".join(result)


def render(source):
    from governance.templatetags.governance import markdown

    html = str(markdown(source))
    for key, (start, end) in MARKERS.items():
        tag, _sep, line = key.partition("-")
        classes = f"wb-diff-{tag} wb-diff-line" if line else f"wb-diff-{tag}"
        html = html.replace(start, f'<{tag} class="{classes}">')
        html = html.replace(end, f"</{tag}>")
    return mark_safe(html)


def diff(old, new):
    """HTML of the Markdown ``new`` with what changed from ``old`` marked"""
    old, new = old or "", new or ""
    if not similar(old, new):
        return format_html(
            "<div>{}</div><div>{}</div>",
            render(mark_text(old, "del")),
            render(mark_text(new, "ins")),
        )
    old_lines, new_lines = old.split("\n"), new.split("\n")
    lines = []
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            lines.extend(new_lines[j1:j2])
            continue
        removed, added = old_lines[i1:i2], new_lines[j1:j2]
        # Lines replaced one by one are compared word by word
        while removed and added and similar(removed[0], added[0]):
            lines.append(diff_line(removed.pop(0), added.pop(0)))
        lines.extend(mark_line(line, "del") for line in removed)
        lines.extend(mark_line(line, "ins") for line in added)
    return render("\n".join(lines))
