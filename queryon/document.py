"""The in-memory representation of a loaded document."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

_WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


@dataclass
class Block:
    """One locatable piece of the document: a page, a slide, or a part of a flowing text."""

    label: str            # e.g. "Page 3", "Slide 7", "Part 2"
    text: str
    heading: str = ""     # nearest heading, if the format has them

    @property
    def words(self) -> int:
        return count_words(self.text)


@dataclass
class Document:
    path: Path
    kind: str                         # "PDF", "Word", "PowerPoint", ...
    blocks: list[Block]
    ocr_used: int = 0                 # number of pages/images read with OCR
    notes: list[str] = field(default_factory=list)
    truncated_from: int = 0           # original word count if we cut it

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def words(self) -> int:
        return sum(b.words for b in self.blocks)

    @property
    def unit_name(self) -> str:
        labels = {b.label.split(" ")[0] for b in self.blocks}
        return labels.pop() if len(labels) == 1 else "Part"

    def labelled_text(self) -> str:
        """Document text with [Page n] markers, used as the model's reading material."""
        out = []
        for b in self.blocks:
            head = f"[{b.label}]" + (f" {b.heading}" if b.heading and b.heading not in b.text[:200] else "")
            out.append(f"{head}\n{b.text.strip()}")
        return "\n\n".join(out)

    def plain_text(self) -> str:
        return "\n\n".join(b.text.strip() for b in self.blocks)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.labelled_text().encode("utf-8")).hexdigest()[:24]

    def truncate(self, max_words: int) -> "Document":
        """Keep the first max_words words, cutting the last block at a sentence if possible."""
        total = self.words
        if total <= max_words:
            return self
        kept: list[Block] = []
        budget = max_words
        for b in self.blocks:
            if budget <= 0:
                break
            if b.words <= budget:
                kept.append(b)
                budget -= b.words
                continue
            words = _WORD_RE.findall(b.text)[:budget]
            cut = " ".join(words)
            end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
            if end > len(cut) * 0.5:
                cut = cut[: end + 1]
            kept.append(Block(b.label, cut, b.heading))
            budget = 0
        return Document(self.path, self.kind, kept, self.ocr_used, list(self.notes), truncated_from=total)
