# AGENTS.md

## Identidade do projeto
- Nome do produto: **Resumo de Evoluções Clínicas**
- Repositório remoto: `resumo-evolucoes-clinicas`
- Observação local: a pasta de trabalho ainda pode aparecer como `pontelo`; isso não altera o nome do produto.

## Objetivo do MVP
Aplicação web interna que:
1. recebe o registro do paciente e um intervalo de datas
2. consulta o AGHUse
3. baixa o PDF de evoluções do período
4. extrai e limpa o texto
5. reordena as evoluções cronologicamente
6. envia o texto processado para um LLM da OpenAI
7. mostra texto processado + resumo gerado

## Restrições atuais do MVP
- manter simplicidade
- sem login próprio da aplicação
- sem sessões de usuário
- sem concorrência entre trabalhos
- apenas **um processamento por vez**
- polling simples para acompanhar o status
- artefatos intermediários são sobrescritos em `downloads/` a cada execução

## Fluxo funcional atual
### Entrada do usuário
Na página inicial, o usuário informa:
- `patient_record`
- `start_date`
- `end_date`

As datas entram pela UI como `YYYY-MM-DD` e o backend normaliza para o formato usado no AGHUse:
- início: `DD/MM/YYYY 00:01`
- fim: `DD/MM/YYYY 23:59`

Se a data final vier no futuro, o backend normaliza para a data atual.

## Pipeline principal
O backend usa o fluxo baseado em PDF por intervalo de datas:
1. login no AGHUse
2. abertura de **Internação Atual**
3. seleção do paciente
4. seleção da categoria `Médico`
5. captura de `patient_summary` na tela
6. abertura de `Visualizar Tudo`
7. preenchimento do intervalo
8. geração do relatório
9. leitura da URL do PDF em `<object type="application/pdf">`
10. download autenticado do PDF
11. extração de texto com `PyMuPDF`
12. limpeza do TXT extraído
13. reordenação cronológica das evoluções
14. resumo com OpenAI

## Fonte de verdade para o LLM e para a UI
O texto exibido ao usuário e enviado ao modelo deve ser sempre o arquivo/texto:
- **limpo**
- **processado**
- **ordenado cronologicamente**

Na prática, isso corresponde ao conteúdo de `downloads/evolucoes-intervalo-ordenado.txt`.

## Arquivos principais
### Backend
- `app.py` — rotas Flask e orquestração do work
- `aghu.py` — automação do AGHUse, download do PDF e integração do pipeline
- `config.py` — leitura de variáveis de ambiente e paths
- `llm.py` — integração com OpenAI
- `work_manager.py` — estado em memória do processamento
- `processa_evolucoes_txt.py` — limpeza e reordenação cronológica do texto extraído

### Frontend
- `templates/base.html`
- `templates/index.html`
- `templates/result.html`
- `static/app.js`
- `static/styles.css`

### Prompt
- `prompts/resumo.txt`

## Scripts auxiliares
- `main.py` — utilitário manual para disparar a captura/resumo fora da UI web

## Artefatos gerados
Saídas padrão em `downloads/`:
- `evolucoes-intervalo.pdf`
- `evolucoes-intervalo.txt`
- `evolucoes-intervalo-processado.txt`
- `evolucoes-intervalo-ordenado.txt`
- `evolucoes-intervalo.debug.html` (quando a resposta não é um PDF válido)

Esses arquivos são úteis para depuração e podem ser sobrescritos a cada execução.

## Modo fixture
A variável `EVOLUTION_FIXTURE_PATH` aponta para um **PDF bruto**.

Nesse modo:
- o sistema não acessa o AGHUse
- copia o PDF fixture para o path de saída
- extrai o texto
- processa
- reordena
- envia o texto ao LLM normalmente

## Estados esperados do processamento
Fases atualmente previstas no endpoint de status:
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

## Observações de manutenção
- O fluxo antigo de captura direta do texto da tela foi substituído pelo fluxo de PDF por intervalo.
- Ao alterar o pipeline, preservar a simplicidade do MVP.
- Evitar introduzir concorrência, filas, banco de dados ou autenticação própria sem necessidade explícita.
- Em mudanças de UX, manter a home enxuta e a página de resultado focada em status, período, resumo do paciente, texto processado e resumo final.
