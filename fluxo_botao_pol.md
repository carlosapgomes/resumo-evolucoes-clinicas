# Fluxo do botão POL / investigação da rota de internações

Data da investigação: **2026-04-11**

## Objetivo desta sessão
Documentar o que foi investigado no fluxo acessado pelo botão `#polMenu`, com foco em:
- navegar pelo caminho de **internações**
- abrir a consulta de **evolução por intervalo**
- tentar reproduzir a estratégia já usada no projeto atual para obter o **PDF bruto**
- se não fosse possível, verificar se a nova rota expõe **texto bruto** ou algum outro artefato equivalente

> Resultado resumido: foi possível automatizar a navegação até a visualização do relatório, mas **não foi encontrado um caminho oculto para PDF nem para texto puro** com o perfil atual. A rota observada renderiza as páginas do relatório como **imagens PNG por página**.

---

## Arquivos envolvidos nesta sessão
- Script explorado e ajustado: `path2.py`
- Referência do fluxo atual do projeto: `source_system.py`
- Documento gerado nesta sessão: `fluxo_botao_pol.md`

Arquivos de apoio/snapshots gerados durante os testes:
- `debug/frame_pol-after-dates.html`
- `debug/frame_pol-after-visualizar.html`
- `debug/report-runtime.html`
- `debug/report-via-request.html`
- `downloads/path2-evolucoes-intervalo.debug.html`
- alguns arquivos binários temporários em `downloads/` usados só para inspeção de respostas HTTP

---

## Ajustes feitos no `path2.py`
Durante a sessão, o script `path2.py` foi ajustado para facilitar a exploração do fluxo novo.

### Ajustes principais
1. **Uso das variáveis do `.env`**
   - `SOURCE_SYSTEM_URL`
   - `SOURCE_SYSTEM_USERNAME`
   - `SOURCE_SYSTEM_PASSWORD`

2. **Navegação robusta até a tela de pesquisa POL**
   - inclusão de clique explícito no botão `#polMenu`
   - tentativa prioritária com `DOM click`, porque o clique padrão do Playwright sofria interceptação visual

3. **Timeouts de segurança**
   - uso de timeouts altos e esperas adicionais para telas lentas
   - inclusão de espera explícita para estabilização antes de seguir

4. **Preenchimento do intervalo de datas**
   - suporte para preencher as datas diretamente no modal de evolução

5. **Seleção de ordenação Crescente**
   - em vez de depender apenas do clique visual no componente PrimeFaces, a seleção passou a ser feita diretamente no `select` oculto

6. **Espera pela tela de relatório**
   - polling da URL do `iframe[name="frame_pol"]` até detectar a navegação para a página de relatório

7. **Fallbacks para descoberta de PDF**
   - tentativa via `<object type="application/pdf">`
   - tentativa via URL do viewer
   - tentativa via formulários internos do relatório

> Esses ajustes deixaram o script apto a chegar até a visualização do relatório novo, mesmo sem resolver a obtenção do PDF.

---

## Fluxo funcional confirmado
O seguinte fluxo foi confirmado como executável com o perfil atual:

1. abrir a página inicial do sistema fonte
2. autenticar com usuário e senha
3. fechar diálogos iniciais
4. abrir a tela POL pelo botão `#polMenu`
5. preencher o prontuário no campo `#prontuarioInput`
6. abrir `Pesquisa Avançada`
7. selecionar `Internações`
8. acessar `Detalhes da Internação`
9. clicar em `Evolução`
10. preencher `dataInicio`
11. preencher `dataFim`
12. ajustar a ordenação para `Crescente`
13. clicar em `Visualizar`
14. aguardar a navegação do iframe para:
   - `/pages/ambulatorio/relatorios/relatorioAnaEvoInternacaoPdf.xhtml?cid=4`

---

## Identificadores e elementos relevantes encontrados

### Abertura da área POL
- botão principal: `#polMenu`
- observação importante: o clique padrão sofria interceptação visual; o `DOM click` funcionou melhor

### Tela de pesquisa
- campo de prontuário: `#prontuarioInput`
- link: `Pesquisa Avançada`
- aba/resultado: `Internações`

### Dentro do iframe principal
- iframe: `iframe[name="frame_pol"]`
- link de entrada: `Detalhes da Internação`
- botão: `Evolução`

### Modal de evolução
- início: `dataInicio:dataInicio:inputId_input`
- fim: `dataFim:dataFim:inputId_input`
- ordenação:
  - container: `ordenacaoCrescente:ordenacaoCrescente:inputId`
  - `select` oculto: `ordenacaoCrescente:ordenacaoCrescente:inputId_input`
  - label visual: `ordenacaoCrescente:ordenacaoCrescente:inputId_label`
- botão visualizar:
  - `bt_UltimosQuinzedias:button`
  - apesar do nome, este é o botão efetivo `Visualizar` do modal

