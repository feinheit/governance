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
# where from and when, under the title
SOURCES = {
    "en": {
        "url": "https://github.com/holacracyone/Holacracy-Constitution/tree/v5.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    "de": {
        "url": "https://github.com/holacracyone/Holacracy-Constitution-5.0-GERMAN",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.de",
    },
}
COPIED_ON = dt.date(2026, 11, 5)
# The docs come from the repository, not from users: HTML like <kbd> is fine
_markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
_link = re.compile(r'href="([^":#]+\.md)(#[^"]*)?"')


def url(page):
    return reverse("help", args=[page]) if page else reverse("help")


def render_page(page, language="de"):
    pages = PAGES["de" if language == "de" else "en"]
    if page not in pages:
        raise Http404
    text = (settings.BASE_DIR / "docs" / pages[page]).read_text()
    title = re.sub(r"[*_]", "", text.split("\n", 1)[0].removeprefix("# ")).strip()
    # Links relative to the page's file
    here = posixpath.dirname(pages[page])
    files = {posixpath.relpath(file, here or "."): key for key, file in pages.items()}

    def link(match):
        if match[1] not in files:
            return match[0]
        return f'href="{url(files[match[1]])}{match[2] or ""}"'

    html = _markdown.render(text)
    html = re.sub(r"^<h1>.*?</h1>\n", "", html, count=1)  # The page's title
    return title, mark_safe(_link.sub(link, html))


def help_page(request, page=""):
    language = "de" if get_language() == "de" else "en"
    title, html = render_page(page, language)
    return render(
        request,
        "help.html",
        {
            "title": title,
            "html": html,
            "start": url("") if page else None,
            "source": SOURCES[language] | {"date": COPIED_ON}
            if page == "constitution"
            else None,
        },
    )
