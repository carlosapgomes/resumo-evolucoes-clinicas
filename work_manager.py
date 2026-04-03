from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


class WorkInProgressError(RuntimeError):
    pass


class WorkNotFoundError(RuntimeError):
    pass


@dataclass
class WorkState:
    id: str
    patient_record: str
    status: str
    phase: str
    message: str
    started_at: str
    finished_at: str | None = None
    raw_text: str | None = None
    summary: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._current_work: WorkState | None = None

    def start_work(self, patient_record: str) -> WorkState:
        with self._lock:
            if self._current_work and self._current_work.status == "running":
                raise WorkInProgressError("Já existe um processamento em andamento.")

            work = WorkState(
                id=uuid4().hex,
                patient_record=patient_record,
                status="running",
                phase="starting",
                message="Iniciando processamento...",
                started_at=_utcnow_iso(),
            )
            self._current_work = work
            return _clone_work(work)

    def is_busy(self) -> bool:
        with self._lock:
            return self._current_work is not None and self._current_work.status == "running"

    def get_current_work(self) -> WorkState | None:
        with self._lock:
            if not self._current_work:
                return None
            return _clone_work(self._current_work)

    def get_work(self, work_id: str) -> WorkState | None:
        with self._lock:
            if not self._current_work or self._current_work.id != work_id:
                return None
            return _clone_work(self._current_work)

    def update_work(
        self,
        work_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        message: str | None = None,
        raw_text: str | None = None,
        summary: str | None = None,
        error: str | None = None,
    ) -> WorkState:
        with self._lock:
            work = self._require_work(work_id)

            if status is not None:
                work.status = status
            if phase is not None:
                work.phase = phase
            if message is not None:
                work.message = message
            if raw_text is not None:
                work.raw_text = raw_text
            if summary is not None:
                work.summary = summary
            if error is not None:
                work.error = error

            return _clone_work(work)

    def complete_work(self, work_id: str, *, raw_text: str, summary: str) -> WorkState:
        with self._lock:
            work = self._require_work(work_id)
            work.status = "completed"
            work.phase = "completed"
            work.message = "Resumo concluído."
            work.raw_text = raw_text
            work.summary = summary
            work.error = None
            work.finished_at = _utcnow_iso()
            return _clone_work(work)

    def fail_work(
        self,
        work_id: str,
        *,
        message: str,
        error: str | None = None,
        raw_text: str | None = None,
    ) -> WorkState:
        with self._lock:
            work = self._require_work(work_id)
            work.status = "error"
            work.phase = "error"
            work.message = message
            work.error = error
            if raw_text is not None:
                work.raw_text = raw_text
            work.finished_at = _utcnow_iso()
            return _clone_work(work)

    def _require_work(self, work_id: str) -> WorkState:
        if not self._current_work or self._current_work.id != work_id:
            raise WorkNotFoundError(f"Processamento não encontrado: {work_id}")
        return self._current_work


def _clone_work(work: WorkState) -> WorkState:
    return WorkState(**work.to_dict())


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
