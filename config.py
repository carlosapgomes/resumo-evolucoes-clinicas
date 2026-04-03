import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    aghuse_url: str | None
    user_name: str | None
    user_pw: str | None
    openai_api_key: str
    openai_model: str = "gpt-5"
    openai_timeout_seconds: float = 120.0
    flask_host: str = "0.0.0.0"
    flask_port: int = 8000
    evolution_fixture_path: str | None = None


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    flask_port = int(os.getenv("FLASK_PORT", "8000"))
    openai_timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    evolution_fixture_path = os.getenv("EVOLUTION_FIXTURE_PATH")

    aghuse_url = os.getenv("AGHUSE_URL")
    user_name = os.getenv("USER_NAME")
    user_pw = os.getenv("USER_PW")

    if not evolution_fixture_path:
        aghuse_url = required_env("AGHUSE_URL")
        user_name = required_env("USER_NAME")
        user_pw = required_env("USER_PW")

    return Settings(
        aghuse_url=aghuse_url,
        user_name=user_name,
        user_pw=user_pw,
        openai_api_key=required_env("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5"),
        openai_timeout_seconds=openai_timeout_seconds,
        flask_host=os.getenv("FLASK_HOST", "0.0.0.0"),
        flask_port=flask_port,
        evolution_fixture_path=evolution_fixture_path,
    )
