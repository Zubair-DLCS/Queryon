"""Builds small sample documents in every supported format for the tests."""

from __future__ import annotations

from pathlib import Path

PARAS = [
    "Photosynthesis is the process plants use to turn light energy into chemical energy. "
    "It takes place mainly in the leaves, inside small structures called chloroplasts.",
    "Chlorophyll is the green pigment that absorbs sunlight. Plants take in carbon dioxide "
    "from the air and water from the soil, and release oxygen as a by-product.",
    "The light-dependent reactions happen in the thylakoid membranes and produce ATP and NADPH. "
    "The Calvin cycle then uses these to build glucose from carbon dioxide in the stroma.",
    "Factors such as light intensity, temperature and carbon dioxide concentration limit the rate "
    "of photosynthesis. Farmers use greenhouses to control these factors and increase crop yield.",
]
TEXT = "\n\n".join(PARAS)


def make_all(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = {}

    import pymupdf

    pdf = pymupdf.open()
    for i in range(0, 4, 2):
        page = pdf.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), PARAS[i] + "\n\n" + PARAS[i + 1], fontsize=11)
    out["pdf"] = folder / "sample.pdf"
    pdf.save(out["pdf"])

    import docx

    d = docx.Document()
    d.add_heading("Photosynthesis", level=1)
    for p in PARAS[:2]:
        d.add_paragraph(p)
    d.add_heading("Reactions and limits", level=1)
    for p in PARAS[2:]:
        d.add_paragraph(p)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Input", "Output"
    t.cell(1, 0).text, t.cell(1, 1).text = "Carbon dioxide and water", "Glucose and oxygen"
    out["docx"] = folder / "sample.docx"
    d.save(out["docx"])

    from pptx import Presentation

    prs = Presentation()
    for i, p in enumerate(PARAS):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = f"Topic {i + 1}"
        s.placeholders[1].text = p
        s.notes_slide.notes_text_frame.text = "Remember this for the exam."
    out["pptx"] = folder / "sample.pptx"
    prs.save(out["pptx"])

    out["txt"] = folder / "sample.txt"
    out["txt"].write_text(TEXT, encoding="utf-8")
    out["md"] = folder / "sample.md"
    out["md"].write_text("# Photosynthesis\n\n" + TEXT, encoding="utf-8")
    out["rtf"] = folder / "sample.rtf"
    out["rtf"].write_text("{\\rtf1\\ansi " + "\\par\\par ".join(PARAS) + "}", encoding="utf-8")

    from odf.opendocument import OpenDocumentText
    from odf.text import H, P

    odt = OpenDocumentText()
    odt.text.addElement(H(outlinelevel=1, text="Photosynthesis"))
    for p in PARAS:
        odt.text.addElement(P(text=p))
    out["odt"] = folder / "sample.odt"
    odt.save(str(out["odt"]))

    # A picture of text (like a phone photo of a page) and a scanned PDF.
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    img = Image.new("RGB", (1700, 900), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    import textwrap

    for p in PARAS[:2]:
        for line in textwrap.wrap(p, 80):
            draw.text((60, y), line, fill="black", font=font)
            y += 44
        y += 30
    out["png"] = folder / "sample.png"
    img.save(out["png"])

    scan = pymupdf.open()
    page = scan.new_page(width=img.width * 72 / 200, height=img.height * 72 / 200)
    page.insert_image(page.rect, filename=str(out["png"]))
    out["scan"] = folder / "scanned.pdf"
    scan.save(out["scan"])
    return out
