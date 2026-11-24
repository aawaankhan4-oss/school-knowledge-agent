"""Converts PROGRESS.md into a formatted PDF, for sending out after the demo."""
import sys
import markdown
from bs4 import BeautifulSoup, NavigableString
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable,
)

SRC = sys.argv[1] if len(sys.argv) > 1 else "PROGRESS.md"
OUT = sys.argv[2] if len(sys.argv) > 2 else "PROGRESS.pdf"

with open(SRC, "r", encoding="utf-8") as f:
    md_text = f.read()

html = markdown.markdown(md_text, extensions=["extra"])
soup = BeautifulSoup(html, "html.parser")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1Custom", fontSize=20, leading=24, spaceBefore=4, spaceAfter=10, textColor=colors.HexColor("#1a2b5c")))
styles.add(ParagraphStyle(name="H2Custom", fontSize=15, leading=19, spaceBefore=16, spaceAfter=6, textColor=colors.HexColor("#1a2b5c")))
styles.add(ParagraphStyle(name="BodyCustom", fontSize=10, leading=14, spaceAfter=4))
styles.add(ParagraphStyle(name="BulletCustom", fontSize=10, leading=14))


def inline_to_markup(tag):
    """Converts bs4 inline children (strong/em/code/a/text) to reportlab mini-markup."""
    out = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            out.append(str(child))
        elif child.name == "strong":
            out.append(f"<b>{inline_to_markup(child)}</b>")
        elif child.name == "em":
            out.append(f"<i>{inline_to_markup(child)}</i>")
        elif child.name == "code":
            out.append(f'<font face="Courier" size="9">{child.get_text()}</font>')
        elif child.name == "a":
            out.append(f'<link href="{child.get("href", "")}" color="blue">{inline_to_markup(child)}</link>')
        else:
            out.append(inline_to_markup(child))
    return "".join(out)


story = []
for el in soup.find_all(["h1", "h2", "h3", "p", "ul", "ol", "hr"], recursive=False):
    if el.name == "h1":
        story.append(Paragraph(inline_to_markup(el), styles["H1Custom"]))
    elif el.name in ("h2", "h3"):
        story.append(Paragraph(inline_to_markup(el), styles["H2Custom"]))
    elif el.name == "p":
        story.append(Paragraph(inline_to_markup(el), styles["BodyCustom"]))
    elif el.name in ("ul", "ol"):
        items = []
        for li in el.find_all("li", recursive=False):
            items.append(ListItem(Paragraph(inline_to_markup(li), styles["BulletCustom"]), bulletColor=colors.HexColor("#1a2b5c")))
        story.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=16, spaceAfter=8))
    elif el.name == "hr":
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        story.append(Spacer(1, 4))

doc = SimpleDocTemplate(
    OUT, pagesize=LETTER,
    topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    title="School Info Assistant — Progress Log",
)
doc.build(story)
print(f"Wrote {OUT}")
