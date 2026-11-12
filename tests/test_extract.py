import pytest

from queryon.extract import ExtractionError, find_tesseract, load_document

from .samples import make_all


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    return make_all(tmp_path_factory.mktemp("docs"))


@pytest.mark.parametrize("kind,unit", [
    ("pdf", "Page"), ("docx", "Part"), ("pptx", "Slide"), ("txt", "Part"),
    ("md", "Part"), ("rtf", "Part"), ("odt", "Part"),
])
def test_formats(files, kind, unit):
    doc = load_document(files[kind])
    text = doc.plain_text()
    assert "chloroplasts" in text
    assert "Calvin cycle" in text
    assert doc.blocks[0].label.startswith(unit)
    assert 100 < doc.words < 200


def test_pdf_pages(files):
    doc = load_document(files["pdf"])
    assert [b.label for b in doc.blocks] == ["Page 1", "Page 2"]
    assert "[Page 2]" in doc.labelled_text()


def test_docx_table_and_headings(files):
    doc = load_document(files["docx"])
    assert "Glucose and oxygen" in doc.plain_text()
    assert doc.blocks[0].heading == "Photosynthesis"


def test_pptx_notes(files):
    doc = load_document(files["pptx"])
    assert len(doc.blocks) == 4
    assert "Speaker notes" in doc.blocks[0].text
    assert doc.blocks[0].heading == "Topic 1"


@pytest.mark.skipif(find_tesseract() is None, reason="Tesseract not installed")
@pytest.mark.parametrize("kind", ["png", "scan"])
def test_ocr(files, kind):
    doc = load_document(files[kind])
    assert doc.ocr_used >= 1
    text = doc.plain_text().lower()
    assert "photosynthesis" in text and "chlorophyll" in text


def test_unsupported(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_text("hello")
    with pytest.raises(ExtractionError):
        load_document(p)


def test_empty(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("too short")
    with pytest.raises(ExtractionError):
        load_document(p)


def test_truncate(files):
    doc = load_document(files["txt"])
    short = doc.truncate(60)
    assert short.words <= 60
    assert short.truncated_from == doc.words
    assert doc.truncate(10_000) is doc
