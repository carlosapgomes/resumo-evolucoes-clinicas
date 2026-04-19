# Formato do JSON de Evoluções (para ingestão em banco e consumo por rotinas/LLM)

Este documento descreve o formato gerado pelo fluxo de extração em `path2.py`.

Arquivo de saída típico:
- `downloads/path2-<intervalo>.json`

---

## 1) Estrutura geral

O JSON é um **array de objetos** (não há objeto wrapper no topo).

```json
[
  {
    "createdAt": "2024-06-05T23:29:00",
    "signedAt": "2024-06-05T23:29:00",
    "content": "...",
    "createdBy": "Dr. Exemplo",
    "type": "medical",
    "sourceIndex": 1,
    "confidence": "high",
    "signatureLine": "Elaborado e assinado por Dr. Exemplo, Crm 12345 em 05/06/2024 23:29",
    "admissionKey": "br.gov.mec.aghu.paciente.prontuarioonline.vo.InternacaoVO@abcd1234",
    "admissionRowIndex": 1,
    "admissionStart": "2024-04-22",
    "admissionEnd": "2024-05-07",
    "chunkStart": "2024-04-22",
    "chunkEnd": "2024-05-06",
    "requestedStart": "2024-04-20",
    "requestedEnd": "2024-05-10"
  }
]
```

---

## 2) Campos por evolução

### `createdAt` (string, obrigatório)
- Data/hora inicial da evolução.
- Formato: `YYYY-MM-DDTHH:MM:SS` (ISO sem timezone explícito).
- Exemplo: `"2024-06-06T09:54:00"`.

### `signedAt` (string, obrigatório)
- Data/hora extraída da linha de assinatura (`signatureLine`).
- Formato: `YYYY-MM-DDTHH:MM:SS`.
- Exemplo: `"2024-06-06T10:14:00"`.

### `content` (string, obrigatório)
- Corpo textual da evolução.
- Não inclui a data/hora inicial nem a linha final de assinatura.
- Mantém quebras de linha para preservar contexto clínico.

### `createdBy` (string, obrigatório)
- Nome/profissional extraído da assinatura.
- Exemplo: `"Enf. Fulana de Tal"`.

### `type` (string, obrigatório)
- Classificação por conselho/indícios na assinatura e conteúdo:
  - `medical` → encontrou `Crm`
  - `nursing` → encontrou `Coren`
  - `phisiotherapy` → encontrou `Crefito`
  - `nutrition` → encontrou `Crn` / `Crn5` etc.
  - `speech_therapy` → encontrou `Crefono`
  - `dentistry` → encontrou `Cro` na assinatura **ou** indício textual de odontologia no conteúdo
  - `other` → não encontrou padrão reconhecido

> Observação: o valor `phisiotherapy` está escrito assim no gerador atual e deve ser tratado como valor canônico para compatibilidade.

### `sourceIndex` (integer, obrigatório)
- Índice sequencial da evolução na ordem original extraída do documento.
- Começa em `1`.

### `confidence` (string, obrigatório)
- Confiança da classificação `type`:
  - `high` para `medical`, `nursing`, `phisiotherapy`, `nutrition`, `speech_therapy`, `dentistry`
  - `low` para `other`

### `signatureLine` (string, obrigatório)
- Linha de fechamento da evolução usada como marcador final.
- Padrão esperado: começa com `Elaborado...` e termina em `em DD/MM/YYYY HH:MM` (ou `HH:MM:SS`).

### `admissionKey` (string, obrigatório)
- Identificador da linha de internação na tabela (`data-rk`).
- Útil para rastreabilidade e deduplicação entre chunks.

### `admissionRowIndex` (integer, obrigatório)
- Índice de linha da internação na tabela (`data-ri`) no momento da coleta.

### `admissionStart` / `admissionEnd` (string ISO date, obrigatório)
- Período da internação de origem (`YYYY-MM-DD`).
- `admissionEnd` pode ser `null` quando não há alta (internação atual).

