from __future__ import annotations

from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, OpenAIError

from config import load_settings

PROMPT_PATH = Path(__file__).parent / "prompts" / "resumo.txt"


class SummaryGenerationError(RuntimeError):
    pass


class SummaryTimeoutError(SummaryGenerationError):
    pass


def load_summary_prompt() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError("O arquivo de prompt está vazio: prompts/resumo.txt")
    return prompt


def generate_summary(raw_text: str, patient_record: str | None = None) -> str:
    if not raw_text.strip():
        raise RuntimeError("Não é possível gerar resumo com texto vazio.")

    settings = load_settings()
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
    )
    instructions = load_summary_prompt()

    user_message_parts = []
    if patient_record:
        user_message_parts.append(f"Registro do paciente: {patient_record}")

    user_message_parts.extend(
        [
            "Texto bruto capturado do AGHUse:",
            raw_text,
        ]
    )

    try:
        response = client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            input="\n\n".join(user_message_parts),
        )
    except APITimeoutError as error:
        raise SummaryTimeoutError(
            f"A geração do resumo excedeu o tempo limite de {settings.openai_timeout_seconds:.0f} segundos."
        ) from error
    except APIConnectionError as error:
        raise SummaryGenerationError(
            "Não foi possível se conectar ao serviço de resumo da OpenAI."
        ) from error
    except APIStatusError as error:
        raise SummaryGenerationError(
            f"O serviço de resumo da OpenAI retornou erro HTTP {error.status_code}."
        ) from error
    except OpenAIError as error:
        raise SummaryGenerationError(
            "O serviço de resumo da OpenAI retornou um erro inesperado."
        ) from error
    except Exception as error:
        raise SummaryGenerationError(
            "Ocorreu um erro inesperado durante a geração do resumo."
        ) from error

    summary = _extract_response_text(response)
    if not summary:
        raise SummaryGenerationError("O modelo retornou uma resposta vazia ao gerar o resumo.")

    return summary.strip()


def _extract_response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    output = getattr(response, "output", None) or []
    fragments: list[str] = []

    for item in output:
        content = getattr(item, "content", None) or []
        for chunk in content:
            text = getattr(chunk, "text", None)
            if text:
                fragments.append(str(text))

    return "\n".join(fragment.strip() for fragment in fragments if fragment.strip())
