"""Drives the real window headlessly with a scripted stand-in model and saves screenshots.
Usage: QT_QPA_PLATFORM=offscreen python scripts/ui_smoke.py OUT_DIR"""

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from queryon.llm import Backend
from queryon.ui.main_window import MainWindow
from queryon.ui.style import QSS
from tests.samples import make_all

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screens")
OUT.mkdir(parents=True, exist_ok=True)


class DemoBackend(Backend):
    name = "demo-model"
    context_tokens = 8192
    qi = 0

    def generate(self, messages, max_tokens=700, temperature=0.3, on_token=None, cancel=None, json_schema=None):
        user = messages[-1]["content"]
        if json_schema and "questions" in json_schema["properties"]:
            k = json_schema["properties"]["questions"]["minItems"]
            bank = [("Where in the plant cell does photosynthesis mainly take place?",
                     ["In the chloroplasts", "In the nucleus", "In the cell wall", "In the roots"],
                     "The text says photosynthesis takes place inside chloroplasts in the leaves."),
                    ("Which gas do plants release during photosynthesis?",
                     ["Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen"],
                     "Oxygen is released as a by-product."),
                    ("What does chlorophyll do?", ["Absorbs sunlight", "Stores water", "Makes soil", "Releases carbon dioxide"],
                     "Chlorophyll is the green pigment that absorbs sunlight."),
                    ("What does the Calvin cycle build?", ["Glucose", "Oxygen", "Chlorophyll", "Water"],
                     "The Calvin cycle builds glucose from carbon dioxide."),
                    ("Why do farmers use greenhouses?", ["To control the factors that limit photosynthesis", "To keep birds away",
                     "To reduce sunlight", "To remove oxygen"], "Greenhouses control light, temperature and CO2.")]
            out = json.dumps({"questions": [{"question": q, "options": o, "correct_option": 0, "explanation": e}
                                            for q, o, e in [bank[(self.qi + j) % len(bank)] for j in range(k)]]})
            self.qi += k
        elif json_schema:
            k = json_schema["properties"]["cards"]["minItems"]
            bank = [("Chlorophyll", "The green pigment in plants that absorbs sunlight."),
                    ("Calvin cycle", "The stage that builds glucose from carbon dioxide, in the stroma."),
                    ("Chloroplast", "The small part of a plant cell where photosynthesis happens.")]
            out = json.dumps({"cards": [{"front": f, "back": b} for f, b in (bank * 5)[:k]]})
        elif "Rewrite this part" in user:
            out = ("Plants make their own food using sunlight. This process is called **photosynthesis**. "
                   "It happens mostly in the leaves, inside tiny parts called chloroplasts. A green colour "
                   "called chlorophyll catches the sunlight. The plant takes in carbon dioxide from the air "
                   "and water from the soil, and gives out oxygen.")
        elif "key points" in user:
            out = "- Plants use sunlight to make food (Page 1)\n- Chlorophyll absorbs light (Page 1)\n- Light, temperature and CO₂ limit the rate (Page 2)"
        else:
            out = ("**Photosynthesis** is how plants make their own food from sunlight (Page 1).\n\n"
                   "- It happens in the **chloroplasts**, mostly in the leaves (Page 1).\n"
                   "- Plants take in carbon dioxide and water, and give out oxygen (Page 1).\n"
                   "- Two stages: light reactions make ATP and NADPH, then the Calvin cycle builds glucose (Page 2).")
        for piece in re.findall(r"\S+\s*", out):
            if cancel is not None and cancel.is_set():
                break
            if on_token:
                on_token(piece)
            time.sleep(0.002)
        return out


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_idle(app, win, timeout=20):
    end = time.time() + timeout
    pump(app, 0.2)
    while win.busy and time.time() < end:
        pump(app, 0.05)
    pump(app, 0.4)


app = QApplication(sys.argv)
app.setStyleSheet(QSS)
win = MainWindow()
win.prepare_backend = lambda interactive=True: None  # no real model in this test
win.resize(1280, 820)
win.show()
pump(app, 0.5)
win.grab().save(str(OUT / "0_start.png"))

win.backend = DemoBackend()
win._set_model_label("Standard — Llama 3.2 3B<br><small>offline · ready</small>", "#15803d")
files = make_all(Path(tempfile.mkdtemp()))
import docx as _docx
from tests.samples import PARAS
long_path = Path(tempfile.mkdtemp()) / "Biology Lecture 4 - Photosynthesis.docx"
d = _docx.Document()
for i in range(6):
    d.add_heading(["Introduction", "Pigments", "Light reactions", "Calvin cycle", "Limiting factors", "Summary"][i], 1)
    for p in PARAS * 2:
        d.add_paragraph(p)
d.save(long_path)
files["long"] = long_path
win.open_document(str(files["long"]))
wait_idle(app, win)
assert win.doc is not None and win.engine is not None, "document did not open"

win.chat.ask("Explain the main idea in simple words")
wait_idle(app, win)
assert win.chat.history[-1].role == "assistant"
win.grab().save(str(OUT / "1_chat.png"))

win.tabs.setCurrentWidget(win.summary)
win.summary.group.button(0).click()
win.summary.generate()
wait_idle(app, win)
assert win.summary.result is not None
win.grab().save(str(OUT / "2_simplify.png"))

win.tabs.setCurrentWidget(win.quiz)
win.quiz.count.setCurrentIndex(0)
win.quiz.generate()
wait_idle(app, win)
assert len(win.quiz.questions) == 5
q = win.quiz.questions[0]
win.quiz.choose((q.answer + 1) % 4)  # pick a wrong answer to show feedback
pump(app, 0.3)
win.grab().save(str(OUT / "3_quiz.png"))

win.tabs.setCurrentWidget(win.cards)
win.cards.generate()
wait_idle(app, win)
assert len(win.cards.cards) >= 3
win.cards.flip()
pump(app, 0.3)
win.grab().save(str(OUT / "4_flashcards.png"))

win.tabs.setCurrentWidget(win.document_view)
pump(app, 0.3)
win.grab().save(str(OUT / "5_original.png"))

# exports
from queryon.ui.main_window import save_pdf
from queryon import export as ex

save_pdf(ex.quiz_html(win.quiz.questions, win.doc.name), str(OUT / "quiz.pdf"))
ex.summary_docx(win.summary.result, win.doc.name, str(OUT / "summary.docx"))

# reopening the same document restores cached results instantly
win.open_document(str(files["long"]))
wait_idle(app, win)
assert win.summary.result is not None and len(win.quiz.questions) == 5
print("UI smoke test passed; screenshots in", OUT)
