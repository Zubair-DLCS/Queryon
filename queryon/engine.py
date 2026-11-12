"""What Queryon does with a document: chat, simplified versions, quizzes, flashcards.

Small offline models are much better at short, focused jobs than at one long one,
so long outputs are produced part by part, and quiz/flashcard output is forced
into valid JSON with a schema (llama.cpp grammar).
"""

from __future__ import annotations

import json
import random
import re
import threading
from dataclasses import dataclass, field

from .document import Block, Document, count_words
from .llm import Backend

ProgressCB = "Callable[[int, int, str], None]"

STYLE_RULES = (
    "Write in clear, simple English that a first-year student can follow: short sentences, "
    "everyday words, and a brief explanation the first time a technical term appears."
)


# --------------------------------------------------------------------------- chunking

@dataclass
class Chunk:
    blocks: list[Block]

    @property
    def text(self) -> str:
        return "\n\n".join(b.text.strip() for b in self.blocks)

    @property
    def words(self) -> int:
        return sum(b.words for b in self.blocks)

    @property
    def source(self) -> str:
        first, last = self.blocks[0].label, self.blocks[-1].label
        if first == last:
            return first
        kind = first.split(" ")[0]
        if last.split(" ")[0] == kind:
            plural = {"Page": "Pages", "Slide": "Slides", "Part": "Parts"}.get(kind, kind)
            return f"{plural} {first.split(' ', 1)[1]}–{last.split(' ', 1)[1]}"
        return f"{first}–{last}"


def _split_block(b: Block, max_words: int) -> list[Block]:
    if b.words <= max_words:
        return [b]
    # Units are sentences; a sentence that is itself huge is cut by word count.
    units: list[tuple[str, bool]] = []  # (text, starts_new_paragraph)
    for par in re.split(r"\n\s*\n", b.text):
        for k, sent in enumerate(re.split(r"(?<=[.!?])\s+", par.strip())):
            words = sent.split()
            for s in range(0, len(words), max_words):
                units.append((" ".join(words[s:s + max_words]), k == 0 and s == 0))
    pieces, cur, n = [], "", 0
    for text, new_par in units:
        w = count_words(text)
        if cur and n + w > max_words:
            pieces.append(Block(b.label, cur, b.heading))
            cur, n = "", 0
        cur = text if not cur else cur + ("\n\n" if new_par else " ") + text
        n += w
    if cur:
        pieces.append(Block(b.label, cur, b.heading))
    return pieces


def make_chunks(doc: Document, target_words: int) -> list[Chunk]:
    """Group consecutive blocks into chunks of about target_words, never splitting
    mid-paragraph unless a single block is far too long."""
    blocks: list[Block] = []
    for b in doc.blocks:
        blocks.extend(_split_block(b, int(target_words * 1.5)))
    chunks: list[Chunk] = []
    cur: list[Block] = []
    for b in blocks:
        cur_words = sum(x.words for x in cur)
        if cur and cur_words + b.words > target_words * 1.25 and cur_words >= target_words * 0.5:
            chunks.append(Chunk(cur))
            cur = []
        cur.append(b)
    if cur:
        # Fold a tiny tail into the previous chunk.
        if chunks and sum(x.words for x in cur) < target_words * 0.35:
            chunks[-1].blocks.extend(cur)
        else:
            chunks.append(Chunk(cur))
    return chunks


def _trim_to_sentence(text: str) -> str:
    text = text.rstrip()
    if not text or text[-1] in ".!?:)\"'”" or text.endswith(("**", "*")):
        return text
    cut = max(text.rfind(". "), text.rfind(".\n"), text.rfind("? "), text.rfind("! "))
    return text[: cut + 1] if cut > len(text) * 0.6 else text


def _tokens_for_words(words: int) -> int:
    return int(words * 1.45) + 40


def _extract_json(text: str):
    text = text.strip()
    try:
        return json.loads(text, strict=False)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0), strict=False)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- results

