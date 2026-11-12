import json
import re

from queryon.document import Block, Document
from queryon.engine import ChatTurn, Engine, make_chunks
from queryon.llm import Backend, strip_thinking
from queryon.export import markdown_to_html, quiz_docx, summary_docx, cards_docx

from pathlib import Path


class FakeBackend(Backend):
    """Stands in for the model: returns predictable text so the logic can be tested."""

    name = "fake"
    context_tokens = 8192

    def __init__(self):
        self.calls = []

    def generate(self, messages, max_tokens=700, temperature=0.3, on_token=None, cancel=None, json_schema=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "schema": json_schema})
        user = messages[-1]["content"]
        if json_schema and "questions" in json_schema["properties"]:
            k = json_schema["properties"]["questions"]["minItems"]
            out = json.dumps({"questions": [
                {"question": f"Question {len(self.calls)}-{i}?", "options": [f"A) right {i}", "wrong 1", "wrong 2", "wrong 3"],
                 "correct_option": 0, "explanation": "Because the text says so."} for i in range(k)]})
        elif json_schema:
            k = json_schema["properties"]["cards"]["minItems"]
            out = json.dumps({"cards": [{"front": f"Term {len(self.calls)}-{i}", "back": "Meaning."} for i in range(k)]})
        else:
            m = re.search(r"about (\d+) words", user)
            n = int(m.group(1)) if m else 30
            out = ("Simple words here. " * (n // 3 + 1)).strip()
        if on_token:
            for piece in out.split(" "):
                on_token(piece + " ")
        return out


def make_doc(pages=6, words_per_page=500):
    blocks = [Block(f"Page {i + 1}", " ".join(f"word{i}_{j}." for j in range(words_per_page))) for i in range(pages)]
    return Document(Path("lecture.pdf"), "PDF", blocks)


def test_chunks_cover_everything_in_order():
    doc = make_doc()
    chunks = make_chunks(doc, 900)
    labels = [b.label for c in chunks for b in c.blocks]
    assert labels == [b.label for b in doc.blocks]
    assert chunks[0].source.startswith("Pages 1")


def test_long_block_is_split():
    doc = Document(Path("a.txt"), "Text", [Block("Part 1", " ".join("w." for _ in range(3000)))])
    chunks = make_chunks(doc, 600)
    assert len(chunks) >= 3


def test_simplify_lengths():
    doc = make_doc()
    for ratio in (0.5, 0.25, 0.1):
        fb = FakeBackend()
        streamed = []
        res = Engine(fb, doc).simplify(ratio, on_token=streamed.append)
        assert res.mode == "rewrite"
        assert abs(res.achieved - ratio) < ratio * 0.5, (ratio, res.achieved)
        assert "".join(streamed).strip()
        assert "_(from Page" in res.text


def test_short_doc_gives_key_points():
    doc = make_doc(pages=1, words_per_page=300)
    res = Engine(FakeBackend(), doc).simplify(0.1)
    assert res.mode == "key points"


def test_chat_includes_document_and_trims_history():
    doc = make_doc(pages=2, words_per_page=200)
    fb = FakeBackend()
    history = [ChatTurn("user", "q " * 2000), ChatTurn("assistant", "a " * 2000)] * 5
    Engine(fb, doc).chat("What is word1_3?", history)
    msgs = fb.calls[0]["messages"]
    assert "[Page 2]" in msgs[0]["content"]
    assert msgs[-1]["content"] == "What is word1_3?"
    assert len(msgs) < 12  # older turns dropped to fit the context


def test_quiz_count_shuffle_and_sources():
    doc = make_doc()
    qs = Engine(FakeBackend(), doc).quiz(10, seed=1)
    assert len(qs) == 10
    assert all(len(q.options) == 4 for q in qs)
    assert all(not q.options[q.answer].startswith("A)") for q in qs)  # prefix stripped
    assert all(q.options[q.answer].startswith("right") for q in qs)
    assert len({q.answer for q in qs}) > 1  # answers not always in slot A
    assert all(q.source.startswith("Page") for q in qs)


def test_flashcards():
    cards = Engine(FakeBackend(), make_doc()).flashcards(12)
    assert len(cards) == 12
    assert len({c.front for c in cards}) == 12


def test_strip_thinking():
    assert strip_thinking("<think>hmm</think>Answer") == "Answer"


def test_markdown_and_exports(tmp_path):
    html = markdown_to_html("## Title\n\n- **bold** item\n- two\n\n_(from Page 2)_\n\nText.")
    assert "<h3>Title</h3>" in html and "<b>bold</b>" in html and 'class="src"' in html
    doc = make_doc()
    eng = Engine(FakeBackend(), doc)
    summary_docx(eng.simplify(0.25), "lecture.pdf", str(tmp_path / "s.docx"))
    quiz_docx(eng.quiz(5), "lecture.pdf", str(tmp_path / "q.docx"))
    cards_docx(eng.flashcards(5), "lecture.pdf", str(tmp_path / "c.docx"))
    assert all((tmp_path / f).stat().st_size > 1000 for f in ("s.docx", "q.docx", "c.docx"))
