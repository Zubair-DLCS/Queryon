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

RESET = "\x00"  # streamed-token prefix meaning "replace the text shown so far"

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


def _json_items(text: str, key: str) -> list[dict]:
    """Items of the array `key`, salvaging complete items even if the JSON was cut off
    (which happens when a model runs out of output budget mid-answer)."""
    data = _extract_json(text)
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [x for x in data[key] if isinstance(x, dict)]
    m = re.search(r'"%s"\s*:\s*\[' % re.escape(key), text)
    if not m:
        return []
    dec = json.JSONDecoder(strict=False)
    items, pos = [], m.end()
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            obj, pos = dec.raw_decode(text, pos)
        except ValueError:
            break
        if isinstance(obj, dict):
            items.append(obj)
    return items


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

    def _cite_example(self) -> str:
        labels = [b.label for b in self.doc.blocks]
        return labels[min(1, len(labels) - 1)]

    def _chat_system(self) -> str:
        ex = self._cite_example()
        return (
            f"You are Queryon, a patient study assistant helping a student understand the document "
            f"\"{self.doc.name}\". The full document is below; each section starts with a marker "
            f"in square brackets, such as [{ex}].\n\n"
            "Rules:\n"
            "- Answer using ONLY the document. If the answer is not in it, say: "
            "\"The document does not cover this.\" and, if useful, say what it does cover.\n"
            f"- After each fact, cite the marker of the section it comes from in round brackets, "
            f"like ({ex}). Use only markers that appear in the document.\n"
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
        """on_token receives streamed text; a token starting with RESET replaces everything
        shown so far (used when a part is shortened after it was written)."""
        total = self.doc.words
        target_total = total * ratio
        if target_total < 120:
            return self._key_points(ratio, on_token, cancel)

        # Small models follow "about N words" much better for short outputs, so parts are
        # small; each part should still produce at least ~90 words to keep the thread.
        chunk_words = int(min(1600, max(350, 90 / ratio)))
        chunks = make_chunks(self.doc, chunk_words)
        out_parts: list[str] = []
        for i, ch in enumerate(chunks):
            if cancel is not None and cancel.is_set():
                break
            if on_progress:
                on_progress(i, len(chunks), f"Rewriting part {i + 1} of {len(chunks)} ({ch.source})")
            target = max(40, round(ch.words * ratio))
            header = f"\n\n_(from {ch.source})_\n\n" if len(chunks) > 1 else ""
            if on_token and header:
                on_token(header)
            sentences = max(2, round(target / 16))
            messages = [
                {"role": "system", "content": (
                    "You rewrite study material so students can understand it more easily. "
                    f"{STYLE_RULES} Keep the most important ideas, definitions, names and numbers, in the "
                    "original order. Never add facts or examples that are not in the text. Keep headings "
                    "(lines starting with ##) as short headings. Write in paragraphs; use a bullet list "
                    "only where the original text has a list. Stay within the word limit. "
                    "Output only the rewritten text, with no introduction or comments.")},
                {"role": "user", "content": (
                    f"Rewrite this part of \"{self.doc.name}\" in simpler English. It is now "
                    f"{ch.words} words; your version must be about {target} words "
                    f"(roughly {sentences} short sentences){' - leave out minor details' if ratio < 0.5 else ''}. "
                    f"Use only information from this text.\n\nTEXT:\n{ch.text}")},
            ]
            text = self.backend.generate(messages, max_tokens=_tokens_for_words(int(target * 1.45)),
                                         temperature=0.3, on_token=on_token, cancel=cancel)
            text = _trim_to_sentence(text.strip())
            if count_words(text) > target * 1.25 and not (cancel is not None and cancel.is_set()):
                if on_progress:
                    on_progress(i, len(chunks), f"Shortening part {i + 1} of {len(chunks)}")
                text = self._shorten(text, target, cancel) or text
                if on_token:
                    on_token(RESET + "".join(out_parts) + header + text)
            out_parts.append(header + text)
        if on_progress:
            on_progress(len(chunks), len(chunks), "Done")
        body = "".join(out_parts).strip()
        body_words = count_words(re.sub(r"_\(from [^)]*\)_", "", body))
        return SummaryResult(ratio, body, total, body_words, "rewrite")

    def _shorten(self, text: str, target: int, cancel) -> str:
        messages = [
            {"role": "system", "content": (
                f"You shorten text for students. {STYLE_RULES} Keep the most important facts, drop "
                "minor details and repetition, never add anything new. Keep ## headings. "
                "Output only the shortened text.")},
            {"role": "user", "content": f"Shorten this to about {target} words:\n\n{text}"},
        ]
        out = self.backend.generate(messages, max_tokens=_tokens_for_words(int(target * 1.3)),
                                    temperature=0.2, cancel=cancel)
        out = _trim_to_sentence(out.strip())
        return out if count_words(out) >= target * 0.4 else ""

    def _key_points(self, ratio, on_token, cancel) -> SummaryResult:
        n = 3 if self.doc.words < 400 else 5
        messages = [
            {"role": "system", "content": f"You help students revise. {STYLE_RULES} Never add facts that are not in the text."},
            {"role": "user", "content": (
                f"The document below is short, so give ONLY its {n} most important key points as a "
                f"bullet list of exactly {n} lines starting with '- ', each one short sentence in simple "
                f"English, followed by its section marker in round brackets, like ({self._cite_example()}). "
                f"Output only the list.\n\n"
                f"DOCUMENT:\n{self.doc.labelled_text()}")},
        ]
        text = self.backend.generate(messages, max_tokens=50 * n + 40, temperature=0.3,
                                     on_token=on_token, cancel=cancel).strip()
        bullets = [l for l in text.splitlines() if re.match(r"^\s*([-*•]|\d+[.)])\s+", l)]
        if len(bullets) > n:  # small models often ignore the count
            text = "\n".join(bullets[:n])
            if on_token:
                on_token(RESET + text)
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

    def _item_chunk_words(self, n_items: int) -> int:
        # About two items per section, so each question points to a specific place.
        return int(min(600, max(200, self.doc.words * 2 / max(1, n_items))))

    def quiz(self, n_questions: int = 10, on_progress=None, cancel=None, seed: int | None = None) -> list[Question]:
        rng = random.Random(seed)
        questions: list[Question] = []

        def ask(ch: Chunk, k: int) -> None:
            # The model writes the right answer as text, not as an option number: small models
            # are unreliable at pointing to "option 2" but good at stating the answer itself.
            schema = {
                "type": "object",
                "properties": {"questions": {"type": "array", "minItems": k, "maxItems": k, "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "correct_answer": {"type": "string"},
                        "wrong_answers": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
                        "explanation": {"type": "string"},
                    },
                    "required": ["question", "correct_answer", "wrong_answers", "explanation"],
                }}},
                "required": ["questions"],
            }
            avoid = [q.question for q in questions]
            avoid_txt = ("\nThese questions were already asked; ask about different facts:\n- " + "\n- ".join(avoid)) if avoid else ""
            messages = [
                {"role": "system", "content": (
                    "You write fair multiple-choice questions that test understanding of study material. "
                    "Every question must be answerable from the text alone. For each question give the "
                    "correct answer, then three wrong answers that sound plausible but are clearly wrong "
                    "according to the text. Answers are short phrases. Do not use 'All of the above' or "
                    "'None of the above'. The explanation says in one simple sentence why the correct "
                    "answer is right, using the text. Respond with JSON only.")},
                {"role": "user", "content": (
                    f"Write {k} multiple-choice question{'s' if k > 1 else ''} about this text, each about "
                    f"a different fact.{avoid_txt}\n\nTEXT:\n{ch.text}")},
            ]
            raw = self.backend.generate(messages, max_tokens=280 * k + 120, temperature=0.5,
                                        cancel=cancel, json_schema=schema)
            for q in _json_items(raw, "questions")[:k]:
                clean = _clean_question(q, ch.source, rng)
                if clean and _is_new(clean.question, [x.question for x in questions]):
                    questions.append(clean)

        self._fill(n_questions, lambda: len(questions), ask, "Writing questions for", on_progress, cancel,
                   chunk_words=self._item_chunk_words(n_questions))
        order = {c.source: i for i, c in enumerate(make_chunks(self.doc, self._item_chunk_words(n_questions)))}
        questions.sort(key=lambda q: order.get(q.source, 0))
        return questions[:n_questions]

    def flashcards(self, n_cards: int = 12, on_progress=None, cancel=None) -> list[Card]:
        cards: list[Card] = []

        def ask(ch: Chunk, k: int) -> None:
            schema = {
                "type": "object",
                "properties": {"cards": {"type": "array", "minItems": k, "maxItems": k, "items": {
                    "type": "object",
                    "properties": {"front": {"type": "string", "maxLength": 120},
                                   "back": {"type": "string", "maxLength": 320}},
                    "required": ["front", "back"],
                }}},
                "required": ["cards"],
            }
            avoid = [c.front for c in cards]
            avoid_txt = ("\nThese cards already exist; make cards about other terms:\n- " + "\n- ".join(avoid)) if avoid else ""
            messages = [
                {"role": "system", "content": (
                    "You make revision flashcards from study material. The front is a key term or a "
                    "short question. The back is a short answer in your own simple words: ONE sentence, "
                    "under 25 words. Do not copy whole sentences or paragraphs from the text. Focus on the "
                    "most important terms, facts and ideas. Respond with JSON only.")},
                {"role": "user", "content": f"Make {k} flashcard{'s' if k > 1 else ''} from this text.{avoid_txt}\n\nTEXT:\n{ch.text}"},
            ]
            raw = self.backend.generate(messages, max_tokens=150 * k + 100, temperature=0.5,
                                        cancel=cancel, json_schema=schema)
            for c in _json_items(raw, "cards")[:k]:
                front = str(c.get("front", "")).strip()
                back = _shorten_answer(str(c.get("back", "")).strip())
                if front and back and _is_new(front, [x.front for x in cards]):
                    cards.append(Card(front, back, ch.source))

        cw = self._item_chunk_words(n_cards)
        self._fill(n_cards, lambda: len(cards), ask, "Making flashcards for", on_progress, cancel, chunk_words=cw)
        order = {c.source: i for i, c in enumerate(make_chunks(self.doc, cw))}
        cards.sort(key=lambda c: order.get(c.source, 0))
        return cards[:n_cards]

    def _fill(self, n, have, ask, verb, on_progress, cancel, chunk_words: int = 600, extra_rounds: int = 4) -> None:
        """One pass over the document, then up to extra_rounds top-up calls for items
        lost to duplicates or invalid output."""
        plan = self._allocate(n, chunk_words)
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
            ask(ch, min(missing, 4))
        if on_progress:
            on_progress(1, 1, "Done")