@dataclass
class SummaryResult:
    ratio: float
    text: str
    original_words: int
    words: int
    mode: str  # "rewrite" or "key points"

    @property
    def achieved(self) -> float:
        return self.words / max(1, self.original_words)


@dataclass
class Question:
    question: str
    options: list[str]
    answer: int
    explanation: str
    source: str


@dataclass
class Card:
    front: str
    back: str
    source: str


@dataclass
class ChatTurn:
    role: str
    content: str


# --------------------------------------------------------------------------- engine

class Engine:
    def __init__(self, backend: Backend, doc: Document):
        self.backend = backend
        self.doc = doc

    # ----------------------------------------------------------------- chat

    def _chat_system(self) -> str:
        return (
            f"You are Queryon, a patient study assistant helping a student understand the document "
            f"\"{self.doc.name}\". The full document is below; each section starts with a marker "
            f"such as [Page 3] or [Slide 2].\n\n"
            "Rules:\n"
            "- Answer using ONLY the document. If the answer is not in it, say: "
            "\"The document does not cover this.\" and, if useful, say what it does cover.\n"
            "- After each fact, cite where it is, like (Page 3) or (Slide 2).\n"
            f"- {STYLE_RULES}\n"
            "- Keep answers focused: a short paragraph or a few bullet points unless asked for more.\n\n"
            "=== DOCUMENT START ===\n"
            f"{self.doc.labelled_text()}\n"
            "=== DOCUMENT END ==="
        )

    def chat(self, question: str, history: list[ChatTurn], on_token=None, cancel=None, max_answer=700) -> str:
        system = self._chat_system()
        budget = self.backend.context_tokens - self.backend.count_tokens(system) - max_answer - 64
        q_tokens = self.backend.count_tokens(question)
        kept: list[ChatTurn] = []
        used = q_tokens
        for turn in reversed(history[-12:]):  # newest first, until the budget is spent
            t = self.backend.count_tokens(turn.content) + 8
            if used + t > budget:
                break
            kept.insert(0, turn)
            used += t
        if used > budget:
            raise ValueError("That question is too long. Please shorten it.")
        messages = [{"role": "system", "content": system}]
        messages += [{"role": t.role, "content": t.content} for t in kept]
        messages.append({"role": "user", "content": question})
        return self.backend.generate(messages, max_tokens=max_answer, temperature=0.3,
                                     on_token=on_token, cancel=cancel).strip()

    # ----------------------------------------------------------------- simplified versions

    def simplify(self, ratio: float, on_token=None, on_progress=None, cancel=None) -> SummaryResult:
        total = self.doc.words
        target_total = total * ratio
        if target_total < 120:
            return self._key_points(ratio, on_token, cancel)

        # Each part should produce at least ~90 words, or small models lose the thread.
        chunk_words = int(min(1600, max(550, 90 / ratio)))
        chunks = make_chunks(self.doc, chunk_words)
        out_parts: list[str] = []
        prev_tail = ""
        for i, ch in enumerate(chunks):
            if cancel is not None and cancel.is_set():
                break
            if on_progress:
                on_progress(i, len(chunks), f"Rewriting part {i + 1} of {len(chunks)} ({ch.source})")
            target = max(40, round(ch.words * ratio))
            header = f"\n\n_(from {ch.source})_\n\n" if len(chunks) > 1 else ""
            if on_token and header:
                on_token(header)
            context = (f"For context, the previous part of the simplified version ended with:\n\"{prev_tail}\"\n\n"
                       if prev_tail else "")
            messages = [
                {"role": "system", "content": (
                    "You rewrite study material so students can understand it more easily. "
                    f"{STYLE_RULES} Keep every key idea, definition, name, number and example that fits "
                    "in the length you are given, in the original order. Never add facts that are "
                    "not in the text. Keep headings (lines starting with ##) as short headings. "
                    "Output only the rewritten text, with no introduction or comments.")},
                {"role": "user", "content": (
                    f"{context}Rewrite this part of \"{self.doc.name}\" in simpler English in about "
                    f"{target} words (it is now {ch.words} words). "
                    f"Use paragraphs; use bullet points only where the original lists things.\n\n"
                    f"TEXT:\n{ch.text}")},
            ]
            text = self.backend.generate(messages, max_tokens=_tokens_for_words(int(target * 1.35)),
                                         temperature=0.3, on_token=on_token, cancel=cancel)
            text = _trim_to_sentence(text.strip())
            out_parts.append(header + text)
            prev_tail = " ".join(text.split()[-40:])
        if on_progress:
            on_progress(len(chunks), len(chunks), "Done")
        body = "".join(out_parts).strip()
        body_words = count_words(re.sub(r"_\(from [^)]*\)_", "", body))
        return SummaryResult(ratio, body, total, body_words, "rewrite")

    def _key_points(self, ratio, on_token, cancel) -> SummaryResult:
        n = 3 if self.doc.words < 400 else 5
        messages = [
            {"role": "system", "content": f"You help students revise. {STYLE_RULES} Never add facts that are not in the text."},
            {"role": "user", "content": (
                f"The document below is short, so give its {n} most important key points as a bullet "
                f"list (lines starting with '- '), each one sentence, in simple English, followed by "
                f"the source in brackets like (Page 1). Output only the list.\n\n"
                f"DOCUMENT:\n{self.doc.labelled_text()}")},
        ]
        text = self.backend.generate(messages, max_tokens=60 * n + 40, temperature=0.3,
                                     on_token=on_token, cancel=cancel).strip()
        return SummaryResult(ratio, text, self.doc.words, count_words(text), "key points")

    # ----------------------------------------------------------------- quiz & flashcards

    def _allocate(self, n_items: int, chunk_words: int = 600) -> list[tuple[Chunk, int]]:
        chunks = make_chunks(self.doc, chunk_words)
        total = sum(c.words for c in chunks) or 1
        alloc = [max(0, round(n_items * c.words / total)) for c in chunks]
        # Fix rounding so the counts add up exactly.
        while sum(alloc) < n_items:
            alloc[max(range(len(chunks)), key=lambda i: chunks[i].words / (alloc[i] + 1))] += 1
        while sum(alloc) > n_items:
            alloc[max(range(len(chunks)), key=lambda i: alloc[i])] -= 1
        return [(c, k) for c, k in zip(chunks, alloc) if k > 0]

    def quiz(self, n_questions: int = 10, on_progress=None, cancel=None, seed: int | None = None) -> list[Question]:
        rng = random.Random(seed)
        questions: list[Question] = []

        def ask(ch: Chunk, k: int) -> None:
            schema = {
                "type": "object",
                "properties": {"questions": {"type": "array", "minItems": k, "maxItems": k, "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string"}},
                        "correct_option": {"type": "integer", "minimum": 0, "maximum": 3},
                        "explanation": {"type": "string"},
                    },
                    "required": ["question", "options", "correct_option", "explanation"],
                }}},
                "required": ["questions"],
            }
            avoid = [q.question for q in questions if q.source == ch.source]
            avoid_txt = ("\nDo not repeat these questions that were already asked:\n- " + "\n- ".join(avoid)) if avoid else ""
            messages = [
                {"role": "system", "content": (
                    "You write fair multiple-choice questions that test understanding of study material. "
                    "Every question must be answerable from the text alone. Each has exactly 4 options: "
                    "one correct and three plausible but clearly wrong. Do not use 'All of the above' or "
                    "'None of the above'. The explanation says in one simple sentence why the answer is "
                    "correct. Respond with JSON only.")},
                {"role": "user", "content": (
                    f"Write {k} multiple-choice question{'s' if k > 1 else ''} about this text. Cover "
                    f"different ideas, not the same one twice.{avoid_txt}\n\nTEXT:\n{ch.text}")},
            ]
            raw = self.backend.generate(messages, max_tokens=230 * k + 60, temperature=0.5,
                                        cancel=cancel, json_schema=schema)
            for q in (_extract_json(raw) or {}).get("questions", [])[:k]:
                clean = _clean_question(q, ch.source, rng)
                if clean and _is_new(clean.question, [x.question for x in questions]):
                    questions.append(clean)

        self._fill(n_questions, lambda: len(questions), ask, "Writing questions for", on_progress, cancel)
        return questions[:n_questions]

    def flashcards(self, n_cards: int = 12, on_progress=None, cancel=None) -> list[Card]:
        cards: list[Card] = []

        def ask(ch: Chunk, k: int) -> None:
            schema = {
                "type": "object",
                "properties": {"cards": {"type": "array", "minItems": k, "maxItems": k, "items": {
                    "type": "object",
                    "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                    "required": ["front", "back"],
                }}},
                "required": ["cards"],
            }
            avoid = [c.front for c in cards if c.source == ch.source]
            avoid_txt = ("\nThese cards already exist, make different ones:\n- " + "\n- ".join(avoid)) if avoid else ""
            messages = [
                {"role": "system", "content": (
                    "You make revision flashcards from study material. The front is a short question or "
                    "a key term; the back is a short, simple answer or definition (one or two sentences) "
                    "taken from the text. Focus on the most important terms, facts and ideas. "
                    "Respond with JSON only.")},
                {"role": "user", "content": f"Make {k} flashcard{'s' if k > 1 else ''} from this text.{avoid_txt}\n\nTEXT:\n{ch.text}"},
            ]
            raw = self.backend.generate(messages, max_tokens=90 * k + 60, temperature=0.5,
                                        cancel=cancel, json_schema=schema)
            for c in (_extract_json(raw) or {}).get("cards", [])[:k]:
                front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
                if front and back and _is_new(front, [x.front for x in cards]):
                    cards.append(Card(front, back, ch.source))

        self._fill(n_cards, lambda: len(cards), ask, "Making flashcards for", on_progress, cancel)
        # keep document order
        order = {c.source: i for i, (c, _) in enumerate(self._allocate(max(1, n_cards)))}
        cards.sort(key=lambda c: order.get(c.source, 0))
        return cards[:n_cards]

    def _fill(self, n, have, ask, verb, on_progress, cancel, extra_rounds: int = 2) -> None:
        """One pass over the document, then up to extra_rounds top-up calls for items
        lost to duplicates or invalid output."""
        plan = self._allocate(n)
        steps = len(plan)
        for i, (ch, k) in enumerate(plan):
            if cancel is not None and cancel.is_set():
                return
            if on_progress:
                on_progress(i, steps, f"{verb} {ch.source}")
            ask(ch, k)
        chunks = sorted((c for c, _ in plan), key=lambda c: -c.words)
        for r in range(extra_rounds):
            missing = n - have()
            if missing <= 0 or (cancel is not None and cancel.is_set()):
                break
            ch = chunks[r % len(chunks)]
            if on_progress:
                on_progress(steps, steps + 1, f"Adding {missing} more")
            ask(ch, min(missing, 5))
        if on_progress:
            on_progress(1, 1, "Done")


def _is_new(text: str, existing: list[str]) -> bool:
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    t = norm(text)
    return bool(t) and all(norm(e) != t for e in existing)


_PREFIX_RE = re.compile(r"^\s*(?:\(?[A-Da-d1-4][).:]\s+|option\s+[A-Da-d][).:]?\s*)", re.I)


def _clean_question(q: dict, source: str, rng: random.Random) -> Question | None:
    try:
        text = str(q["question"]).strip()
        options = [_PREFIX_RE.sub("", str(o)).strip() for o in q["options"]]
        answer = int(q["correct_option"])
    except (KeyError, TypeError, ValueError):
        return None
    if not text or len(options) != 4 or not 0 <= answer < 4 or any(not o for o in options):
        return None
    if len({o.lower() for o in options}) < 4:
        return None
    correct = options[answer]
    if not any(w in " ".join(options).lower() for w in ("all of the above", "none of the above", "both a")):
        rng.shuffle(options)  # small models put the answer in slot A far too often
    return Question(text, options, options.index(correct), str(q.get("explanation", "")).strip(), source)
