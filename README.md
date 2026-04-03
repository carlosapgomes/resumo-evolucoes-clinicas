# Resumo de Evoluções Clínicas

Aplicação web interna para captura de evoluções no AGHUse e geração de resumo clínico com apoio de LLM.

## Setup

```bash
# Instalar dependências
uv sync

# Instalar navegadores do Playwright, se necessário
uv run playwright install
```

## Configuração

Crie um arquivo `.env` com as variáveis necessárias.

### Modo normal

```env
AGHUSE_URL=https://...
USER_NAME=...
USER_PW=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5
OPENAI_TIMEOUT_SECONDS=120
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
```

### Modo de teste com fixture local

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5
OPENAI_TIMEOUT_SECONDS=120
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
EVOLUTION_FIXTURE_PATH=./evolucoes.txt
```

## Uso

### Subir a aplicação web

```bash
uv run python app.py
```

### Testar apenas a captura

```bash
uv run python main.py 123456
```

## Endpoints principais

- `GET /`
- `GET /health`
- `POST /api/work`
- `GET /api/work/<work_id>/status`
- `GET /resultado/<work_id>`
