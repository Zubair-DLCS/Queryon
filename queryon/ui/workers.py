"""Running slow jobs (reading files, the AI model) off the UI thread."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..llm import Cancelled


class JobSignals(QObject):
    token = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class Job(QRunnable):
    """Runs fn(job) in the thread pool. fn may call job.emit_token / job.emit_progress
    and should check job.cancel (a threading.Event)."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = JobSignals()
        self.cancel = threading.Event()
        self.setAutoDelete(False)

    def emit_token(self, text: str) -> None:
        self.signals.token.emit(text)

    def emit_progress(self, done: int, total: int, message: str) -> None:
        self.signals.progress.emit(done, total, message)

    def run(self) -> None:
        try:
            result = self.fn(self)
        except Cancelled:
            self.signals.cancelled.emit()
            return
        except InterruptedError:
            self.signals.cancelled.emit()
            return
        except Exception as e:  # shown to the user as a friendly message
            traceback.print_exc()
            msg = str(e) or e.__class__.__name__
            self.signals.failed.emit(msg)
            return
        if self.cancel.is_set():
            self.signals.cancelled.emit()
        else:
            self.signals.done.emit(result)


_jobs: set[Job] = set()


def start(job: Job) -> Job:
    _jobs.add(job)
    for sig in (job.signals.done, job.signals.failed, job.signals.cancelled):
        sig.connect(lambda *_: _jobs.discard(job))
    QThreadPool.globalInstance().start(job)
    return job