### Tela de relatório
URL detectada:
- `/pages/ambulatorio/relatorios/relatorioAnaEvoInternacaoPdf.xhtml?cid=4`

Elementos relevantes:
- viewer HTML com `#viewer` e páginas `#pageContainerN`
- imagens por página com classe:
  - `img.pdfviewer-img`
- botão de impressão:
  - `j_idt42:bt_imprimir:button`
  - estava **desabilitado** com o perfil atual
- formulário do botão imprimir:
  - `form id="j_idt42"`
- links ocultos relacionados a download:
  - `downloadLinkAjax`
  - `downloadLinkAjaxFrame`
- formulário desses links:
  - `form id="printLinks"`
- iframe interno de download:
  - `print_download_frame`

---

## Problema inicial resolvido: clique no botão POL
No início dos testes, o fluxo travava ao tentar abrir a área POL.

### Sintoma
O Playwright reportava que o clique em `#polMenu` estava sendo interceptado por outro elemento visual.

### Evidência observada
O erro mostrava interceptação por uma área visual semelhante a:
- `.casca-menu-center`

### Solução aplicada
Foi priorizado:
- `element.click()` via DOM (`evaluate`) no `#polMenu`

### Resultado
Após isso, a tela de pesquisa POL passou a abrir corretamente e o campo `#prontuarioInput` ficou acessível.

---

## Problema do seletor de ordenação
No modal de evolução, o seletor visual de ordenação também apresentava instabilidade.

### Sintoma
O clique no gatilho visual do `selectonemenu` falhava por interceptação do overlay do modal:
- `#modalEvolucao_modal`

### Solução aplicada
Em vez de depender do clique visual, a solução foi:
- acessar diretamente o `select` oculto
- escolher a opção cujo texto é `Crescente`
- atualizar a label visual
- disparar evento `change`

### Resultado
A ordenação passou a ser configurada de forma estável.

---

## Testes com intervalo menor
Como o paciente inicialmente usado gera um relatório muito grande, foi sugerido e executado um teste com intervalo mais curto para reduzir o tempo dos ciclos de investigação.

### Intervalos usados
- intervalo inicial explorado: `05/06/2024` até `01/07/2024`
- intervalo curto de depuração: `05/06/2024` até `07/06/2024`

### Benefício do intervalo curto
- menos páginas
- menos ruído de rede
- mais facilidade para identificar endpoints relevantes

Mesmo com o intervalo curto, o comportamento da rota permaneceu essencialmente o mesmo.

---

## O que foi descoberto sobre a rota de relatório
Esta foi a descoberta principal da sessão.

### Comportamento observado
A página de relatório **não** expõe um `<object type="application/pdf">` como a rota antiga do projeto.

Em vez disso, ela renderiza um viewer HTML com várias páginas, cada uma baseada em uma imagem:
- `dynamiccontent.properties.xhtml?...&pdf_page=0`
- `dynamiccontent.properties.xhtml?...&pdf_page=1`
- etc.

### Tipo de resposta das páginas
As requisições das páginas responderam com:
- `Content-Type: image/png`

### Conclusão técnica
Com o perfil atual, a nova rota está entregando a visualização do relatório como **imagens PNG por página**, e não como PDF embutido ou texto HTML.

---

## Hipótese levantada durante a sessão
Foi levantada a hipótese de que, assim como na rota antiga, pudesse existir:
- um endpoint de PDF oculto
- ou um formulário interno que gerasse um PDF mesmo sem o botão visível habilitado

Essa hipótese motivou a exploração abaixo.

---

## Estratégias testadas para achar o PDF oculto

### 1. Procurar `<object type="application/pdf">`
Tentativa inspirada no fluxo atual do projeto.

#### Resultado
- **falhou**
- nenhum `<object>` com PDF apareceu nessa rota

---

### 2. Inferir a URL do PDF pelo iframe/viewer
Foi tentado descobrir se a própria URL do `iframe` ou algum parâmetro interno apontava para um PDF direto.

#### Resultado
- **falhou**
- a URL do iframe apontava para a própria página HTML do relatório
- não surgiu nenhuma URL direta de PDF

---

### 3. Acionar links ocultos do relatório
Foram testados os links:
- `downloadLinkAjax`
- `downloadLinkAjaxFrame`

Esses links submetem o formulário `printLinks` para o `print_download_frame`.

#### Resultado
- retornaram **HTML da tela de relatório**
- não retornaram binário `%PDF-`
- nenhum `Content-Disposition` de PDF foi observado

---

### 4. Fazer POST manual no formulário `printLinks`
Foi reproduzida manualmente a submissão do formulário de download do relatório, usando o `javax.faces.ViewState` capturado na tela.

#### Resultado
- retornou **HTML**
- não retornou PDF

---

### 5. Fazer POST manual no formulário do botão `Imprimir`
Mesmo com o botão `Imprimir` desabilitado visualmente, foi tentado fazer POST direto no formulário `j_idt42` com diferentes combinações de payload.

