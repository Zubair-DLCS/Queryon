"""Turning results into HTML (for display and PDF) and Word files."""

from __future__ import annotations

import html
import re
from datetime import date

from . import APP_NAME, CREDIT_LINE
from .engine import Card, Question, SummaryResult

_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)"), r"<i>\1</i>"),
    (re.compile(r"(?<!\w)_\((.+?)\)_(?!\w)"), r'<span class="src">(\1)</span>'),
]


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    for rx, rep in _INLINE:
        text = rx.sub(rep, text)
    return text


def markdown_to_html(md: str) -> str:
    """A small Markdown subset: headings, bullet/numbered lists, bold, italics, paragraphs."""
    out, list_tag = [], None
    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        m_h = re.match(r"^(#{1,4})\s+(.*)", line)
        m_ul = re.match(r"^\s*[-*•]\s+(.*)", line)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        want = "ul" if m_ul else "ol" if m_ol else None
        if list_tag and want != list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None
        if m_h:
            level = min(4, len(m_h.group(1)) + 1)
            out.append(f"<h{level}>{_inline(m_h.group(2))}</h{level}>")
        elif want:
            if not list_tag:
                out.append(f"<{want}>")
                list_tag = want
            out.append(f"<li>{_inline((m_ul or m_ol).group(1))}</li>")
        elif line.strip():
            cls = ' class="src"' if re.fullmatch(r"_\(.+\)_", line.strip()) else ""
            out.append(f"<p{cls}>{_inline(line)}</p>")
    if list_tag:
        out.append(f"</{list_tag}>")
    return "\n".join(out)


def _page(title: str, body: str, doc_name: str) -> str:
    return f"""<html><head><meta charset="utf-8"><style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 11pt; color: #1f2937; }}
h1 {{ font-size: 18pt; color: #0f766e; margin-bottom: 2px; }}
h2 {{ font-size: 14pt; color: #134e4a; }} h3 {{ font-size: 12pt; color: #134e4a; }}
.meta {{ color: #6b7280; font-size: 9pt; }}
.src {{ color: #9ca3af; font-size: 9pt; }}
.credit {{ color: #6b7280; font-size: 9pt; border-top: 1px solid #e5e7eb; padding-top: 6px; margin-top: 18px; }}
.q {{ font-weight: 600; margin-top: 12px; }}
td {{ padding: 6px; border: 1px solid #d1d5db; vertical-align: top; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="meta">Source: {html.escape(doc_name)} &middot; {date.today():%d %B %Y}</p>
{body}
<p class="credit">Generated with {APP_NAME} &middot; {html.escape(CREDIT_LINE)}</p>
</body></html>"""


def summary_html(s: SummaryResult, doc_name: str) -> str:
    title = f"Simplified version ({int(s.ratio * 100)}%)" if s.mode == "rewrite" else "Key points"
    return _page(title, markdown_to_html(s.text), doc_name)


def quiz_html(questions: list[Question], doc_name: str) -> str:
    parts = []
    for i, q in enumerate(questions, 1):
        opts = "".join(f"<li>{html.escape(o)}</li>" for o in q.options)
        parts.append(f'<p class="q">{i}. {html.escape(q.question)} <span class="src">({q.source})</span></p>'
                     f'<ol type="A">{opts}</ol>')
    parts.append("<h2>Answer key</h2><ol>")
    for q in questions:
        parts.append(f"<li><b>{'ABCD'[q.answer]}</b> — {html.escape(q.explanation)}</li>")
    parts.append("</ol>")
    return _page("Practice quiz", "\n".join(parts), doc_name)


def cards_html(cards: list[Card], doc_name: str) -> str:
    rows = "".join(
        f"<tr><td width='40%'><b>{html.escape(c.front)}</b></td><td>{html.escape(c.back)}"
        f" <span class='src'>({c.source})</span></td></tr>" for c in cards)
    return _page("Flashcards", f"<table cellspacing='0' width='100%'>{rows}</table>", doc_name)


# --------------------------------------------------------------------------- Word export

def _docx_base(title: str, doc_name: str):
    import docx
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading(title, level=0)
    meta = d.add_paragraph(f"Source: {doc_name} · {date.today():%d %B %Y}")
    meta.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    footer = d.sections[0].footer.paragraphs[0]
    footer.text = f"Generated with {APP_NAME} · {CREDIT_LINE}"
    footer.runs[0].font.size = Pt(8)
    return d


def _add_inline_runs(par, text: str) -> None:
    from docx.shared import Pt, RGBColor

    for piece in re.split(r"(\*\*.+?\*\*|_\(.+?\)_)", text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            par.add_run(piece[2:-2]).bold = True
        elif piece.startswith("_(") and piece.endswith(")_"):
            r = par.add_run(piece[1:-1])
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x9C, 0xA3, 0xAF)
        else:
            par.add_run(piece.replace("*", ""))


def summary_docx(s: SummaryResult, doc_name: str, path: str) -> None:
    title = f"Simplified version ({int(s.ratio * 100)}%)" if s.mode == "rewrite" else "Key points"
    d = _docx_base(title, doc_name)
    for line in s.text.split("\n"):
        line = line.rstrip()
        if not line.strip():
            continue
        m_h = re.match(r"^(#{1,4})\s+(.*)", line)
        m_ul = re.match(r"^\s*[-*•]\s+(.*)", line)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m_h:
            d.add_heading(m_h.group(2).replace("*", ""), level=min(3, len(m_h.group(1))))
        elif m_ul:
            _add_inline_runs(d.add_paragraph(style="List Bullet"), m_ul.group(1))
        elif m_ol:
            _add_inline_runs(d.add_paragraph(style="List Number"), m_ol.group(1))
        else:
            _add_inline_runs(d.add_paragraph(), line)
    d.save(path)


def quiz_docx(questions: list[Question], doc_name: str, path: str) -> None:
    d = _docx_base("Practice quiz", doc_name)
    for i, q in enumerate(questions, 1):
        p = d.add_paragraph()
        p.add_run(f"{i}. {q.question}").bold = True
        p.add_run(f"  ({q.source})").italic = True
        for letter, o in zip("ABCD", q.options):
            d.add_paragraph(f"{letter}. {o}").paragraph_format.left_indent = 360000
    d.add_page_break()
    d.add_heading("Answer key", level=1)
    for i, q in enumerate(questions, 1):
        p = d.add_paragraph()
        p.add_run(f"{i}. {'ABCD'[q.answer]}").bold = True
        p.add_run(f" — {q.explanation}")
    d.save(path)


def cards_docx(cards: list[Card], doc_name: str, path: str) -> None:
    d = _docx_base("Flashcards", doc_name)
    t = d.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Front", "Back"
    for c in cards:
        row = t.add_row().cells
        row[0].text = c.front
        row[1].text = f"{c.back} ({c.source})"
    d.save(path)
