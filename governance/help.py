"""The user documentation in docs/ as help pages

English in ``name.md``, German in ``name.de.md``, shown in the page's
language. The Markdown files link each other relatively
(``proposals.md``), which works on GitHub; here the links lead to the help
pages instead.
"""

import datetime as dt
import posixpath
import re

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from markdown_it import MarkdownIt


# Page → file in docs/ per language, the README is the start page
_NAMES = {
    "": "README",
    "orientation": "orientation",
    "proposals": "proposals",
    "meetings": "meetings",
    "operational": "operational",
    "mails": "mails",
}
PAGES = {
    "en": {page: f"{name}.md" for page, name in _NAMES.items()}
    | {"constitution": "constitution/Holacracy-Constitution.md"},
    "de": {page: f"{name}.de.md" for page, name in _NAMES.items()}
    | {"constitution": "constitution/Holacracy-Verfassung.md"},
}
# The constitution's texts are HolacracyOne's, copied unchanged (NOTICE):
# where from and the version, the day of the document's latest change
# upstream (compared again on 2026-11-10), under the title
SOURCES = {
    "en": {
        "url": "https://github.com/holacracyone/Holacracy-Constitution/tree/v5.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "date": dt.date(2021, 5, 20),
    },
    "de": {
        "url": "https://github.com/holacracyone/Holacracy-Constitution-5.0-GERMAN",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.de",
        "date": dt.date(2026, 3, 25),
    },
}
# The docs come from the repository, not from users: HTML like <kbd> is fine
_markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
_link = re.compile(r'href="([^":#]+\.md)(#[^"]*)?"')
# Drawings next to the docs (e.g. scripts/proposal_states.py), inlined: in
# the page's colors (light and dark), their text in its font
_svg = re.compile(r'<img src="([^":/]+\.svg)" alt="([^"]*)"\s*/?>')


def url(page):
    return reverse("help", args=[page]) if page else reverse("help")


# The constitution's files are unchanged (NOTICE), their titles not quite
# right (German needs the hyphen)
TITLES = {
    "Holacracy Verfassung": "Holacracy-Verfassung",
}


def _title(line):
    title = re.sub(r"[*_]", "", line.removeprefix("# ")).strip()
    return TITLES.get(title, title)


def chapters(page, language="de"):
    """All pages in their order (the start page first, the constitution
    last), for the navigation above each: their titles, the current one"""
    pages = PAGES["de" if language == "de" else "en"]
    result = []
    for key, file in pages.items():
        with (settings.BASE_DIR / "docs" / file).open() as f:
            title = _title(f.readline())
        result.append({"url": url(key), "title": title, "current": key == page})
    return result


def render_page(page, language="de"):
    pages = PAGES["de" if language == "de" else "en"]
    if page not in pages:
        raise Http404
    text = (settings.BASE_DIR / "docs" / pages[page]).read_text()
    title = _title(text.split("\n", 1)[0])
    # Links relative to the page's file
    here = posixpath.dirname(pages[page])
    files = {posixpath.relpath(file, here or "."): key for key, file in pages.items()}

    def link(match):
        if match[1] not in files:
            return match[0]
        return f'href="{url(files[match[1]])}{match[2] or ""}"'

    def svg(match):
        drawing = (settings.BASE_DIR / "docs" / here / match[1]).read_text()
        return drawing.replace("<svg ", f'<svg aria-label="{match[2]}" ', 1)

    html = _svg.sub(svg, _markdown.render(text))
    html = re.sub(r"^<h1>.*?</h1>\n", "", html, count=1)  # The page's title
    return title, mark_safe(_link.sub(link, html))


def help_page(request, page=""):
    language = "de" if get_language() == "de" else "en"
    if page not in PAGES[language]:
        raise Http404
    # In the page's language, also for the constitution in the other one
    context = {"chapters": chapters(page, language)}
    if page == "constitution":
        # The constitution in the other language on request, the rest of
        # the page stays in the user's
        if (requested := request.GET.get("language")) in SOURCES:
            language = requested
        context |= {
            "language": language,
            "source": SOURCES[language],
            "languages": [("de", "Deutsch"), ("en", "English")],
        }
    context["title"], context["html"] = render_page(page, language)
    return render(request, "help.html", context)
