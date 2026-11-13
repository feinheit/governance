"""Draws the states of proposals for the help (docs/proposals.md):
``docs/proposal-states.svg`` and ``docs/proposal-states.de.svg``

    uv run scripts/proposal_states.py

The help inlines them (governance/help.py), so that they take the colors
of the page's theme (the badges' tones of main.css); GitHub shows them as
images, in the fallback colors (light, dark by the system's setting).
"""

from pathlib import Path
from xml.sax.saxutils import escape


LABELS = {
    "en": {
        "title": "States of proposals",
        "draft": "draft",
        "published": "published",
        "waiting": "waiting for a meeting",
        "adopted": "adopted",
        "withdrawn": "withdrawn",
        "new": ["New", "proposal"],
        "publish": "Publish (async)",
        "back": ["Back to the draft,", "or a conflict"],
        "to_meeting": ["brought to", "a meeting"],
        "expired": ["three months", "without a meeting"],
        "requested": ["a meeting asked for,", "or brought to one"],
        "consented": ["everybody consented,", "or the deadline"],
        "withdraw": ["Withdraw"],
        "adopt": ["Adopt", "(in the meeting)"],
        "discard": ["Discard (in the meeting),", "or Withdraw"],
        "again": "Draft again (a new draft)",
    },
    "de": {
        "title": "Zustände von Vorschlägen",
        "draft": "Entwurf",
        "published": "veröffentlicht",
        "waiting": "wartet auf ein Meeting",
        "adopted": "angenommen",
        "withdrawn": "zurückgezogen",
        "new": ["Neuer", "Vorschlag"],
        "publish": "Veröffentlichen (asynchron)",
        "back": ["Zurück zum Entwurf,", "oder ein Konflikt"],
        "to_meeting": ["in ein Meeting", "gebracht"],
        "expired": ["drei Monate", "ohne Meeting"],
        "requested": ["Meeting gewünscht,", "oder in eines gebracht"],
        "consented": ["alle haben zugestimmt,", "oder die Frist"],
        "withdraw": ["Zurückziehen"],
        "adopt": ["Annehmen", "(im Meeting)"],
        "discard": ["Verwerfen (im Meeting),", "oder Zurückziehen"],
        "again": "Neu entwerfen (ein neuer Entwurf)",
    },
}

WIDTH, HEIGHT = 760, 480
BOX_W, BOX_H = 150, 40
# Centers of the states, their tones like the badges (the tone filter)
STATES = {
    "draft": (175, 225, "neutral"),
    "published": (395, 85, "warning"),
    "waiting": (395, 360, "info"),
    "adopted": (660, 85, "success"),
    "withdrawn": (660, 360, "neutral"),
}
# Fallback colors (main.css' light and dark tones) for GitHub's images
TONES = {
    "light": {
        "text": "#212529",
        "line": "#6c757d",
        "neutral": ("#eceef2", "#4a525c"),
        "info": ("#d9f1f4", "#0b6470"),
        "success": ("#dcf3e9", "#0f6e4b"),
        "warning": ("#fbefd2", "#855600"),
    },
    "dark": {
        "text": "#dee2e6",
        "line": "#9aa1a9",
        "neutral": ("#262a31", "#c3c8d0"),
        "info": ("#0e3338", "#7fd3de"),
        "success": ("#0f3326", "#6fd6a8"),
        "warning": ("#3a2c0c", "#f0c060"),
    },
}


def style():
    def rules(colors):
        lines = [
            f".ps-text {{ fill: var(--bs-body-color, {colors['text']}); }}",
            f".ps-line {{ stroke: var(--bs-secondary-color, {colors['line']}); }}",
            f".ps-head {{ fill: var(--bs-secondary-color, {colors['line']}); }}",
        ]
        for tone in ["neutral", "info", "success", "warning"]:
            bg, ink = colors[tone]
            lines += [
                (
                    f".ps-{tone} rect {{ fill: var(--wb-{tone}-bg, {bg});"
                    f" stroke: var(--wb-{tone}-ink, {ink}); }}"
                ),
                f".ps-{tone} text {{ fill: var(--wb-{tone}-ink, {ink}); }}",
            ]
        return "\n".join(lines)

    dark = rules(TONES["dark"]).replace("\n", "\n  ")
    return f"""
.ps {{ font: 13px system-ui, -apple-system, "Segoe UI", sans-serif; }}
.ps-state text {{ font-weight: 600; }}
.ps-line {{ fill: none; stroke-width: 1.25; }}
{rules(TONES["light"])}
@media (prefers-color-scheme: dark) {{
  {dark}
}}
"""


def box(name, label):
    x, y, tone = STATES[name]
    return (
        f'<g class="ps-state ps-{tone}">'
        f'<rect x="{x - BOX_W / 2}" y="{y - BOX_H / 2}" width="{BOX_W}"'
        f' height="{BOX_H}" rx="8"/>'
        f'<text x="{x}" y="{y + 4.5}" text-anchor="middle">{escape(label)}</text>'
        "</g>"
    )