_STOP = set("a an the of in on at to for from by with and or is are was were be been it its this that "
            "what which who whom how why when where does do did can could would should into as than "
            "then their there these those about main primarily mainly part".split())


def _content_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 1}


def _is_new(text: str, existing: list[str]) -> bool:
    """False if text repeats an existing item, even when reworded."""
    t = _content_words(text)
    if not t:
        return False
    for e in existing:
        o = _content_words(e)
        if o and len(t & o) / len(t | o) >= 0.6:
            return False
    return True


def _shorten_answer(text: str, max_words: int = 35) -> str:
    """Flashcard backs: keep the first sentence or two, at most max_words words."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out = sentences[0]
    if len(sentences) > 1 and count_words(out) < 12:
        out += " " + sentences[1]
    words = out.split()
    if len(words) > max_words:
        out = " ".join(words[:max_words]).rstrip(",;:") + "…"
    return out


_PREFIX_RE = re.compile(r"^\s*(?:\(?[A-Da-d1-4][).:]\s+|option\s+[A-Da-d][).:]?\s*)", re.I)


def _clean_question(q: dict, source: str, rng: random.Random) -> Question | None:
    try:
        text = str(q["question"]).strip()
        correct = _PREFIX_RE.sub("", str(q["correct_answer"])).strip()
        wrong = [_PREFIX_RE.sub("", str(o)).strip() for o in q["wrong_answers"]]
    except (KeyError, TypeError):
        return None
    options = [correct] + wrong
    if not text or len(options) != 4 or any(not o for o in options):
        return None
    if len({o.lower().rstrip(".") for o in options}) < 4:
        return None  # a "wrong" answer that equals the right one
    if any(w in " ".join(options).lower() for w in ("all of the above", "none of the above")):
        return None
    rng.shuffle(options)
    return Question(text, options, options.index(correct), str(q.get("explanation", "")).strip(), source)
