# Pontelo

Projeto Python com Playwright para automação de navegador.

## Setup

```bash
# Ativar o ambiente virtual
source .venv/bin/activate

# Instalar dependências
uv sync

# Instalar navegadores do Playwright (se necessário)
playwright install
```

## Uso

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
```

## Comandos úteis

```bash
# Executar script
uv run python main.py

# Executar testes Playwright
playwright test

# Abrir navegador interativo
playwright codegen
```
