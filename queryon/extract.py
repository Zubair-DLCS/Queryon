"""Reading text out of every supported file type.

Each reader returns a Document made of Blocks, so answers can point back to
"Page 3" or "Slide 5". Scanned PDF pages and images go through OCR (Tesseract).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import app_dir
from .document import Block, Document, count_words

PART_WORDS = 350  # size of a "Part" for formats that have no pages

FILE_TYPES = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".doc": "Word (old .doc)",
    ".pptx": "PowerPoint",
    ".ppt": "PowerPoint (old .ppt)",
    ".txt": "Text",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".rtf": "Rich Text",
    ".odt": "OpenDocument Text",
    ".odp": "OpenDocument Slides",
    ".png": "Image",
    ".jpg": "Image",
    ".jpeg": "Image",
    ".bmp": "Image",
    ".tif": "Image",
    ".tiff": "Image",
    ".webp": "Image",
}

OPEN_DIALOG_FILTER = (
    "Study documents (*.pdf *.docx *.doc *.pptx *.ppt *.txt *.md *.rtf *.odt *.odp "
    "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*.*)"
)


class ExtractionError(Exception):
    """A message that can be shown to the student as-is."""


# --------------------------------------------------------------------------- helpers

def _clean(text: str) -> str:
    text = text.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # re-join hyphenated line breaks
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _unwrap(par: str) -> str:
    """Turn a PDF paragraph with hard line breaks into one line."""
    return re.sub(r"\s*\n\s*", " ", par).strip()


def _split_into_parts(paragraphs: list[tuple[str, str]]) -> list[Block]:
    """Group (heading, paragraph) pairs into Parts of about PART_WORDS words."""
    blocks: list[Block] = []
    cur: list[str] = []
    cur_heading = ""
    cur_words = 0
    for heading, par in paragraphs:
        par = par.strip()
        if not par:
            continue
        new_section = heading and heading != cur_heading and cur_words > PART_WORDS * 0.4
        if cur and (cur_words + count_words(par) > PART_WORDS * 1.3 or new_section):
            blocks.append(Block(f"Part {len(blocks) + 1}", "\n\n".join(cur), cur_heading))
            cur, cur_words = [], 0
        if not cur:
            cur_heading = heading
        cur.append(par)
        cur_words += count_words(par)
    if cur:
        blocks.append(Block(f"Part {len(blocks) + 1}", "\n\n".join(cur), cur_heading))
    return blocks


# --------------------------------------------------------------------------- OCR

def find_tesseract() -> str | None:
    candidates = [
        app_dir() / "tesseract" / "tesseract.exe",
        app_dir() / "tesseract" / "tesseract",
    ]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "tesseract" / "tesseract.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which("tesseract")
    if found:
        return found
    for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if pf and (Path(pf) / "Tesseract-OCR" / "tesseract.exe").exists():
            return str(Path(pf) / "Tesseract-OCR" / "tesseract.exe")
    return None


def ocr_image(image) -> str:
    """OCR a PIL image. Raises ExtractionError if Tesseract is not available."""
    exe = find_tesseract()
    if not exe:
        raise ExtractionError(
            "This file contains scanned pages or pictures, and the OCR component "
            "(Tesseract) was not found. Reinstall Queryon or install Tesseract OCR."
        )
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = exe
    tessdata = Path(exe).parent / "tessdata"
    if tessdata.exists():
        # An environment variable avoids Windows path-quoting problems with --tessdata-dir.
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    image = image.convert("L")
    return pytesseract.image_to_string(image, lang="eng")


# --------------------------------------------------------------------------- readers

def read_pdf(path: Path, progress=None) -> Document:
    import pymupdf

    try:
        pdf = pymupdf.open(path)
    except Exception as e:
        raise ExtractionError(f"Could not open this PDF ({e}).") from e
    if pdf.needs_pass:
        raise ExtractionError("This PDF is password-protected. Remove the password and try again.")
    blocks, ocr_pages = [], 0
    n = len(pdf)
    for i, page in enumerate(pdf):
        if progress:
            progress(i, n, f"Reading page {i + 1} of {n}")
        pars = []
        for b in page.get_text("blocks", sort=True):
            if b[6] == 0:  # text block
                t = _unwrap(_clean(b[4]))
                if t:
                    pars.append(t)
        text = "\n\n".join(pars)
        if count_words(text) < 15 and (page.get_images() or not text):
            from PIL import Image

            if progress:
                progress(i, n, f"Scanned page {i + 1} of {n}: recognising text (OCR)")
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            ocr = _clean(ocr_image(img))
            del img, pix
            if count_words(ocr) > count_words(text):
                text = "\n\n".join(_unwrap(p) for p in ocr.split("\n\n"))
                ocr_pages += 1
        if text.strip():
            blocks.append(Block(f"Page {i + 1}", text))
    pdf.close()
    return Document(path, "PDF", blocks, ocr_used=ocr_pages)


def read_docx(path: Path, progress=None) -> Document:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = docx.Document(str(path))
    except Exception as e:
        raise ExtractionError(f"Could not open this Word file ({e}).") from e
    pars: list[tuple[str, str]] = []
    heading = ""
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") or style == "title":
                heading = text
                pars.append((heading, f"## {text}"))
            else:
                pars.append((heading, text))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells = []
                for c in r.cells:
                    ct = c.text.strip().replace("\n", " ")
                    if not cells or cells[-1] != ct:   # merged cells repeat
                        cells.append(ct)
                rows.append(" | ".join(cells))
            if rows:
                pars.append((heading, "Table:\n" + "\n".join(rows)))
    return Document(path, "Word", _split_into_parts(pars))


def read_pptx(path: Path, progress=None) -> Document:
    from pptx import Presentation

    try:
        prs = Presentation(str(path))
    except Exception as e:
        raise ExtractionError(f"Could not open this PowerPoint file ({e}).") from e
    blocks = []
    for i, slide in enumerate(prs.slides, start=1):
        title, lines = "", []

        def walk(shapes):
            nonlocal title
            for sh in shapes:
                if sh.shape_type == 6 and hasattr(sh, "shapes"):  # group
                    walk(sh.shapes)
                    continue
                if getattr(sh, "has_table", False) and sh.has_table:
                    for r in sh.table.rows:
                        lines.append(" | ".join(c.text.strip() for c in r.cells))
                    continue
                if not getattr(sh, "has_text_frame", False) or not sh.has_text_frame:
                    continue
                is_title = sh.is_placeholder and "title" in str(sh.placeholder_format.type).lower()
                for para in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in para.runs).strip()
                    if not t:
                        continue
                    if is_title and not title:
                        title = t
                    else:
                        lines.append(("  " * para.level) + "• " + t)

        walk(slide.shapes)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append("Speaker notes: " + notes)
        body = "\n".join(lines)
        text = (f"{title}\n{body}" if title else body).strip()
        if text:
            blocks.append(Block(f"Slide {i}", text, title))
    return Document(path, "PowerPoint", blocks)


def _paragraphs_from_plain(text: str, markdown: bool) -> list[tuple[str, str]]:
    pars, heading = [], ""
    for chunk in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if markdown:
            first = chunk.splitlines()[0]
            m = re.match(r"^#{1,6}\s+(.*)", first)
            if m:
                heading = m.group(1).strip()
        pars.append((heading, chunk))
    return pars


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text(path: Path, progress=None) -> Document:
    md = path.suffix.lower() in (".md", ".markdown")
    text = _read_text_file(path)
    return Document(path, "Markdown" if md else "Text", _split_into_parts(_paragraphs_from_plain(text, md)))


def read_rtf(path: Path, progress=None) -> Document:
    from striprtf.striprtf import rtf_to_text

    text = rtf_to_text(_read_text_file(path), errors="ignore")
    return Document(path, "Rich Text", _split_into_parts(_paragraphs_from_plain(text, False)))


def read_odf(path: Path, progress=None) -> Document:
    from odf import teletype, text as odftext
    from odf.draw import Page
    from odf.opendocument import load

    try:
        doc = load(str(path))
    except Exception as e:
        raise ExtractionError(f"Could not open this OpenDocument file ({e}).") from e
    if path.suffix.lower() == ".odp":
        blocks = []
        for i, page in enumerate(doc.getElementsByType(Page), start=1):
            lines = [teletype.extractText(p).strip() for p in page.getElementsByType(odftext.P)]
            body = "\n".join(l for l in lines if l)
            if body:
                blocks.append(Block(f"Slide {i}", body))
        return Document(path, "OpenDocument Slides", blocks)
    pars, heading = [], ""
    for el in doc.text.childNodes:
        name = getattr(el, "qname", (None, ""))[1]
        if name in ("h", "p", "list"):
            t = teletype.extractText(el).strip()
            if not t:
                continue
            if name == "h":
                heading = t
                t = f"## {t}"
            pars.append((heading, t))
    return Document(path, "OpenDocument Text", _split_into_parts(pars))


def read_image(path: Path, progress=None) -> Document:
    from PIL import Image, ImageSequence

    try:
        img = Image.open(path)
    except Exception as e:
        raise ExtractionError(f"Could not open this image ({e}).") from e
    frames = [f.copy() for f in ImageSequence.Iterator(img)][:10]
    blocks = []
    for i, frame in enumerate(frames, start=1):
        if progress:
            progress(i - 1, len(frames), "Recognising text in the image (OCR)")
        # Upscale small phone screenshots: Tesseract likes ~300 dpi text.
        if frame.width < 1500:
            scale = 1500 / frame.width
            frame = frame.resize((int(frame.width * scale), int(frame.height * scale)))
        text = _clean(ocr_image(frame))
        if text:
            label = f"Page {i}" if len(frames) > 1 else "Image"
            blocks.append(Block(label, "\n\n".join(_unwrap(p) for p in text.split("\n\n"))))
    return Document(path, "Image", blocks, ocr_used=len(frames))


def _convert_legacy_office(path: Path) -> Path:
    """Convert .doc/.ppt to .docx/.pptx with MS Office (if installed) or LibreOffice."""
    is_ppt = path.suffix.lower() == ".ppt"
    out_dir = Path(tempfile.mkdtemp(prefix="queryon_"))
    target = out_dir / (path.stem + (".pptx" if is_ppt else ".docx"))

    if sys.platform == "win32":
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                if is_ppt:
                    app = win32com.client.DispatchEx("PowerPoint.Application")
                    pres = app.Presentations.Open(str(path), True, False, False)  # read-only, no window
                    pres.SaveAs(str(target), 24)  # ppSaveAsOpenXMLPresentation
                    pres.Close()
                    app.Quit()
                else:
                    app = win32com.client.DispatchEx("Word.Application")
                    app.Visible = False
                    d = app.Documents.Open(str(path), ReadOnly=True)
                    d.SaveAs2(str(target), FileFormat=16)  # wdFormatXMLDocument
                    d.Close(False)
                    app.Quit()
            finally:
                pythoncom.CoUninitialize()
            if target.exists():
                return target
        except Exception:
            pass

    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office and sys.platform == "win32":
        for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            cand = Path(pf or "") / "LibreOffice" / "program" / "soffice.exe"
            if cand.exists():
                office = str(cand)
    if office:
        fmt = "pptx" if is_ppt else "docx"
        subprocess.run([office, "--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(path)],
                       capture_output=True, timeout=180)
        if target.exists():
            return target

    kind = "PowerPoint" if is_ppt else "Word"
    raise ExtractionError(
        f"Old {path.suffix} files need Microsoft {kind} or LibreOffice installed to open. "
        f"Alternatively, open the file in {kind} and use 'Save As' "
        f"{'.pptx' if is_ppt else '.docx'}, then load that."
    )


def load_document(path: str | Path, progress=None) -> Document:
    """Read any supported file. progress(done, total, message) is optional."""
    path = Path(path)
    if not path.exists():
        raise ExtractionError("File not found.")
    ext = path.suffix.lower()
    if ext not in FILE_TYPES:
        raise ExtractionError(
            f"'{ext or path.name}' files are not supported. Supported: PDF, Word, PowerPoint, "
            "text, Markdown, RTF, OpenDocument and images."
        )
    if ext == ".pdf":
        doc = read_pdf(path, progress)
    elif ext == ".docx":
        doc = read_docx(path, progress)
    elif ext == ".pptx":
        doc = read_pptx(path, progress)
    elif ext in (".doc", ".ppt"):
        if progress:
            progress(0, 1, "Converting old Office file")
        converted = _convert_legacy_office(path)
        doc = (read_pptx if ext == ".ppt" else read_docx)(converted, progress)
        doc.path, doc.kind = path, FILE_TYPES[ext]
    elif ext in (".txt", ".md", ".markdown"):
        doc = read_text(path, progress)
    elif ext == ".rtf":
        doc = read_rtf(path, progress)
    elif ext in (".odt", ".odp"):
        doc = read_odf(path, progress)
    else:
        doc = read_image(path, progress)

    if doc.words < 20:
        raise ExtractionError(
            "Queryon could not find readable text in this file. If it is a photo or scan, "
            "make sure the text is clear and well lit."
        )
    return doc
