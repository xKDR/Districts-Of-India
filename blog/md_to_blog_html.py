"""article_current.md -> article_current.html, in the blog's house style.

Per blog/instructions.txt, which supersedes the blog's online instructions page:
hand-written markup only, <html><body> wrapper, <p> around every paragraph, <h3>
for section titles and nothing below them, graphs centred and inserted as .png,
no CSS, no title inside the post, first para is the byline, <h3>Acknowledgments</h3>
at the end.

    python md_to_blog_html.py

Deliberately handles only the constructs this article actually uses -- paragraphs,
h3, images with an italic caption, bullet lists, links, italics, em dashes. It is
not a general Markdown implementation and does not need to be.
"""

import html
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent / "article_current.md"
DST = SRC.with_suffix(".html")
IMG_WIDTH = 700  # px; blogger scales the rest


def inline(text: str) -> str:
    """Markdown inlines -> HTML, on text that is not itself markup."""
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    text = text.replace("—", "&mdash;").replace("–", "&ndash;")
    return text


blocks = [b.strip() for b in SRC.read_text().split("\n\n") if b.strip()]
out, i = [], 0
while i < len(blocks):
    b = blocks[i]
    if b.startswith("### "):
        out.append(f"<h3>{inline(b[4:])}</h3>")
    elif b.startswith("!["):
        alt, src = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", b).groups()
        caption = ""
        if i + 1 < len(blocks) and blocks[i + 1].startswith("*"):
            i += 1
            caption = f"<br><i>{inline(blocks[i].strip('*'))}</i>"
        out.append(
            f'<center><img src="{html.escape(src)}" alt="{html.escape(alt)}" '
            f'width="{IMG_WIDTH}">{caption}</center>'
        )
    elif b.startswith("- "):
        items = "".join(f"<li>{inline(line[2:])}</li>" for line in b.split("\n"))
        out.append(f"<ul>{items}</ul>")
    else:
        out.append(f"<p>{inline(' '.join(b.split(chr(10))))}</p>")
    i += 1

# instructions.txt item 3: start with <html><body>, end with </body></html>.
DST.write_text("<html><body>\n\n" + "\n\n".join(out) + "\n\n</body></html>\n")
print(f"wrote {DST.name}: {len(out)} blocks, "
      f"{sum(o.startswith('<center>') for o in out)} figures, "
      f"{sum(o.startswith('<h3>') for o in out)} sections")
