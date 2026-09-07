"""article_*.md -> Quarto .qmd (+ a starter _quarto.yml), for a rendered website.

    python md_to_quarto.py && quarto render .

Quarto reads Markdown natively, so this does only the four things Quarto cannot
guess from the source: attach YAML front matter, lift the byline out of the body
into the author field, promote the Blogger-mandated h3 section titles to h2, and
repoint the cross-links at the .html Quarto publishes rather than the .md source.

Companion to md_to_blog_html.py, which targets Blogger's hand-written-HTML house
style instead. Both read the same markdown; neither is derived from the other.

    python md_to_quarto.py --check    # self-check, writes nothing
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES_URL = "https://xkdr.github.io/India-Built-and-Lit/blog/"

# Titles live here, not in the markdown: the blog's house style forbids a title
# inside the post, so the .md files genuinely do not carry one. Anything absent
# from this table is a working note rather than a page -- cheatsheet.md and
# district_summary.md are not meant to be published.
PAGES = {
    "article_current.md": {
        "title": "India, Built and Lit",
        "subtitle": "District building volume and nighttime lights, from satellite imagery",
        # A website project needs a landing page. This is the only page that could
        # be one, and Quarto resolves navbar hrefs through it, so the href below
        # stays article_current.qmd.
        "output-file": "index.html",
    },
    "article_appendix.md": {
        "title": "Appendix: problems in the building volume data",
    },
}

SITE = """\
project:
  type: website
  output-dir: _site

website:
  title: "India · Built & Lit"
  navbar:
    left:
      - href: article_current.qmd
        text: Article
      - href: article_appendix.qmd
        text: Appendix
      - href: https://github.com/xKDR/India-Built-and-Lit
        text: GitHub

format:
  html:
    theme: cosmo
    toc: true
    fig-align: center
"""

BYLINE = re.compile(r"^By (.+?)\.?\s*$")


def quote(value: str) -> str:
    """Always quote. The byline is prose, and '[AUTHOR NAMES].' unquoted is a
    YAML flow sequence, not a string -- it would parse as a one-element list."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def convert(text: str, meta: dict, pages=PAGES) -> str:
    body = text.strip()
    front = dict(meta)

    # Byline is the article's first paragraph, per the blog's house style. Quarto
    # renders `author` in the title block, so leaving it in the body would print
    # it twice.
    first, _, rest = body.partition("\n\n")
    m = BYLINE.match(first.strip())
    if m:
        front["author"] = m.group(1)
        body = rest.lstrip()

    # h3-only is a Blogger rule. Under a Quarto page title (h1) it skips a level,
    # which breaks both the document outline and the sidebar TOC nesting.
    body = re.sub(r"^### ", "## ", body, flags=re.MULTILINE)

    # A leading heading duplicates the title Quarto renders from the front matter.
    # article_appendix.md carries one so it reads as a standalone document; here
    # it would print the title twice.
    head, sep, tail = body.partition("\n\n")
    if head.lstrip().startswith("#"):
        body = tail.lstrip()

    # Absolute Pages links to a sibling article point at the .md source, which
    # Quarto does not publish. Only rewrite targets that are actually built here:
    # a link to an unlisted .md would otherwise become a dead .html.
    def relink(m):
        name = m.group(1)
        return f"{name}.html" if f"{name}.md" in pages else m.group(0)

    body = re.sub(re.escape(PAGES_URL) + r"(\w+)\.md", relink, body)

    fm = "\n".join(f"{k}: {quote(v)}" for k, v in front.items())
    return f"---\n{fm}\n---\n\n{body}\n"


def check():
    src = (
        "By [AUTHOR NAMES].\n\n"
        "### Duplicated page title\n\n"
        "### A section\n\n"
        f"See [our appendix]({PAGES_URL}article_appendix.md) and "
        f"[the notes]({PAGES_URL}cheatsheet.md).\n"
    )
    out = convert(src, {"title": 'A "quoted" title'})
    assert 'author: "[AUTHOR NAMES]"' in out, "byline must be lifted and quoted"
    assert "By [AUTHOR NAMES]" not in out.split("---")[2], "byline left in body"
    assert 'title: "A \\"quoted\\" title"' in out, "quotes in a title must escape"
    assert "\n## A section" in out and "### A section" not in out, "h3 -> h2"
    assert "Duplicated page title" not in out, "leading heading must be dropped"
    assert "(article_appendix.html)" in out, "known page must relink to .html"
    assert f"({PAGES_URL}cheatsheet.md)" in out, "unlisted page must be left alone"
    print("self-check ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
        sys.exit()
    for name, meta in PAGES.items():
        dst = (HERE / name).with_suffix(".qmd")
        dst.write_text(convert((HERE / name).read_text(), meta))
        print("wrote", dst.name)
    site = HERE / "_quarto.yml"
    if site.exists():
        print("kept", site.name, "(already present, not overwritten)")
    else:
        site.write_text(SITE)
        print("wrote", site.name)
