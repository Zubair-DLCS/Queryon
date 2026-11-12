"""The main window: header with author credit, sidebar, and the five tabs."""

from __future__ import annotations

import html
import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPageLayout, QPageSize, QPdfWriter, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_TAGLINE, APP_VERSION, AUTHOR_NAME, AUTHOR_TITLE
from .. import export as ex
from ..cache import ResultCache
from ..config import MAX_WORDS, Settings
from ..engine import Engine
from ..extract import FILE_TYPES, OPEN_DIALOG_FILTER, ExtractionError, load_document
from ..models import BY_ID, find_model_file, recommended_model
from . import workers
from .dialogs import AboutDialog, ModelSetupDialog, SettingsDialog
from .panels import ChatPanel, DocumentPanel, FlashcardPanel, QuizPanel, SummaryPanel
from .style import ACCENT, BAD, GOOD, MUTED


def asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


class MainWindow(QMainWindow):
    busy_changed = Signal(bool)
    document_changed = Signal()

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.doc = None
        self.backend = None
        self.engine = None
        self.cache = None
        self.busy = False
        self.current_job = None
        self.model_job = None

        self.setWindowTitle(f"{APP_NAME} — by {AUTHOR_NAME}")
        self.setWindowIcon(QIcon(str(asset("queryon.png"))))
        self.resize(1240, 800)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)

        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.chat = ChatPanel(self)
        self.summary = SummaryPanel(self)
        self.quiz = QuizPanel(self)
        self.cards = FlashcardPanel(self)
        self.document_view = DocumentPanel(self)
        self.tabs.addTab(self.chat, "Chat")
        self.tabs.addTab(self.summary, "Simplify")
        self.tabs.addTab(self.quiz, "Quiz")
        self.tabs.addTab(self.cards, "Flashcards")
        self.tabs.addTab(self.document_view, "Original text")
        body.addWidget(self.tabs, 1)
        bw = QWidget()
        bw.setLayout(body)
        root.addWidget(bw, 1)
        self.setCentralWidget(central)

        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, 1)
        credit = QLabel(f"© 2026 {AUTHOR_NAME}  ·  {APP_NAME} v{APP_VERSION}")
        self.statusBar().addPermanentWidget(credit)

        self.set_busy(False)
        QTimer.singleShot(250, self.prepare_backend)

    # ------------------------------------------------------------------ layout

    def _header(self) -> QFrame:
        h = QFrame()
        h.setObjectName("header")
        h.setFixedHeight(84)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(22, 10, 26, 10)
        logo = QLabel()
        pm = QPixmap(str(asset("queryon.png")))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(logo)
        lay.addSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("appTitle")
        tag = QLabel(APP_TAGLINE + "  ·  offline study assistant")
        tag.setObjectName("appTagline")
        titles.addStretch(1)
        titles.addWidget(t)
        titles.addWidget(tag)
        titles.addStretch(1)
        lay.addLayout(titles)
        lay.addStretch(1)
        credit = QVBoxLayout()
        credit.setSpacing(0)
        by = QLabel("Developed by")
        by.setObjectName("creditTitle")
        by.setAlignment(Qt.AlignRight)
        name = QLabel(AUTHOR_NAME)
        name.setObjectName("creditName")
        name.setAlignment(Qt.AlignRight)
        role = QLabel(AUTHOR_TITLE)
        role.setObjectName("creditTitle")
        role.setAlignment(Qt.AlignRight)
        credit.addStretch(1)
        for w in (by, name, role):
            credit.addWidget(w)
        credit.addStretch(1)
        lay.addLayout(credit)
        return h

    def _sidebar(self) -> QFrame:
        s = QFrame()
        s.setObjectName("sidebar")
        s.setFixedWidth(280)
        lay = QVBoxLayout(s)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self.open_btn = QPushButton("Open a document…")
        self.open_btn.setObjectName("primary")
        self.open_btn.setMinimumHeight(42)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.choose_file)
        lay.addWidget(self.open_btn)

        drop = QFrame()
        drop.setObjectName("dropZone")
        dl = QVBoxLayout(drop)
        dtxt = QLabel("or drag and drop a file here<br><small>PDF · Word · PowerPoint · text · "
                      "RTF · OpenDocument · images / scans</small>")
        dtxt.setAlignment(Qt.AlignCenter)
        dtxt.setWordWrap(True)
        dtxt.setObjectName("muted")
        dl.addWidget(dtxt)
        lay.addWidget(drop)

        doc_card = QFrame()
        doc_card.setObjectName("card")
        dc = QVBoxLayout(doc_card)
        cap = QLabel("DOCUMENT")
        cap.setObjectName("muted")
        dc.addWidget(cap)
        self.doc_name = QLabel("None open")
        self.doc_name.setObjectName("docName")
        self.doc_name.setWordWrap(True)
        self.doc_info = QLabel(f"Up to {MAX_WORDS:,} words (about 8 pages).")
        self.doc_info.setObjectName("muted")
        self.doc_info.setWordWrap(True)
        dc.addWidget(self.doc_name)
        dc.addWidget(self.doc_info)
        lay.addWidget(doc_card)

        model_card = QFrame()
        model_card.setObjectName("card")
        mc = QVBoxLayout(model_card)
        cap2 = QLabel("AI MODEL")
        cap2.setObjectName("muted")
        mc.addWidget(cap2)
        self.model_label = QLabel("Not loaded")
        self.model_label.setWordWrap(True)
        self.model_label.setTextFormat(Qt.RichText)
        mc.addWidget(self.model_label)
        change = QPushButton("Change model…")
        change.clicked.connect(self.open_settings)
        mc.addWidget(change)
        lay.addWidget(model_card)

        lay.addStretch(1)
        tip = QLabel("<small>Answers come from your document only and show page references. "
                     "AI can make mistakes — check important points.</small>")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        st = QPushButton("Settings")
        st.clicked.connect(self.open_settings)
        ab = QPushButton("About")
        ab.clicked.connect(lambda: AboutDialog(self).exec())
        row.addWidget(st)
        row.addWidget(ab)
        lay.addLayout(row)
        return s

    # ------------------------------------------------------------------ helpers used by panels

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.open_btn.setEnabled(not busy)
        self.status_label.setText(message or ("Working…" if busy else "Ready"))
        self.busy_changed.emit(busy)

    def flash(self, message: str, ms: int = 4000) -> None:
        self.statusBar().showMessage(message, ms)

    def warn(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)

    def run(self, fn, label, token=None, progress=None, done=None, failed=None, cancelled=None):
        job = workers.Job(fn)
        if token:
            job.signals.token.connect(token)
        if progress:
            job.signals.progress.connect(progress)

        def finish(cb, *args):
            self.current_job = None
            self.set_busy(False)
            if cb:
                cb(*args)

        job.signals.done.connect(lambda r: finish(done, r))
        job.signals.failed.connect(lambda m: finish(failed or self.warn, m))
        job.signals.cancelled.connect(lambda: finish(cancelled))
        self.current_job = job
        self.set_busy(True, label)
        workers.start(job)
        return job

    def cancel_current(self) -> None:
        if self.current_job:
            self.current_job.cancel.set()
            self.status_label.setText("Stopping…")

    def ensure_engine(self) -> bool:
        if self.engine is not None:
            return True
        if self.model_job is not None:
            self.flash("The AI model is still loading — one moment…", 5000)
            return False
        self.prepare_backend(interactive=True)
        return self.engine is not None

    # ------------------------------------------------------------------ AI backend

    def _set_model_label(self, text: str, color: str) -> None:
        self.model_label.setText(f"<span style='color:{color}'>●</span> {text}")

    def prepare_backend(self, interactive: bool = True) -> None:
        if self.backend is not None:
            self.backend.close()
        self.backend = self.engine = None
        s = self.settings
        if s.backend == "cloud":
            from ..llm import CloudBackend

            try:
                self.backend = CloudBackend(s.cloud_base_url, s.cloud_model, s.cloud_api_key)
            except ValueError as e:
                self._set_model_label(str(e), BAD)
                return
            self._set_model_label(f"{html.escape(self.backend.name)}<br><small>needs internet</small>", GOOD)
            self._backend_ready()
            return

        if s.local_model == "custom":
            path = Path(s.custom_model_path) if s.custom_model_path else None
            if not path or not path.exists():
                path = None
            label = path.name if path else "custom model"
        else:
            info = BY_ID.get(s.local_model) or recommended_model()
            path = find_model_file(info)
            label = info.name
        if path is None:
            self._set_model_label("No offline model installed yet", BAD)
            if interactive:
                dlg = ModelSetupDialog(self, self.settings)
                if dlg.exec():
                    self.prepare_backend(interactive=False)
            return

        self._set_model_label(f"Loading {html.escape(label)}…", "#d97706")
        threads = s.threads

        def work(job):
            from ..llm import LocalBackend

            return LocalBackend(str(path), threads=threads)

        def loaded(backend):
            self.model_job = None
            self.backend = backend
            self._set_model_label(f"{html.escape(label)}<br><small>offline · ready</small>", GOOD)
            self._backend_ready()

        def failed(msg):
            self.model_job = None
            self._set_model_label("Could not load the model", BAD)
            self.warn(f"The AI model could not be loaded:\n\n{msg}\n\nThe file may be damaged or there may "
                      "not be enough free memory. Close other programs, or choose a lighter model in Settings.")

        self.model_job = workers.Job(work)
        self.model_job.signals.done.connect(loaded)
        self.model_job.signals.failed.connect(failed)
        self.flash("Loading the AI model…", 8000)
        workers.start(self.model_job)

    def _backend_ready(self) -> None:
        self._make_engine()
        self.busy_changed.emit(self.busy)

    def _make_engine(self) -> None:
        if self.backend is not None and self.doc is not None:
            self.engine = Engine(self.backend, self.doc)
            self.cache = ResultCache(self.doc.fingerprint(), self.backend.name)
        else:
            self.engine = None
            self.cache = None
        self.document_changed.emit()

    def open_settings(self) -> None:
        if self.busy:
            self.flash("Please wait for the current task to finish.")
            return
        if SettingsDialog(self, self.settings).exec():
            self.prepare_backend(interactive=True)

    # ------------------------------------------------------------------ documents

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a study document", "", OPEN_DIALOG_FILTER)
        if path:
            self.open_document(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self.busy:
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.open_document(urls[0])

    def open_document(self, path: str) -> None:
        if self.busy:
            return
        if Path(path).suffix.lower() not in FILE_TYPES:
            self.warn(f"'{Path(path).suffix}' files are not supported.")
            return

        def work(job):
            return load_document(path, progress=job.emit_progress)

        def done(doc):
            if doc.words > MAX_WORDS:
                ans = QMessageBox.question(
                    self, APP_NAME,
                    f"This document has {doc.words:,} words. {APP_NAME} works with up to {MAX_WORDS:,} "
                    f"words (about 8 pages) so that it runs well on ordinary computers.\n\n"
                    f"Use the first {MAX_WORDS:,} words?")
                if ans != QMessageBox.Yes:
                    return
                doc = doc.truncate(MAX_WORDS)
            self.doc = doc
            unit = doc.unit_name.lower()
            info = f"{doc.kind} · {doc.words:,} words · {len(doc.blocks)} {unit}{'s' if len(doc.blocks) != 1 else ''}"
            if doc.ocr_used:
                info += f"<br>{doc.ocr_used} scanned page{'s' if doc.ocr_used > 1 else ''} read with OCR — check the Original text tab"
            if doc.truncated_from:
                info += f"<br><span style='color:{BAD}'>Shortened from {doc.truncated_from:,} words</span>"
            self.doc_name.setText(doc.name)
            self.doc_info.setText(info)
            self._make_engine()
            self.tabs.setCurrentWidget(self.chat)
            self.flash(f"Opened {doc.name}")
            if self.backend is None and self.model_job is None:
                self.prepare_backend(interactive=True)

        def failed(msg):
            self.warn(msg)

        def progress(done_n, total, msg):
            self.status_label.setText(msg)

        self.run(work, f"Reading {Path(path).name}…", progress=progress, done=done, failed=failed)

    # ------------------------------------------------------------------ export

    def export(self, kind: str, fmt: str, data) -> None:
        if not data or self.doc is None:
            return
        stem = Path(self.doc.name).stem
        suffix = {"summary": "simplified", "quiz": "quiz", "cards": "flashcards"}[kind]
        if kind == "summary" and data.mode == "rewrite":
            suffix += f"-{int(data.ratio * 100)}pct"
        default = f"{stem} - {suffix}.{fmt}"
        filt = "Word document (*.docx)" if fmt == "docx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "Save", default, filt)
        if not path:
            return
        try:
            if fmt == "docx":
                {"summary": ex.summary_docx, "quiz": ex.quiz_docx, "cards": ex.cards_docx}[kind](data, self.doc.name, path)
            else:
                page = {"summary": ex.summary_html, "quiz": ex.quiz_html, "cards": ex.cards_html}[kind](data, self.doc.name)
                save_pdf(page, path)
        except PermissionError:
            self.warn("Could not save the file. Is it open in another program?")
            return
        except Exception as e:
            self.warn(f"Could not save the file: {e}")
            return
        self.flash(f"Saved {Path(path).name}", 6000)

    def closeEvent(self, e):
        if self.current_job:
            self.current_job.cancel.set()
        super().closeEvent(e)


def save_pdf(page_html: str, path: str) -> None:
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
    writer.setResolution(300)
    doc = QTextDocument()
    doc.setHtml(page_html)
    doc.setPageSize(writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF())
    doc.print_(writer)
