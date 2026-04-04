from __future__ import annotations

import traceback
from datetime import date, datetime
from threading import Thread

from flask import Flask, abort, jsonify, render_template, request

from aghu import CaptureResult, capture_evolution_data
from config import load_settings
from llm import SummaryGenerationError, SummaryTimeoutError, generate_summary
from work_manager import WorkInProgressError, WorkManager

settings = load_settings()
app = Flask(__name__)
app.json.ensure_ascii = False
work_manager = WorkManager()


@app.get("/health")
def healthcheck():
    return jsonify({"ok": True, "service": "resumo-evolucoes-clinicas"})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/resultado/<work_id>")
def result_page(work_id: str):
    work = work_manager.get_work(work_id)
    if work is None:
        abort(404)

    return render_template("result.html", work=work)


@app.post("/api/work")
def create_work():
    payload = request.get_json(silent=True) or {}
    patient_record = str(payload.get("patient_record", "")).strip()
    start_date_raw = str(payload.get("start_date", "")).strip()
    end_date_raw = str(payload.get("end_date", "")).strip()

    if not patient_record:
        return _json_error(
            400,
            "INVALID_PATIENT_RECORD",
            "Informe o registro do paciente.",
        )

    if not start_date_raw:
        return _json_error(
            400,
            "INVALID_START_DATE",
            "Informe a data inicial.",
        )

    if not end_date_raw:
        return _json_error(
            400,
            "INVALID_END_DATE",
            "Informe a data final.",
        )

    try:
        start_date, end_date, interval_start_datetime, interval_end_datetime = _normalize_requested_dates(
            start_date_raw,
            end_date_raw,
        )
    except ValueError as error:
        return _json_error(400, "INVALID_DATE_RANGE", str(error))

    try:
        work = work_manager.start_work(
            patient_record,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            interval_start_datetime=interval_start_datetime,
            interval_end_datetime=interval_end_datetime,
        )
    except WorkInProgressError:
        return _json_error(
            409,
            "WORK_IN_PROGRESS",
            "Já existe um processamento em andamento. Aguarde terminar.",
        )

    thread = Thread(
        target=run_work,
        args=(
            work.id,
            patient_record,
            interval_start_datetime,
            interval_end_datetime,
        ),
        daemon=True,
    )
    thread.start()

    return (
        jsonify(
            {
                "ok": True,
                "work": work.to_dict(),
                "result_url": f"/resultado/{work.id}",
                "status_url": f"/api/work/{work.id}/status",
            }
        ),
        201,
    )


@app.get("/api/work/<work_id>/status")
def get_work_status(work_id: str):
    work = work_manager.get_work(work_id)
    if work is None:
        return _json_error(
            404,
            "WORK_NOT_FOUND",
            "Processamento não encontrado.",
        )

    return jsonify({"ok": True, "work": work.to_dict()})


def run_work(
    work_id: str,
    patient_record: str,
    interval_start_datetime: str,
    interval_end_datetime: str,
) -> None:
    capture_result: CaptureResult | None = None

    def report(phase: str, message: str) -> None:
        work_manager.update_work(work_id, phase=phase, message=message)

    try:
        work_manager.update_work(
            work_id,
            phase="starting",
            message="Preparando automação no AGHUse...",
        )
        capture_result = capture_evolution_data(
            patient_record,
            interval_start_datetime,
            interval_end_datetime,
            progress_callback=report,
        )
    except Exception as error:
        print(f"Erro na etapa de captura do AGHUse para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="Não foi possível capturar e processar as evoluções no AGHUse.",
            error=_friendly_capture_error_message(error),
            patient_summary=capture_result.patient_summary if capture_result else None,
            raw_text=capture_result.raw_text if capture_result else None,
        )
        return

    raw_text = capture_result.raw_text
    patient_summary = capture_result.patient_summary

    try:
        work_manager.update_work(
            work_id,
            phase="summarizing",
            message="Gerando resumo com o modelo...",
            patient_summary=patient_summary,
            raw_text=raw_text,
        )
        summary = generate_summary(raw_text)
    except SummaryTimeoutError as error:
        print(f"Timeout na etapa de resumo para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="A geração do resumo excedeu o tempo limite.",
            error=str(error),
            patient_summary=patient_summary,
            raw_text=raw_text,
        )
        return
    except SummaryGenerationError as error:
        print(f"Erro na etapa de resumo para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="Não foi possível gerar o resumo com o modelo.",
            error=str(error),
            patient_summary=patient_summary,
            raw_text=raw_text,
        )
        return
    except Exception as error:
        print(f"Erro inesperado na etapa de resumo para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="Ocorreu um erro inesperado ao gerar o resumo.",
            error=str(error),
            patient_summary=patient_summary,
            raw_text=raw_text,
        )
        return

    work_manager.complete_work(
        work_id,
        patient_summary=patient_summary,
        raw_text=raw_text,
        summary=summary,
    )


def _normalize_requested_dates(
    start_date_raw: str,
    end_date_raw: str,
) -> tuple[date, date, str, str]:
    start_date = _parse_iso_date(start_date_raw, field_name="data inicial")
    end_date = _parse_iso_date(end_date_raw, field_name="data final")

    today = date.today()
    if end_date > today:
        end_date = today

    if start_date > end_date:
        raise ValueError("A data inicial não pode ser posterior à data final.")

    interval_start_datetime = start_date.strftime("%d/%m/%Y") + " 00:01"
    interval_end_datetime = end_date.strftime("%d/%m/%Y") + " 23:59"
    return start_date, end_date, interval_start_datetime, interval_end_datetime


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"Formato inválido para {field_name}.") from error


def _json_error(status_code: int, code: str, message: str):
    return (
        jsonify(
            {
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        ),
        status_code,
    )


def _friendly_capture_error_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Falha inesperada durante a captura das evoluções."

    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "A captura das evoluções no AGHUse excedeu o tempo limite."

    return message


if __name__ == "__main__":
    app.run(host=settings.flask_host, port=settings.flask_port, debug=False)