Payloads testados incluíram, entre outros:
- envio tradicional do nome do botão
- envio textual do valor `Imprimir`
- envio como requisição parcial JSF (`javax.faces.partial.ajax=true`)

#### Resultado
- respostas HTML ou XML parcial JSF
- **nenhuma resposta trouxe PDF**
- nenhum `Content-Type: application/pdf`
- nenhum corpo iniciando com `%PDF-`

---

### 6. Manipular a URL das imagens do viewer
Como cada página vinha de um endpoint `dynamiccontent.properties`, foram testadas variações como:
- remover `pdf_page`
- remover `uid`
- alterar `pfdrt`

#### Resultado
- resposta `image/png`
- ou erro/404/500
- **nenhuma variação retornou PDF**

---

## O que foi descoberto sobre texto puro
A meta final da exploração mudou durante a sessão: o PDF passou a ser entendido apenas como um meio possível para chegar ao texto.

### Pergunta investigada
A tela de relatório expõe o conteúdo clínico como texto no HTML?

### Resultado
Tudo indica que **não**.

O que foi observado na página:
- estrutura HTML do viewer
- toolbar
- containers de página
- imagens `img.pdfviewer-img`

O que **não** foi observado:
- camada de texto selecionável
- blocos `<div>` / `<span>` / `<pre>` com o texto clínico
- endpoint textual evidente
- PDF embutido

### Conclusão prática
Com o perfil atual, a rota parece expor apenas:
- **HTML da casca do viewer**
- **PNG por página**

Não foi encontrado texto puro no DOM nem endpoint evidente de texto.

---

## Papel do botão `Imprimir`
O usuário informou durante a sessão que o login atual **não tem perfil para gerar PDF**.

Isso explica por que o botão:
- `j_idt42:bt_imprimir:button`

aparece:
- presente na página
- mas com atributo `disabled`
- e classe visual de botão desabilitado

### Impacto dessa descoberta
Isso reforça a interpretação de que:
- a página de relatório foi construída para suportar geração/impressão
- porém o perfil atual não consegue ativar o caminho oficial de impressão/PDF
- por isso ainda existem “resquícios” de formulários e links de download, mas eles não produziram PDF com o perfil atual

---

## Conclusão final da sessão
### O que foi conseguido
- automatizar a navegação até a nova visualização de relatório pela rota de internações
- tornar o clique no botão POL confiável
- estabilizar o preenchimento do modal de evolução
- selecionar ordenação crescente de forma robusta
- confirmar a URL e o comportamento da tela de relatório

### O que **não** foi conseguido
- obter PDF bruto
- obter texto puro
- reproduzir na nova rota o mesmo mecanismo de extração usado hoje no fluxo antigo

### Conclusão técnica atual
Com o perfil atual, **não foi encontrado um caminho oculto equivalente ao da rota antiga** para obter PDF ou texto puro nessa nova rota.

O máximo confirmado foi:
- visualização HTML do relatório
- imagens PNG por página

---

## Critério de parada adotado
Foi combinado interromper a investigação se a busca pelo caminho oculto não tivesse sucesso, sem avançar para OCR ou qualquer estratégia baseada em imagem.

Portanto, **a investigação foi encerrada neste ponto**.

Não foram seguidas estratégias como:
- OCR das imagens
- montagem local de PDF a partir das páginas PNG
- extração textual via reconhecimento óptico

---

## Próximo passo recomendado quando o perfil for atualizado
Quando o login receber permissão para habilitar o botão **Imprimir**, retomar a investigação a partir deste ponto, com foco em:

1. repetir o fluxo curto de 2 dias
2. confirmar se `j_idt42:bt_imprimir:button` deixa de estar desabilitado
3. observar a nova requisição disparada ao clicar em `Imprimir`
4. registrar:
   - método HTTP
   - URL final
   - `Content-Type`
   - `Content-Disposition`
   - corpo inicial da resposta (`%PDF-` ou não)
5. verificar se o PDF poderá então ser baixado por:
   - clique normal do botão
   - POST manual no formulário `j_idt42`
   - link interno `printLinks`
   - ou algum endpoint novo que passe a aparecer

---

## Sugestão operacional para a retomada
Ao retomar com o login atualizado:
- usar primeiro um **intervalo de 2 dias**
- manter o mesmo prontuário de teste, se fizer sentido
- capturar rede antes e depois do clique em `Imprimir`
- verificar se aparece:
  - `application/pdf`
  - `content-disposition: attachment`
  - ou algum novo recurso não visto nesta sessão

---

## Resumo executivo
O fluxo do botão `#polMenu` foi automatizado com sucesso até a visualização do relatório de evolução por internação. No entanto, com o perfil atual, a rota acessada não expôs PDF nem texto puro. A página do relatório renderizou o conteúdo como imagens PNG por página, e todas as tentativas de achar um caminho oculto para PDF falharam. A principal pendência para a próxima etapa é repetir os testes com um login que habilite o botão **Imprimir**.
