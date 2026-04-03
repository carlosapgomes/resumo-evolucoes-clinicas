from __future__ import annotations

import traceback
from threading import Thread

from flask import Flask, abort, jsonify, render_template, request

from aghu import capture_evolution_text
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

    return render_template(
        "result.html",
        work_id=work.id,
        patient_record=work.patient_record,
    )


@app.post("/api/work")
def create_work():
    payload = request.get_json(silent=True) or {}
    patient_record = str(payload.get("patient_record", "")).strip()

    if not patient_record:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "INVALID_PATIENT_RECORD",
                        "message": "Informe o registro do paciente.",
                    },
                }
            ),
            400,
        )

    try:
        work = work_manager.start_work(patient_record)
    except WorkInProgressError:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "WORK_IN_PROGRESS",
                        "message": "Já existe um processamento em andamento. Aguarde terminar.",
                    },
                }
            ),
            409,
        )

    thread = Thread(target=run_work, args=(work.id, patient_record), daemon=True)
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
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "WORK_NOT_FOUND",
                        "message": "Processamento não encontrado.",
                    },
                }
            ),
            404,
        )

    return jsonify({"ok": True, "work": work.to_dict()})


def run_work(work_id: str, patient_record: str) -> None:
    raw_text: str | None = None

    def report(phase: str, message: str) -> None:
        work_manager.update_work(work_id, phase=phase, message=message)

    try:
        work_manager.update_work(
            work_id,
            phase="capturing",
            message="Iniciando automação no AGHUse...",
        )
        raw_text = capture_evolution_text(patient_record, progress_callback=report)
    except Exception as error:
        print(f"Erro na etapa de captura do AGHUse para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="Não foi possível capturar as evoluções no AGHUse.",
            error=_friendly_capture_error_message(error),
            raw_text=raw_text,
        )
        return

    try:
        work_manager.update_work(
            work_id,
            phase="summarizing",
            message="Gerando resumo com o modelo...",
            raw_text=raw_text,
        )
        summary = generate_summary(raw_text, patient_record=patient_record)
    except SummaryTimeoutError as error:
        print(f"Timeout na etapa de resumo para o work {work_id}:")
        print(traceback.format_exc())
        work_manager.fail_work(
            work_id,
            message="A geração do resumo excedeu o tempo limite.",
            error=str(error),
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
            raw_text=raw_text,
        )
        return

    work_manager.complete_work(work_id, raw_text=raw_text, summary=summary)


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
