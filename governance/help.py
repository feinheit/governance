"""The user documentation in docs/ as help pages

The Markdown files link each other relatively (``vorschlaege.md``), which
works on GitHub; here the links lead to the help pages instead.
"""

import re

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt


# Page → file in docs/, the README is the start page
PAGES = {
    "": "README.md",
    "orientierung": "orientierung.md",
    "vorschlaege": "vorschlaege.md",
    "meetings": "meetings.md",
    "operatives": "operatives.md",
    "verfassung": "constitution/Holacracy-Verfassung.md",
}
FILES = {file: page for page, file in PAGES.items()}

_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
_link = re.compile(r'href="([^":#]+\.md)(#[^"]*)?"')


def url(page):
    return reverse("help", args=[page]) if page else reverse("help")


def render_page(page):
    if page not in PAGES:
        raise Http404
    text = (settings.BASE_DIR / "docs" / PAGES[page]).read_text()
    title = re.sub(r"[*_]", "", text.split("\n", 1)[0].removeprefix("# ")).strip()

    def link(match):
        if match[1] not in FILES:
            return match[0]
        return f'href="{url(FILES[match[1]])}{match[2] or ""}"'

    html = _markdown.render(text)
    html = re.sub(r"^<h1>.*?</h1>\n", "", html, count=1)  # The page's title
    return title, mark_safe(_link.sub(link, html))


def help_page(request, page=""):
    title, html = render_page(page)
    return render(
        request,
        "help.html",
        {"title": title, "html": html, "start": url("") if page else None},
    )