### `chunkStart` / `chunkEnd` (string ISO date, obrigatório)
- Janela efetiva de extração do chunk de onde a evolução veio.
- A coleta usa chunks de até 15 dias, com sobreposição de 1 dia.

### `requestedStart` / `requestedEnd` (string ISO date, obrigatório)
- Intervalo original solicitado pelo usuário para o processamento consolidado.

---

## 3) Regras de segmentação e coleta usadas na extração

1. A evolução inicia em uma linha de data/hora (`DD/MM/YYYY HH:MM`).
2. A evolução termina na linha `signatureLine` (padrão `Elaborado ... em ...`).
3. A próxima linha de data/hora abre a próxima evolução.
4. Datas repetidas no meio de texto (por quebra de página) não abrem nova evolução.
5. A seleção de internações é automática: inclui toda internação com interseção no intervalo solicitado.
6. O intervalo é fragmentado em chunks de até 15 dias com sobreposição de 1 dia.
7. Há deduplicação no consolidado por chave lógica: `admissionKey + createdAt + signatureLine`.

---

## 4) Recomendação de modelagem para banco

Tabela sugerida: `clinical_evolutions`

Campos mínimos:
- `id` (PK)
- `created_at` (timestamp)
- `signed_at` (timestamp)
- `created_by` (text)
- `evolution_type` (text)  -- `medical|nursing|phisiotherapy|nutrition|speech_therapy|dentistry|other`
- `confidence` (text)      -- `high|low`
- `content` (text)
- `signature_line` (text)
- `source_index` (int)
- `admission_key` (text)
- `admission_row_index` (int)
- `admission_start` (date)
- `admission_end` (date null)
- `chunk_start` (date)
- `chunk_end` (date)
- `requested_start` (date)
- `requested_end` (date)
- `source_file` (text)     -- nome/identificador do JSON de origem
- `ingested_at` (timestamp)

Índices recomendados:
- `(created_at)`
- `(evolution_type, created_at)`
- `(admission_key, created_at)`
- `(source_file, source_index)`
- unicidade lógica para dedupe: `(source_file, admission_key, created_at, signature_line)`

---

## 5) Recomendações para rotinas de ingestão

1. Validar que o topo do JSON é array.
2. Validar presença de todos os campos obrigatórios.
3. Validar formatos de data/hora (`createdAt`, `signedAt`).
4. Tratar `type` fora da lista conhecida como `other`.
   - Lista conhecida atual: `medical`, `nursing`, `phisiotherapy`, `nutrition`, `speech_therapy`, `dentistry`, `other`.
5. Preservar `sourceIndex` para auditoria/replay.
6. Registrar arquivo de origem e data de ingestão.
7. Implementar upsert por chave lógica de dedupe (ex.: `source_file + admission_key + created_at + signature_line`).

---

## 6) Contrato de compatibilidade

Para não quebrar consumidores existentes:
- manter nomes de campos exatamente como estão (`camelCase`)
- manter `type = "phisiotherapy"` enquanto o gerador atual usar esse valor
- adicionar novos campos apenas de forma retrocompatível (sem remover os atuais)

---

## 7) Exemplo prático (item único)

```json
{
  "createdAt": "2024-06-06T04:26:00",
  "signedAt": "2024-06-06T04:26:00",
  "content": "Leito: UC06F\n#CENTRO CIRÚRGICO#\n...",
  "createdBy": "Enf. Ana Carla Moura Macedo Santana",
  "type": "nursing",
  "sourceIndex": 4,
  "confidence": "high",
  "signatureLine": "Elaborado e assinado por Enf. Ana Carla Moura Macedo Santana, Coren 265780 em 06/06/2024 04:26",
  "admissionKey": "br.gov.mec.aghu.paciente.prontuarioonline.vo.InternacaoVO@1234abcd",
  "admissionRowIndex": 1,
  "admissionStart": "2024-04-22",
  "admissionEnd": "2024-05-07",
  "chunkStart": "2024-04-22",
  "chunkEnd": "2024-04-30",
  "requestedStart": "2024-04-20",
  "requestedEnd": "2024-05-10"
}
```