def edge(path, label, x, y, anchor="middle"):
    """A transition: an SVG path and its label (one or more lines)"""
    lines = [label] if isinstance(label, str) else label
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else 15}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<path class="ps-line" d="{path}" marker-end="url(#ps-arrow)"/>'
        f'<text class="ps-text" x="{x}" y="{y}" text-anchor="{anchor}">{spans}</text>'
    )


def draw(labels):
    def left(name):
        return STATES[name][0] - BOX_W / 2

    def right(name):
        return STATES[name][0] + BOX_W / 2

    def top(name):
        return STATES[name][1] - BOX_H / 2

    def bottom(name):
        return STATES[name][1] + BOX_H / 2

    d, p, w, a, x = "draft", "published", "waiting", "adopted", "withdrawn"
    parts = [
        # Start
        f'<circle class="ps-head" cx="18" cy="{STATES[d][1]}" r="6"/>',
        edge(
            f"M24 {STATES[d][1]} H{left(d) - 2}",
            labels["new"],
            24,
            STATES[d][1] + 20,
            "start",
        ),
        # draft ⇄ published
        edge(
            f"M{STATES[d][0] - 30} {top(d)} C{STATES[d][0] - 30} 90,"
            f" 260 {STATES[p][1] - 10}, {left(p) - 2} {STATES[p][1] - 10}",
            labels["publish"],
            205,
            62,
        ),
        edge(
            f"M{left(p)} {STATES[p][1] + 10} C300 {STATES[p][1] + 10},"
            f" {STATES[d][0] + 30} 130, {STATES[d][0] + 30} {top(d) - 2}",
            labels["back"],
            STATES[p][0] - 8,
            150,
            "end",
        ),
        # draft ⇄ waiting
        edge(
            f"M{right(d)} {STATES[d][1] + 8} C300 {STATES[d][1] + 8},"
            f" 300 {STATES[w][1] - 8}, {left(w) - 2} {STATES[w][1] - 8}",
            labels["to_meeting"],
            288,
            262,
            "start",
        ),
        edge(
            f"M{left(w)} {STATES[w][1] + 10} C240 {STATES[w][1] + 10},"
            f" {STATES[d][0]} 320, {STATES[d][0]} {bottom(d) + 2}",
            labels["expired"],
            150,
            318,
            "end",
        ),
        # published → waiting
        edge(
            f"M{STATES[p][0]} {bottom(p)} V{top(w) - 2}",
            labels["requested"],
            STATES[p][0] + 10,
            140,
            "start",
        ),
        # → adopted, → withdrawn
        edge(
            f"M{right(p)} {STATES[p][1]} H{left(a) - 2}",
            labels["consented"],
            (right(p) + left(a)) / 2,
            STATES[p][1] - 26,
        ),
        # Around the right, not crossing waiting → adopted
        edge(
            f"M{STATES[p][0] + 20} {top(p)} V22 H{WIDTH - 8}"
            f" V{STATES[x][1]} H{right(x) + 2}",
            labels["withdraw"],
            (STATES[p][0] + WIDTH) / 2,
            16,
        ),
        edge(
            f"M{right(w) - 20} {top(w)} L{left(a) + 20} {bottom(a) + 2}",
            labels["adopt"],
            right(w) + 52,
            top(w) - 90,
            "start",
        ),
        edge(
            f"M{right(w)} {STATES[w][1]} H{left(x) - 2}",
            labels["discard"],
            (right(w) + left(x)) / 2,
            STATES[w][1] + 36,
        ),
        # withdrawn → a new draft
        edge(
            f"M{STATES[x][0]} {bottom(x)} V{HEIGHT - 20} H{STATES[d][0] - 40}"
            f" V{bottom(d) + 2}",
            labels["again"],
            (STATES[x][0] + STATES[d][0]) / 2,
            HEIGHT - 26,
        ),
        *(box(name, labels[name]) for name in STATES),
    ]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="ps"'
        f' viewBox="0 0 {WIDTH} {HEIGHT}" role="img">'
        f"<title>{escape(labels['title'])}</title>"
        f"<style>{style()}</style>"
        '<defs><marker id="ps-arrow" viewBox="0 0 10 10" refX="9" refY="5"'
        ' markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path class="ps-head" d="M0 0 L10 5 L0 10 z"/></marker></defs>'
        + "\n".join(parts)
        + "</svg>\n"
    )


if __name__ == "__main__":
    docs = Path(__file__).resolve().parent.parent / "docs"
    for language, labels in LABELS.items():
        suffix = "" if language == "en" else f".{language}"
        (docs / f"proposal-states{suffix}.svg").write_text(draw(labels))
