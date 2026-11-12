"""First-run model setup, Settings, and About."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout,
)

from .. import APP_NAME, APP_VERSION, AUTHOR_GITHUB, AUTHOR_NAME, AUTHOR_TITLE, REPO_URL
from ..config import Settings
from ..models import CATALOG, BY_ID, download_model, download_target, find_model_file, recommended_model, total_ram_gb
from . import workers


class ModelSetupDialog(QDialog):
    """Shown when no offline model is installed yet: download one, pick a file, or go cloud."""

    def __init__(self, parent, settings: Settings):
        super().__init__(parent)
        self.settings = settings
        self.job = None
        self.setWindowTitle(f"{APP_NAME} — set up the offline AI model")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        rec = recommended_model()
        head = QLabel(f"<h3>One-time setup</h3>{APP_NAME} works fully offline using an AI model stored on "
                      f"this computer. It needs to be downloaded once. This PC has about "
                      f"<b>{total_ram_gb():.0f} GB</b> of RAM, so the recommended model is "
                      f"<b>{rec.name}</b>.")
        head.setWordWrap(True)
        lay.addWidget(head)

        self.group = QButtonGroup(self)
        for i, m in enumerate(CATALOG):
            have = find_model_file(m) is not None
            rb = QRadioButton(f"{m.name}  —  {m.size_gb:.1f} GB download"
                              + ("   (already installed)" if have else "")
                              + ("   ★ recommended" if m.id == rec.id else ""))
            rb.setToolTip(f"{m.blurb}\nLicence: {m.license}")
            rb.setChecked(m.id == rec.id)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
            sub = QLabel(f"      {m.blurb}")
            sub.setObjectName("muted")
            lay.addWidget(sub)

        self.bar = QProgressBar()
        self.bar.hide()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)

        tip = QLabel("<small>For computer labs: download once, then copy the <b>models</b> folder next to "
                     "Queryon.exe on each PC. No internet needed there.</small>")
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        lay.addWidget(tip)

        row = QHBoxLayout()
        self.browse = QPushButton("I already have a .gguf file…")
        self.browse.clicked.connect(self.pick_file)
        self.cloud = QPushButton("Use a cloud API instead…")
        self.cloud.clicked.connect(self.use_cloud)
        row.addWidget(self.browse)
        row.addWidget(self.cloud)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Later")
        self.cancel_btn.clicked.connect(self.close_or_cancel)
        self.go = QPushButton("Download and use")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.go)
        lay.addLayout(row)

    def chosen(self):
        return CATALOG[self.group.checkedId()]

    def start(self):
        m = self.chosen()
        if find_model_file(m):
            self.accept_model(m.id)
            return
        self.go.setEnabled(False)
        for b in self.group.buttons():
            b.setEnabled(False)
        self.bar.show()
        self.bar.setMaximum(1000)
        self.status.setText(f"Downloading to {download_target(m).parent} … You can keep this window open; "
                            "if the connection drops, press Download again and it will continue.")
        self.cancel_btn.setText("Cancel download")

        def work(job):
            return download_model(m, progress=lambda d, t: job.emit_progress(d, t, ""), cancel=job.cancel)

        def prog(done, total, _):
            if total:
                self.bar.setValue(int(done * 1000 / total))
                self.status.setText(f"Downloaded {done / 1024**3:.2f} of {total / 1024**3:.2f} GB")

        def failed(msg):
            self.reset_ui()
            self.status.setText(f"⚠ Download failed: {msg}\nCheck the internet connection and press "
                                "Download again — it will continue where it stopped.")

        self.job = workers.Job(work)
        self.job.signals.progress.connect(prog)
        self.job.signals.done.connect(lambda _: self.accept_model(m.id))
        self.job.signals.failed.connect(failed)
        self.job.signals.cancelled.connect(lambda: (self.reset_ui(), self.status.setText("Download paused.")))
        workers.start(self.job)

    def reset_ui(self):
        self.job = None
        self.go.setEnabled(True)
        for b in self.group.buttons():
            b.setEnabled(True)
        self.cancel_btn.setText("Later")

    def close_or_cancel(self):
        if self.job:
            self.job.cancel.set()
        else:
            self.reject()

    def accept_model(self, model_id: str):
        self.settings.backend = "local"
        self.settings.local_model = model_id
        self.settings.save()
        self.accept()

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a GGUF model file", "", "GGUF models (*.gguf)")
        if path:
            self.settings.backend = "local"
            self.settings.local_model = "custom"
            self.settings.custom_model_path = path
            self.settings.save()
            self.accept()

    def use_cloud(self):
        dlg = SettingsDialog(self, self.settings, cloud_first=True)
        if dlg.exec() and self.settings.backend == "cloud":
            self.accept()

    def closeEvent(self, e):
        if self.job:
            self.job.cancel.set()
        super().closeEvent(e)


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: Settings, cloud_first: bool = False):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(f"{APP_NAME} settings")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        self.local = QRadioButton("Offline — AI model on this computer (private, no internet)")
        self.cloud = QRadioButton("Cloud — OpenAI-compatible API with your own key (needs internet)")
        (self.cloud if (cloud_first or settings.backend == "cloud") else self.local).setChecked(True)
        lay.addWidget(self.local)

        lf = QFormLayout()
        self.model = QComboBox()
        self.model.addItem(f"Automatic (recommended for this PC: {recommended_model().name})", "auto")
        for m in CATALOG:
            self.model.addItem(m.name + ("" if find_model_file(m) else "  (not downloaded)"), m.id)
        self.model.addItem("My own .gguf file", "custom")
        idx = self.model.findData(settings.local_model)
        self.model.setCurrentIndex(max(0, idx))
        lf.addRow("Model:", self.model)
        prow = QHBoxLayout()
        self.custom = QLineEdit(settings.custom_model_path)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self.pick)
        prow.addWidget(self.custom)
        prow.addWidget(pick)
        lf.addRow("Own model file:", prow)
        self.threads = QSpinBox()
        self.threads.setRange(0, 64)
        self.threads.setValue(settings.threads)
        self.threads.setSpecialValueText("Automatic")
        lf.addRow("CPU threads:", self.threads)
        wrap = QFrame()
        wrap.setLayout(lf)
        lay.addWidget(wrap)

        lay.addSpacing(8)
        lay.addWidget(self.cloud)
        cf = QFormLayout()
        self.url = QLineEdit(settings.cloud_base_url)
        self.cmodel = QLineEdit(settings.cloud_model)
        self.key = QLineEdit(settings.cloud_api_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Paste your API key")
        presets = QComboBox()
        presets.addItem("Presets…")
        presets.addItem("Google Gemini (free tier available)",
                        ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"))
        presets.addItem("OpenAI", ("https://api.openai.com/v1/", "gpt-4o-mini"))
        presets.addItem("Groq", ("https://api.groq.com/openai/v1/", "llama-3.1-8b-instant"))
        presets.addItem("Local llama.cpp / Ollama server", ("http://localhost:11434/v1/", "llama3.2"))
        presets.activated.connect(lambda i: i and (self.url.setText(presets.itemData(i)[0]),
                                                   self.cmodel.setText(presets.itemData(i)[1])))
        cf.addRow("Preset:", presets)
        cf.addRow("API base URL:", self.url)
        cf.addRow("Model name:", self.cmodel)
        cf.addRow("API key:", self.key)
        note = QLabel("<small>With the cloud option, your document text is sent to that service. "
                      "The key is stored only on this computer. Model names change over time; "
                      "check your provider's current list if one stops working.</small>")
        note.setWordWrap(True)
        note.setObjectName("muted")
        cf.addRow(note)
        cwrap = QFrame()
        cwrap.setLayout(cf)
        lay.addWidget(cwrap)

        self.local.toggled.connect(lambda on: (wrap.setEnabled(on), cwrap.setEnabled(not on)))
        wrap.setEnabled(self.local.isChecked())
        cwrap.setEnabled(self.cloud.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a GGUF model file", "", "GGUF models (*.gguf)")
        if path:
            self.custom.setText(path)
            self.model.setCurrentIndex(self.model.findData("custom"))

    def save(self):
        if self.cloud.isChecked() and not self.key.text().strip():
            QMessageBox.warning(self, APP_NAME, "Please paste an API key to use the cloud option.")
            return
        s = self.settings
        s.backend = "cloud" if self.cloud.isChecked() else "local"
        s.local_model = self.model.currentData()
        s.custom_model_path = self.custom.text().strip()
        s.threads = self.threads.value()
        s.cloud_base_url = self.url.text().strip()
        s.cloud_model = self.cmodel.text().strip()
        s.cloud_api_key = self.key.text().strip()
        s.save()
        self.accept()


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        text = QLabel(
            f"<h2 style='color:#0f766e; margin-bottom:0'>{APP_NAME}</h2>"
            f"<p style='margin-top:2px'>Version {APP_VERSION}</p>"
            f"<p>Chat with your study documents, get simplified 50% / 25% / 10% versions, "
            f"practice quizzes and flashcards — all offline, on your own computer.</p>"
            f"<p style='font-size:12pt'><b>Developed by {AUTHOR_NAME}</b><br>{AUTHOR_TITLE}</p>"
            f"<p><a href='{REPO_URL}'>{REPO_URL}</a><br><a href='{AUTHOR_GITHUB}'>{AUTHOR_GITHUB}</a></p>"
            f"<p><small>AI answers can contain mistakes. Always check important points against the "
            f"page references in the original document.<br>Built with Qt (PySide6), llama.cpp, PyMuPDF "
            f"and Tesseract OCR. Offline models: Qwen2.5 (Apache 2.0) and Llama 3.2 (Llama 3.2 Community "
            f"License; Built with Llama).</small></p>")
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextFormat(Qt.RichText)
        lay.addWidget(text)
        ok = QDialogButtonBox(QDialogButtonBox.Ok)
        ok.accepted.connect(self.accept)
        lay.addWidget(ok)
