"""Saves generated summaries, quizzes and flashcards so reopening a document is instant."""

from __future__ import annotations

import json
from dataclasses import asdict

from .config import cache_dir
from .engine import Card, Question, SummaryResult


class ResultCache:
    def __init__(self, fingerprint: str, model_name: str):
        safe_model = "".join(c if c.isalnum() or c in "-_." else "_" for c in model_name)[:60]
        self.path = cache_dir() / f"{fingerprint}__{safe_model}.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass

    def get_summary(self, ratio: float) -> SummaryResult | None:
        d = self.data.get("summaries", {}).get(str(ratio))
        return SummaryResult(**d) if d else None

    def put_summary(self, s: SummaryResult) -> None:
        self.data.setdefault("summaries", {})[str(s.ratio)] = asdict(s)
        self._save()

    def get_quiz(self) -> list[Question] | None:
        d = self.data.get("quiz")
        return [Question(**q) for q in d] if d else None

    def put_quiz(self, qs: list[Question]) -> None:
        self.data["quiz"] = [asdict(q) for q in qs]
        self._save()

    def get_cards(self) -> list[Card] | None:
        d = self.data.get("cards")
        return [Card(**c) for c in d] if d else None

    def put_cards(self, cards: list[Card]) -> None:
        self.data["cards"] = [asdict(c) for c in cards]
        self._save()
