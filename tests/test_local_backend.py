"""Exercises the real llama.cpp code path with a tiny random model (no download needed).
Quality is meaningless here; this checks loading, streaming, stopping and JSON output."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

llama_cpp = pytest.importorskip("llama_cpp")
pytest.importorskip("gguf")

from queryon.engine import Engine
from queryon.llm import Cancelled, LocalBackend

from .test_engine import make_doc


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    path = tmp_path_factory.mktemp("m") / "tiny.gguf"
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_tiny_gguf.py"
    subprocess.run([sys.executable, str(script), str(path)], check=True, capture_output=True)
    b = LocalBackend(str(path), threads=2, n_ctx=4096)
    yield b
    b.close()


def test_stream_and_tokens(backend):
    seen = []
    out = backend.generate([{"role": "user", "content": "hello"}], max_tokens=12, on_token=seen.append)
    assert isinstance(out, str)
    assert backend.count_tokens("the answer") > 0


def test_cancel(backend):
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        backend.generate([{"role": "user", "content": "hello"}], max_tokens=50, cancel=ev)


def test_json_schema_forces_valid_json(backend):
    schema = {"type": "object", "properties": {"cards": {"type": "array", "minItems": 1, "maxItems": 1, "items": {
        "type": "object", "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
        "required": ["front", "back"]}}}, "required": ["cards"]}
    out = backend.generate([{"role": "user", "content": "cards"}], max_tokens=300, json_schema=schema)
    data = json.loads(out, strict=False)  # random weights, yet the grammar guarantees structure
    assert len(data["cards"]) == 1


def test_engine_end_to_end(backend):
    # The tiny model's tokenizer is character-level, so keep the document small.
    doc = make_doc(pages=2, words_per_page=25)
    eng = Engine(backend, doc)
    assert isinstance(eng.chat("hi", [], max_answer=16), str)
    assert eng.simplify(0.5).original_words == doc.words
    qs = eng.quiz(2)  # grammar-constrained; random weights may still yield duplicate options
    assert isinstance(qs, list)
