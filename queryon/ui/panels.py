"""The five tabs: Chat, Simplify, Quiz, Flashcards, Document."""

from __future__ import annotations

import html
import random
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ..engine import ChatTurn
from ..export import markdown_to_html
from .style import BAD, CHAT_CSS, GOOD, MUTED


def _button(text: str, name: str | None = None, tip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


def _cite_html(text_html: str) -> str:
    return re.sub(r"\(((?:Pages?|Slides?|Parts?|Image)[^()]{0,30})\)", r'<span class="src">(\1)</span>', text_html)


class Panel(QWidget):
    """Base: knows the main window (self.app) and reacts to busy/doc changes."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        app.busy_changed.connect(self.on_busy)
        app.document_changed.connect(self.on_document)

    def on_busy(self, busy: bool) -> None:
        pass

    def on_document(self) -> None:
        pass


# =========================================================================== Chat

class ChatPanel(Panel):
    STARTERS = [
        ("Main idea", "Explain the main idea in simple words."),
        ("Key terms", "What are the key terms and what do they mean?"),
        ("Real-life example", "Give me a real-life example of the main concept."),
        ("Exam focus", "What should I focus on for an exam?"),
        ("Explain like I'm new", "Explain this document to someone who has never studied the topic."),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.history: list[ChatTurn] = []
        self.streaming = ""
        self._dirty = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.document().setDefaultStyleSheet(CHAT_CSS)
        lay.addWidget(self.view, 1)

        self.chips = QWidget()
        chips_lay = QHBoxLayout(self.chips)
        chips_lay.setContentsMargins(0, 4, 0, 4)
        tryl = QLabel("Try:")
        tryl.setObjectName("muted")
        chips_lay.addWidget(tryl)
        for label, q in self.STARTERS:
            b = _button(label, "chip", q)
            b.clicked.connect(lambda _=False, q=q: self.ask(q))
            chips_lay.addWidget(b)
        chips_lay.addStretch(1)
        lay.addWidget(self.chips)

        row = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Ask anything about the document…  (Enter to send, Shift+Enter for a new line)")
        self.input.setFixedHeight(64)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        col = QVBoxLayout()
        self.send = _button("Send", "primary")
        self.send.clicked.connect(lambda: self.ask(self.input.toPlainText()))
        self.stop = _button("Stop", "danger")
        self.stop.clicked.connect(self.app.cancel_current)
        self.stop.hide()
        self.clear = _button("New chat")
        self.clear.clicked.connect(self.reset)
        col.addWidget(self.send)
        col.addWidget(self.stop)
        col.addWidget(self.clear)
        row.addLayout(col)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._flush)
        self.render()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
                self.ask(self.input.toPlainText())
                return True
        return super().eventFilter(obj, event)

    def on_document(self):
        self.reset()

    def on_busy(self, busy):
        self.send.setEnabled(not busy and self.app.doc is not None)
        self.chips.setEnabled(not busy and self.app.doc is not None)

    def reset(self):
        self.history.clear()
        self.streaming = ""
        self.render()

    def render(self):
        if self.app.doc is None:
            body = (f"<p style='color:{MUTED}; margin-top:40px' align='center'>"
                    "Open a document to start chatting with it.</p>")
        elif not self.history and not self.streaming:
            body = (f"<p style='color:{MUTED}; margin-top:30px' align='center'>Ask a question about "
                    f"<b>{html.escape(self.app.doc.name)}</b>.<br>Answers come only from the document, "
                    "with page references so you can check them.</p>")
        else:
            parts = []
            for t in self.history:
                parts.append(self._turn_html(t.role, t.content))
            if self.streaming:
                parts.append(self._turn_html("assistant", self.streaming + " ▌"))
            body = "".join(parts)
        self.view.setHtml(f"<html><body>{body}</body></html>")
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    @staticmethod
    def _turn_html(role: str, content: str) -> str:
        if role == "user":
            text = html.escape(content).replace(chr(10), "<br>")
            return ("<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:10px'><tr>"
                    "<td width='25%'></td><td bgcolor='#ccfbf1' style='padding:9px 13px; border-radius:10px'>"
                    f"{text}</td></tr></table>")
        return ("<p class='who'>QUERYON</p>"
                f"<div class='bot'>{_cite_html(markdown_to_html(content))}</div>")

    def _flush(self):
        if self._dirty:
            self._dirty = False
            self.render()

    def ask(self, question: str):
        question = question.strip()
        if not question or self.app.busy or self.app.doc is None:
            return
        if not self.app.ensure_engine():
            return
        self.input.clear()
        past = list(self.history)
        self.history.append(ChatTurn("user", question))
        self.streaming = ""
        self.render()
        engine = self.app.engine

        def work(job):
            return engine.chat(question, past, on_token=job.emit_token, cancel=job.cancel)

        def on_token(t):
            self.streaming += t
            self._dirty = True

        def finish(answer=None):
            self.timer.stop()
            text = answer if isinstance(answer, str) else self.streaming
            if text.strip():
                self.history.append(ChatTurn("assistant", text.strip()))
            self.streaming = ""
            self.send.show(); self.stop.hide()
            self.render()

        def failed(msg):
            self.history.append(ChatTurn("assistant", f"⚠ {msg}"))
            finish("")

        self.send.hide(); self.stop.show()
        self.timer.start()
        self.app.run(work, "Thinking…", token=on_token, done=finish, failed=failed,
                     cancelled=lambda: finish(None))


# =========================================================================== Simplify

class SummaryPanel(Panel):
    RATIOS = [(0.5, "50%", "About half the length. Keeps most details."),
              (0.25, "25%", "A quarter of the length. Main ideas and key details."),
              (0.10, "10%", "A tenth of the length. Only the core ideas.")]

    def __init__(self, app):
        super().__init__(app)
        self.result = None
        self.buffer = ""
        self._dirty = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        top.addWidget(QLabel("Length of the simplified version:"))
        self.group = QButtonGroup(self)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for i, (ratio, label, tip) in enumerate(self.RATIOS):
            b = _button(label, "segment", tip)
            b.setCheckable(True)
            b.setChecked(i == 1)
            self.group.addButton(b, i)
            seg.addWidget(b)
        top.addLayout(seg)
        top.addSpacing(10)
        self.go = _button("Simplify", "primary")
        self.go.clicked.connect(self.generate)
        self.stop = _button("Stop", "danger")
        self.stop.clicked.connect(self.app.cancel_current)
        self.stop.hide()
        top.addWidget(self.go)
        top.addWidget(self.stop)
        top.addStretch(1)
        lay.addLayout(top)

        self.explain = _muted("Queryon rewrites the document part by part in simpler English, "
                              "keeping the order and the key facts. Grey notes show which pages each part came from.")
        lay.addWidget(self.explain)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.progress_label = _muted("")
        self.progress_label.hide()
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)

        self.view = QTextBrowser()
        self.view.document().setDefaultStyleSheet(CHAT_CSS)
        lay.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.stats = _muted("")
        bottom.addWidget(self.stats, 1)
        self.copy = _button("Copy")
        self.copy.clicked.connect(self.copy_text)
        self.to_word = _button("Save as Word")
        self.to_word.clicked.connect(lambda: self.app.export("summary", "docx", self.result))
        self.to_pdf = _button("Save as PDF")
        self.to_pdf.clicked.connect(lambda: self.app.export("summary", "pdf", self.result))
        for b in (self.copy, self.to_word, self.to_pdf):
            bottom.addWidget(b)
        lay.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._flush)
        self.group.idClicked.connect(self._show_cached)
        self.on_document()

    @property
    def ratio(self) -> float:
        return self.RATIOS[self.group.checkedId()][0]

    def on_busy(self, busy):
        self.go.setEnabled(not busy and self.app.doc is not None)
        for b in self.group.buttons():
            b.setEnabled(not busy)

    def on_document(self):
        self.result = None
        self.buffer = ""
        self._show_cached()

    def _set_result(self, result):
        self.result = result
        has = result is not None
        for b in (self.copy, self.to_word, self.to_pdf):
            b.setEnabled(has)
        if not has:
            self.stats.setText("")
            return
        self.view.setHtml(_cite_html(markdown_to_html(result.text)))
        if result.mode == "key points":
            self.stats.setText(f"This document is short ({result.original_words:,} words), so Queryon "
                               f"listed its key points instead of a {int(result.ratio * 100)}% rewrite.")
        else:
            self.stats.setText(f"Original: {result.original_words:,} words  →  simplified: "
                               f"{result.words:,} words ({result.achieved:.0%} of the original)")

    def _show_cached(self, *_):
        if self.app.busy:
            return
        cached = self.app.cache.get_summary(self.ratio) if self.app.cache else None
        if cached:
            self._set_result(cached)
        else:
            self._set_result(None)
            msg = ("Open a document first." if self.app.doc is None
                   else "Choose a length and press <b>Simplify</b>.")
            self.view.setHtml(f"<p style='color:{MUTED}; margin-top:40px' align='center'>{msg}</p>")

    def _flush(self):
        if self._dirty:
            self._dirty = False
            self.view.setHtml(_cite_html(markdown_to_html(self.buffer + " ▌")))
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def generate(self):
        if self.app.busy or self.app.doc is None or not self.app.ensure_engine():
            return
        ratio, engine = self.ratio, self.app.engine
        self.buffer = ""
        self._set_result(None)
        self.view.clear()

        def work(job):
            return engine.simplify(ratio, on_token=job.emit_token, on_progress=job.emit_progress, cancel=job.cancel)

        def on_token(t):
            self.buffer += t
            self._dirty = True

        def on_progress(done, total, msg):
            self.progress.setMaximum(max(1, total))
            self.progress.setValue(done)
            self.progress_label.setText(msg + (" — the first part takes longest" if done == 0 else ""))

        def end():
            self.timer.stop()
            self.progress.hide(); self.progress_label.hide()
            self.go.show(); self.stop.hide()

        def done(result):
            end()
            self.app.cache.put_summary(result)
            self._set_result(result)

        def stopped():
            end()
            self.view.setHtml(_cite_html(markdown_to_html(self.buffer)) +
                              f"<p style='color:{MUTED}'><i>Stopped. Press Simplify to start again.</i></p>")

        def failed(msg):
            end()
            self.view.setHtml(f"<p style='color:{BAD}'>⚠ {html.escape(msg)}</p>")

        self.go.hide(); self.stop.show()
        self.progress.setValue(0); self.progress.show(); self.progress_label.show()
        self.progress_label.setText("Starting…")
        self.timer.start()
        self.app.run(work, f"Simplifying ({int(ratio * 100)}%)…", token=on_token, progress=on_progress,
                     done=done, failed=failed, cancelled=stopped)

    def copy_text(self):
        if self.result:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(re.sub(r"_\((from [^)]*)\)_", r"(\1)", self.result.text))
            self.app.flash("Copied to clipboard")


# =========================================================================== Quiz

class QuizPanel(Panel):
    def __init__(self, app):
        super().__init__(app)
        self.questions = []
        self.answers: dict[int, int] = {}
        self.index = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        top.addWidget(QLabel("Questions:"))
        self.count = QComboBox()
        self.count.addItems(["5", "10", "15"])
        self.count.setCurrentIndex(1)
        top.addWidget(self.count)
        self.go = _button("Make a quiz", "primary")
        self.go.clicked.connect(self.generate)
        self.stop = _button("Stop", "danger")
        self.stop.clicked.connect(self.app.cancel_current)
        self.stop.hide()
        top.addWidget(self.go)
        top.addWidget(self.stop)
        top.addStretch(1)
        self.to_word = _button("Save as Word")
        self.to_word.clicked.connect(lambda: self.app.export("quiz", "docx", self.questions))
        self.to_pdf = _button("Save as PDF")
        self.to_pdf.clicked.connect(lambda: self.app.export("quiz", "pdf", self.questions))
        top.addWidget(self.to_word)
        top.addWidget(self.to_pdf)
        lay.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.progress_label = _muted("")
        self.progress_label.hide()
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        # page 0: empty state
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        self.stack.addWidget(self.empty)

        # page 1: question card
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        self.q_counter = _muted("")
        self.q_counter.setWordWrap(False)
        self.score = _muted("")
        self.score.setWordWrap(False)
        head.addWidget(self.q_counter)
        head.addStretch(1)
        head.addWidget(self.score)
        c.addLayout(head)
        self.q_text = QLabel()
        self.q_text.setWordWrap(True)
        self.q_text.setStyleSheet("font-size: 13pt; font-weight: 600; margin: 8px 0 10px 0;")
        c.addWidget(self.q_text)
        self.option_buttons = []
        for i in range(4):
            b = _button("", "option")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, k=i: self.choose(k))
            self.option_buttons.append(b)
            c.addWidget(b)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.RichText)
        c.addWidget(self.feedback)
        c.addStretch(1)
        nav = QHBoxLayout()
        self.prev = _button("← Previous")
        self.prev.clicked.connect(lambda: self.show_question(self.index - 1))
        self.next = _button("Next →", "primary")
        self.next.clicked.connect(self.next_or_finish)
        nav.addWidget(self.prev)
        nav.addStretch(1)
        nav.addWidget(self.next)
        c.addLayout(nav)
        self.stack.addWidget(card)

        # page 2: results
        res = QFrame()
        res.setObjectName("card")
        r = QVBoxLayout(res)
        r.setContentsMargins(24, 24, 24, 24)
        self.result_title = QLabel()
        self.result_title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        self.result_title.setAlignment(Qt.AlignCenter)
        r.addWidget(self.result_title)
        self.result_detail = QTextBrowser()
        r.addWidget(self.result_detail, 1)
        rb = QHBoxLayout()
        again = _button("Try the same quiz again")
        again.clicked.connect(self.restart)
        new = _button("Make a new quiz", "primary")
        new.clicked.connect(self.generate)
        rb.addStretch(1)
        rb.addWidget(again)
        rb.addWidget(new)
        r.addLayout(rb)
        self.stack.addWidget(res)
        self.on_document()

    def on_busy(self, busy):
        self.go.setEnabled(not busy and self.app.doc is not None)

    def on_document(self):
        cached = self.app.cache.get_quiz() if self.app.cache else None
        self.set_questions(cached or [])

    def set_questions(self, qs):
        self.questions = qs
        self.answers = {}
        has = bool(qs)
        self.to_word.setEnabled(has)
        self.to_pdf.setEnabled(has)
        if has:
            self.show_question(0)
        else:
            self.empty.setText("Open a document first." if self.app.doc is None else
                               "Press <b>Make a quiz</b> to get multiple-choice questions on this document.<br>"
                               "Each answer comes with a short explanation and the page to revise.")
            self.stack.setCurrentIndex(0)

    def restart(self):
        self.answers = {}
        self.show_question(0)

    def show_question(self, i):
        if not self.questions:
            return
        self.index = max(0, min(i, len(self.questions) - 1))
        q = self.questions[self.index]
        self.q_counter.setText(f"Question {self.index + 1} of {len(self.questions)}  ·  {q.source}")
        correct = sum(1 for k, a in self.answers.items() if self.questions[k].answer == a)
        self.score.setText(f"Score: {correct} / {len(self.answers)}")
        self.q_text.setText(q.question)
        chosen = self.answers.get(self.index)
        for k, (b, opt) in enumerate(zip(self.option_buttons, q.options)):
            b.setText(f"{'ABCD'[k]}.  {opt}")
            b.setEnabled(chosen is None)
            style = ""
            if chosen is not None:
                if k == q.answer:
                    style = f"background:#dcfce7; border:1px solid {GOOD}; color:{GOOD}; font-weight:600;"
                elif k == chosen:
                    style = f"background:#fee2e2; border:1px solid {BAD}; color:{BAD};"
            b.setStyleSheet(style)
        if chosen is None:
            self.feedback.setText("")
        else:
            ok = chosen == q.answer
            verdict = (f"<b style='color:{GOOD}'>Correct!</b>" if ok else
                       f"<b style='color:{BAD}'>Not quite.</b> The answer is {'ABCD'[q.answer]}.")
            self.feedback.setText(f"{verdict} {html.escape(q.explanation)} "
                                  f"<span style='color:{MUTED}'>Revise: {q.source}</span>")
        self.prev.setEnabled(self.index > 0)
        self.next.setText("See results" if self.index == len(self.questions) - 1 else "Next →")
        self.stack.setCurrentIndex(1)

    def choose(self, k):
        if self.index not in self.answers:
            self.answers[self.index] = k
            self.show_question(self.index)

    def next_or_finish(self):
        if self.index < len(self.questions) - 1:
            self.show_question(self.index + 1)
            return
        n = len(self.questions)
        correct = sum(1 for k, a in self.answers.items() if self.questions[k].answer == a)
        self.result_title.setText(f"You scored {correct} out of {n}")
        rows = []
        for i, q in enumerate(self.questions):
            a = self.answers.get(i)
            mark = (f"<span style='color:{GOOD}'>✔</span>" if a == q.answer else
                    f"<span style='color:{BAD}'>✘</span>" if a is not None else "–")
            rows.append(f"<p>{mark} <b>{i + 1}.</b> {html.escape(q.question)}<br>"
                        f"<span style='color:{MUTED}'>Answer: {html.escape(q.options[q.answer])} "
                        f"· revise {q.source}</span></p>")
        self.result_detail.setHtml("".join(rows))
        self.stack.setCurrentIndex(2)

    def generate(self):
        if self.app.busy or self.app.doc is None or not self.app.ensure_engine():
            return
        n, engine = int(self.count.currentText()), self.app.engine

        def work(job):
            return engine.quiz(n, on_progress=job.emit_progress, cancel=job.cancel)

        def on_progress(done, total, msg):
            self.progress.setMaximum(max(1, total))
            self.progress.setValue(done)
            self.progress_label.setText(msg)

        def end():
            self.progress.hide(); self.progress_label.hide()
            self.go.show(); self.stop.hide()

        def done(qs):
            end()
            if not qs:
                self.app.warn("The model could not write valid questions for this document. Please try again.")
                return
            self.app.cache.put_quiz(qs)
            self.set_questions(qs)

        def failed(msg):
            end()
            self.app.warn(msg)

        self.go.hide(); self.stop.show()
        self.progress.setValue(0); self.progress.show(); self.progress_label.show()
        self.empty.setText("Writing questions…")
        self.stack.setCurrentIndex(0)
        self.app.run(work, "Making a quiz…", progress=on_progress, done=done, failed=failed,
                     cancelled=lambda: (end(), self.on_document()))


# =========================================================================== Flashcards

class FlipCard(QLabel):
    clicked = Signal()

    def mousePressEvent(self, e):
        self.clicked.emit()


class FlashcardPanel(Panel):
    def __init__(self, app):
        super().__init__(app)
        self.cards = []
        self.order: list[int] = []
        self.pos = 0
        self.flipped = False
        self.known: set[int] = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        top.addWidget(QLabel("Cards:"))
        self.count = QComboBox()
        self.count.addItems(["8", "12", "20"])
        self.count.setCurrentIndex(1)
        top.addWidget(self.count)
        self.go = _button("Make flashcards", "primary")
        self.go.clicked.connect(self.generate)
        self.stop = _button("Stop", "danger")
        self.stop.clicked.connect(self.app.cancel_current)
        self.stop.hide()
        top.addWidget(self.go)
        top.addWidget(self.stop)
        top.addStretch(1)
        self.to_word = _button("Save as Word")
        self.to_word.clicked.connect(lambda: self.app.export("cards", "docx", self.cards))
        self.to_pdf = _button("Save as PDF")
        self.to_pdf.clicked.connect(lambda: self.app.export("cards", "pdf", self.cards))
        top.addWidget(self.to_word)
        top.addWidget(self.to_pdf)
        lay.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.progress_label = _muted("")
        self.progress_label.hide()
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)

        self.info = _muted("")
        self.info.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.info)
        self.card = FlipCard()
        self.card.setAlignment(Qt.AlignCenter)
        self.card.setWordWrap(True)
        self.card.setCursor(Qt.PointingHandCursor)
        self.card.setMinimumHeight(260)
        self.card.clicked.connect(self.flip)
        lay.addWidget(self.card, 1)

        nav = QHBoxLayout()
        self.prev = _button("← Previous")
        self.prev.clicked.connect(lambda: self.move(-1))
        self.flip_btn = _button("Flip  (Space)")
        self.flip_btn.clicked.connect(self.flip)
        self.again = _button("Still learning")
        self.again.clicked.connect(lambda: self.mark(False))
        self.got = _button("I know this ✔", "primary")
        self.got.clicked.connect(lambda: self.mark(True))
        self.shuffle = _button("Shuffle")
        self.shuffle.clicked.connect(self.do_shuffle)
        self.next = _button("Next →")
        self.next.clicked.connect(lambda: self.move(1))
        for w in (self.prev, self.shuffle):
            nav.addWidget(w)
        nav.addStretch(1)
        for w in (self.flip_btn, self.again, self.got):
            nav.addWidget(w)
        nav.addStretch(1)
        nav.addWidget(self.next)
        lay.addLayout(nav)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.flip)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.move(1))
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.move(-1))
        self.on_document()

    def on_busy(self, busy):
        self.go.setEnabled(not busy and self.app.doc is not None)

    def on_document(self):
        cached = self.app.cache.get_cards() if self.app.cache else None
        self.set_cards(cached or [])

    def set_cards(self, cards):
        self.cards = cards
        self.order = list(range(len(cards)))
        self.pos, self.flipped, self.known = 0, False, set()
        has = bool(cards)
        for w in (self.prev, self.next, self.flip_btn, self.again, self.got, self.shuffle, self.to_word, self.to_pdf):
            w.setEnabled(has)
        self.render()

    def render(self):
        if not self.cards:
            self.info.setText("")
            msg = ("Open a document first." if self.app.doc is None else
                   "Press <b>Make flashcards</b> to turn the key terms and ideas into cards you can flip.")
            self.card.setStyleSheet(f"color:{MUTED}; font-size: 11pt;")
            self.card.setText(msg)
            return
        c = self.cards[self.order[self.pos]]
        self.info.setText(f"Card {self.pos + 1} of {len(self.cards)}  ·  known: {len(self.known)}"
                          f"  ·  click the card or press Space to flip")
        if self.flipped:
            self.card.setStyleSheet("background:#f0fdfa; border:2px solid #5eead4; border-radius:16px;"
                                    "padding:30px; font-size:14pt;")
            self.card.setText(f"{html.escape(c.back)}<br><br><span style='color:{MUTED}; font-size:9pt'>"
                              f"{c.source}</span>")
        else:
            self.card.setStyleSheet("background:white; border:2px solid #e5e7eb; border-radius:16px;"
                                    "padding:30px; font-size:17pt; font-weight:600;")
            self.card.setText(html.escape(c.front))

    def flip(self):
        if self.cards:
            self.flipped = not self.flipped
            self.render()

    def move(self, step):
        if self.cards:
            self.pos = (self.pos + step) % len(self.cards)
            self.flipped = False
            self.render()

    def mark(self, known):
        if not self.cards:
            return
        idx = self.order[self.pos]
        (self.known.add if known else self.known.discard)(idx)
        if not known:  # see it again later in this round
            self.order.append(self.order.pop(self.pos))
            self.pos -= 1
        self.move(1)

    def do_shuffle(self):
        random.shuffle(self.order)
        self.pos, self.flipped = 0, False
        self.render()

    def generate(self):
        if self.app.busy or self.app.doc is None or not self.app.ensure_engine():
            return
        n, engine = int(self.count.currentText()), self.app.engine

        def work(job):
            return engine.flashcards(n, on_progress=job.emit_progress, cancel=job.cancel)

        def on_progress(done, total, msg):
            self.progress.setMaximum(max(1, total))
            self.progress.setValue(done)
            self.progress_label.setText(msg)

        def end():
            self.progress.hide(); self.progress_label.hide()
            self.go.show(); self.stop.hide()

        def done(cards):
            end()
            if not cards:
                self.app.warn("The model could not make flashcards for this document. Please try again.")
                return
            self.app.cache.put_cards(cards)
            self.set_cards(cards)

        def failed(msg):
            end()
            self.app.warn(msg)

        self.go.hide(); self.stop.show()
        self.progress.setValue(0); self.progress.show(); self.progress_label.show()
        self.app.run(work, "Making flashcards…", progress=on_progress, done=done, failed=failed,
                     cancelled=lambda: (end(), self.render()))


# =========================================================================== Document

class DocumentPanel(Panel):
    def __init__(self, app):
        super().__init__(app)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        self.note = _muted("The text Queryon extracted from your file. This is exactly what the AI reads.")
        lay.addWidget(self.note)
        self.view = QTextBrowser()
        lay.addWidget(self.view, 1)
        self.on_document()

    def on_document(self):
        doc = self.app.doc
        if doc is None:
            self.view.setHtml(f"<p style='color:{MUTED}' align='center'>No document open.</p>")
            return
        parts = []
        for b in doc.blocks:
            body = html.escape(b.text).replace("\n\n", "</p><p>").replace("\n", "<br>")
            parts.append(f"<h4 style='color:#0f766e; margin-bottom:2px'>{b.label}</h4><p>{body}</p>")
        self.view.setHtml("".join(parts))
