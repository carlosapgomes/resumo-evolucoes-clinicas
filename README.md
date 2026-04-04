# Resumo de Evoluções Clínicas

Aplicação web interna para consultar evoluções clínicas no AGHUse em um intervalo de datas, baixar o relatório em PDF, processar o texto e gerar um resumo clínico com apoio de LLM.

## Visão geral
O MVP atual faz o seguinte:

1. recebe o **registro do paciente**
2. recebe **data inicial** e **data final**
3. acessa o AGHUse
4. baixa o PDF do relatório de evoluções do período
5. extrai o texto do PDF
6. remove artefatos de paginação e identificação repetida
7. reordena as evoluções cronologicamente
8. envia o texto processado para a OpenAI
9. exibe ao usuário:
   - período consultado
   - resumo do paciente capturado na tela
   - texto processado e ordenado
   - resumo gerado

## Restrições do MVP
- sem login próprio da aplicação
- sem concorrência
- um processamento por vez
- estado mantido em memória
- polling simples para acompanhar o status
- foco em simplicidade operacional

## Stack
- **Backend:** Flask
- **Frontend:** HTML + Bootstrap + JavaScript vanilla
- **Automação:** Playwright
- **Extração de PDF:** PyMuPDF
- **LLM:** OpenAI

## Estrutura principal do projeto
```text
app.py
aghu.py
config.py
llm.py
work_manager.py
processa_evolucoes_txt.py
main.py
prompts/resumo.txt
templates/
static/
```

## Setup
### 1. Instalar dependências
```bash
uv sync
```

### 2. Instalar o navegador do Playwright, se necessário
```bash
uv run playwright install chromium
```

## Configuração
Crie um arquivo `.env` com as variáveis adequadas.

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

### Paths opcionais dos artefatos
Se não forem definidos, o sistema usa os defaults abaixo:

```env
PDF_OUTPUT_PATH=downloads/evolucoes-intervalo.pdf
TXT_OUTPUT_PATH=downloads/evolucoes-intervalo.txt
PROCESSED_TXT_OUTPUT_PATH=downloads/evolucoes-intervalo-processado.txt
SORTED_TXT_OUTPUT_PATH=downloads/evolucoes-intervalo-ordenado.txt
PDF_DEBUG_HTML_PATH=downloads/evolucoes-intervalo.debug.html
```

### Modo fixture local
Nesse modo, `EVOLUTION_FIXTURE_PATH` deve apontar para um **PDF bruto** já baixado do sistema.

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5
OPENAI_TIMEOUT_SECONDS=120
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
EVOLUTION_FIXTURE_PATH=./meu-relatorio.pdf
```

Quando `EVOLUTION_FIXTURE_PATH` está presente:
- o sistema **não acessa o AGHUse**
- usa o PDF local como entrada
- extrai, processa, ordena e resume normalmente

## Como executar
### Subir a aplicação web
```bash
uv run python app.py
```

Depois acesse:
```text
http://localhost:8000
```

### Executar manualmente via CLI
O script abaixo é útil para testes fora da interface web:

```bash
uv run python main.py 123456 --start-date 2026-03-30 --end-date 2026-04-04
```

Se as datas não forem informadas, o script usa por padrão:
- início = hoje - 5 dias
- fim = hoje

## Uso pela interface
Na página inicial, informe:
- **Registro do paciente**
- **Data inicial**
- **Data final**

A interface usa datepicker nativo do navegador.

O backend normaliza o período para o formato esperado pelo AGHUse:
- data inicial → `DD/MM/YYYY 00:01`
- data final → `DD/MM/YYYY 23:59`

Se a data final vier no futuro, ela é ajustada para a data atual.

## Pipeline interno
O fluxo atual do backend é:

1. autenticar no AGHUse
2. abrir **Internação Atual**
3. preencher o registro do paciente
4. selecionar categoria profissional `Médico`
5. capturar o resumo do paciente na tela
6. abrir `Visualizar Tudo`
7. preencher o intervalo de datas
8. clicar em `Visualizar`
9. localizar o `<object type="application/pdf">`
10. ler a URL do PDF no atributo `data`
11. baixar o PDF autenticado
12. extrair texto com PyMuPDF
13. processar o texto com `processa_evolucoes_txt.py`
14. usar o texto limpo e ordenado como entrada do LLM

## Artefatos gerados
A cada execução, o sistema sobrescreve os seguintes arquivos em `downloads/`:
- `evolucoes-intervalo.pdf`
- `evolucoes-intervalo.txt`
- `evolucoes-intervalo-processado.txt`
- `evolucoes-intervalo-ordenado.txt`
- `evolucoes-intervalo.debug.html` em caso de resposta inválida no lugar do PDF

Esses artefatos são mantidos para facilitar depuração quando uma execução falha.

## Texto usado no resumo
O texto enviado ao modelo e exibido na UI não é o bruto cru do PDF. O sistema usa a versão:
- limpa
- sem artefatos de paginação
- reordenada cronologicamente

Na prática, corresponde ao conteúdo de:
- `downloads/evolucoes-intervalo-ordenado.txt`

## Endpoints principais
- `GET /`
- `GET /health`
- `POST /api/work`
- `GET /api/work/<work_id>/status`
- `GET /resultado/<work_id>`

## Status do processamento
O endpoint de status pode passar por fases como:
- `starting`
- `logging_in`
- `opening_internacao`
- `filling_patient_record`
- `selecting_professional_category`
- `capturing_patient_summary`
- `opening_date_range`
- `filling_date_range`
- `requesting_report`
- `downloading_pdf`
- `extracting_pdf_text`
- `processing_text`
- `summarizing`
- `completed`
- `error`

## Observações
- O fluxo antigo de captura direta do texto da tela foi substituído pelo fluxo de relatório em PDF por intervalo.
- O diretório local pode continuar com o nome `pontelo`, mesmo com o produto e o repositório remoto já renomeados.
