"""`Queryon.exe --selftest report.txt` checks that the packaged app has everything it needs.
Used by the Windows build pipeline; also handy for diagnosing a lab PC."""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def run(report_path: str) -> int:
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"PASS  {name}" + (f": {detail}" if detail else ""))
        except Exception:
            ok = False
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")

    from . import cpu

    build = cpu.select_llama_build()
    check("cpu", lambda: f"avx2={cpu.has_avx2()} llama build={build}")
    def llama():
        import llama_cpp

        info = llama_cpp.llama_print_system_info().decode(errors="replace")
        return f"{llama_cpp.__version__} | {info.strip()[:300]}"

    check("llama_cpp", llama)
    check("PySide6", lambda: __import__("PySide6").__version__)
    check("pymupdf", lambda: __import__("pymupdf").VersionBind)
    for mod in ("docx", "pptx", "striprtf.striprtf", "odf.opendocument", "psutil", "requests", "jinja2"):
        check(mod, lambda m=mod: __import__(m) and "")

    def ocr():
        from PIL import Image, ImageDraw, ImageFont

        from .extract import find_tesseract, ocr_image

        exe = find_tesseract()
        if not exe:
            raise RuntimeError("tesseract not found")
        img = Image.new("RGB", (1600, 300), "white")
        font = None
        for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(name, 48)
                break
            except OSError:
                continue
        font = font or ImageFont.load_default()
        ImageDraw.Draw(img).text((40, 60), "Photosynthesis happens inside the chloroplasts of plant leaves", fill="black", font=font)
        ImageDraw.Draw(img).text((40, 160), "and chlorophyll absorbs the light energy from the sun today", fill="black", font=font)
        text = ocr_image(img)
        if "chloroplasts" not in text.lower():
            raise RuntimeError(f"OCR result unexpected: {text!r}")
        return exe

    check("tesseract OCR", ocr)

    def docs():
        import docx

        from .extract import load_document

        p = Path(tempfile.mkdtemp()) / "t.docx"
        d = docx.Document()
        d.add_paragraph("Queryon self test. " * 10)
        d.save(p)
        return f"{load_document(p).words} words"

    check("read .docx", docs)

    lines.append("RESULT: " + ("OK" if ok else "FAILED"))
    Path(report_path).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "selftest.txt"))
