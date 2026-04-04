from __future__ import annotations

import json
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

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
    endpoint_url = _build_chat_completions_url(settings.llm_base_url)
    instructions = load_summary_prompt()

    payload = {
        "model": settings.llm_model,
        "messages": [
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
    }

    request = urllib_request.Request(
        endpoint_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError as error:
        raise SummaryTimeoutError(
            f"A geração do resumo excedeu o tempo limite de {settings.llm_timeout_seconds:.0f} segundos."
        ) from error
    except urllib_error.HTTPError as error:
        raise SummaryGenerationError(
            f"O endpoint de LLM configurado retornou erro HTTP {error.code}."
        ) from error
    except urllib_error.URLError as error:
        raise SummaryGenerationError(
            "Não foi possível se conectar ao endpoint de LLM configurado."
        ) from error
    except json.JSONDecodeError as error:
        raise SummaryGenerationError(
            "O endpoint de LLM configurado retornou uma resposta inválida."
        ) from error
    except Exception as error:
        raise SummaryGenerationError(
            "Ocorreu um erro inesperado durante a geração do resumo."
        ) from error

    summary = _extract_chat_completion_text(response_payload)
    if not summary:
        raise SummaryGenerationError("O modelo retornou uma resposta vazia ao gerar o resumo.")

    return summary.strip()


def _build_chat_completions_url(base_url: str) -> str:
    sanitized = base_url.strip().rstrip("/")
    if not sanitized:
        raise RuntimeError("LLM_BASE_URL não pode ser vazio.")
    return f"{sanitized}/chat/completions"


def _extract_chat_completion_text(response_payload: dict) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        fragments: list[str] = []
        for chunk in content:
            if isinstance(chunk, dict):
                text = chunk.get("text")
                if text:
                    fragments.append(str(text))
        return "\n".join(fragment.strip() for fragment in fragments if fragment.strip())

    return ""
