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


def generate_summary(raw_text: str) -> str:
    if not raw_text.strip():
        raise RuntimeError("Não é possível gerar resumo com texto vazio.")

    settings = load_settings()
    client = OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
    )
    instructions = load_summary_prompt()

    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            "Texto das evoluções já processado e ordenado cronologicamente:",
                            raw_text,
                        ]
                    ),
                },
            ],
        )
    except APITimeoutError as error:
        raise SummaryTimeoutError(
            f"A geração do resumo excedeu o tempo limite de {settings.llm_timeout_seconds:.0f} segundos."
        ) from error
    except APIConnectionError as error:
        raise SummaryGenerationError(
            "Não foi possível se conectar ao endpoint de LLM configurado."
        ) from error
    except APIStatusError as error:
        raise SummaryGenerationError(
            f"O endpoint de LLM configurado retornou erro HTTP {error.status_code}."
        ) from error
    except OpenAIError as error:
        raise SummaryGenerationError(
            "O endpoint de LLM configurado retornou um erro inesperado."
        ) from error
    except Exception as error:
        raise SummaryGenerationError(
            "Ocorreu um erro inesperado durante a geração do resumo."
        ) from error

    summary = _extract_chat_completion_text(response)
    if not summary:
        raise SummaryGenerationError("O modelo retornou uma resposta vazia ao gerar o resumo.")

    return summary.strip()


def _extract_chat_completion_text(response: object) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        fragments: list[str] = []
        for chunk in content:
            text = getattr(chunk, "text", None)
            if text:
                fragments.append(str(text))
        return "\n".join(fragment.strip() for fragment in fragments if fragment.strip())

    return ""
