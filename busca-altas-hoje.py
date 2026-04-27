#!/usr/bin/env python3
"""
Automação para extrair a lista de pacientes com alta hoje.

Fluxo:
  1. Login no sistema fonte
  2. Fechar diálogos iniciais
  3. Clicar no ícone de Altas do Dia (id: _icon_img_20352)
  4. Aguardar carregamento do iframe i_frame_altas_do_dia
  5. Clicar em "Visualizar Impressão"
  6. Aguardar e capturar o PDF gerado
  7. Fazer download autenticado do PDF
  8. Extrair tabela de pacientes do PDF via PyMuPDF
  9. Salvar resultado como JSON em downloads/

Colunas extraídas:
  - prontuario   (número do prontuário, sem /)
  - nome          (nome do paciente)
  - leito         (leito)
  - especialidade (abreviação da especialidade)
  - data_internacao (data de internamento)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import pymupdf
from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, FrameLocator, Page, sync_playwright

from source_system import (
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    esperar_locator_com_retry,
    fechar_dialogos_iniciais,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
ALTAS_IFRAME_NAME = "i_frame_altas_do_dia"
ALTAS_ICON_ID = "_icon_img_20352"

DOWNLOADS_DIR = Path("downloads")
DEBUG_DIR = Path("debug")

PDF_OUTPUT_NAME = "altas-hoje.pdf"
JSON_OUTPUT_PREFIX = "altas-hoje"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai lista de pacientes com alta hoje do sistema fonte."
    )
    parser.add_argument("--headless", action="store_true", help="Executa sem interface gráfica")
    return parser.parse_args()


def wait_visible(locator, timeout: int = 10000) -> bool:
    """Aguarda elemento ficar visível."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def safe_click(locator, label: str, timeout: int = 15000) -> bool:
    """Clica em um locator com fallback (force click e DOM click)."""
    if not wait_visible(locator, timeout=timeout):
        print(f"  [!] Não visível para clique: {label}")
        return False

    target = locator.first
    for force in (False, True):
        try:
            target.click(timeout=timeout, force=force)
            return True
        except Exception:
            continue

    try:
        target.evaluate("el => el.click()")
        return True
    except Exception as e:
        print(f"  [!] Clique falhou ({label}): {e}")
        return False


def get_altas_frame_locator(page: Page) -> FrameLocator:
    """Retorna o FrameLocator para o iframe de altas do dia."""
    return page.frame_locator(f'iframe[name="{ALTAS_IFRAME_NAME}"]')


def wait_altas_frame_ready(page: Page, timeout_ms: int = 60000) -> FrameLocator:
    """Aguarda o iframe de altas do dia carregar."""
    print("[i] Aguardando iframe de altas do dia carregar...")
    frame_locator = get_altas_frame_locator(page)
    start = time.time()
    deadline = start + timeout_ms / 1000

    while time.time() < deadline:
        try:
            frame_locator.locator("body").first.wait_for(state="attached", timeout=2000)
            print("[i] Iframe de altas do dia carregado.")
            return frame_locator
        except Exception:
            page.wait_for_timeout(500)

    raise RuntimeError("Timeout aguardando iframe de altas do dia.")


def click_altas_icon(page: Page) -> None:
    """Clica no ícone de Altas do Dia."""
    icon = page.locator(f'[id="{ALTAS_ICON_ID}"]')
    if not safe_click(icon, "ícone Altas do Dia", timeout=20000):
        raise RuntimeError("Não foi possível clicar no ícone de Altas do Dia.")
    print("[i] Ícone Altas do Dia clicado.")


def click_visualizar_impressao(frame_locator: FrameLocator) -> None:
    """Clica no botão Visualizar Impressão dentro do iframe de altas."""
    btn = frame_locator.get_by_role("button", name="Visualizar Impressão")
    if not safe_click(btn, "botão Visualizar Impressão", timeout=20000):
        raise RuntimeError("Não foi possível clicar em Visualizar Impressão.")
    print("[i] Botão Visualizar Impressão clicado.")


def get_pdf_url_from_frame(frame_locator: FrameLocator, page: Page) -> str:
    """Extrai a URL do PDF do <object> dentro do iframe de altas."""
    print("[i] Aguardando objeto PDF aparecer...")

    pdf_object = esperar_locator_com_retry(
        page,
        "visualizador PDF no iframe de altas",
        lambda: frame_locator.locator('object[type="application/pdf"]'),
        timeout=120000,
    )

    ultimo_data = None
    for tentativa in range(1, 4):
        pdf_url = pdf_object.get_attribute("data")
        if pdf_url:
            absolute_url = urljoin(page.url, pdf_url)
            print(f"[i] URL do PDF: {absolute_url}")
            return absolute_url

        ultimo_data = pdf_url
        if tentativa < 3:
            print(f"  [!] Tentativa {tentativa}/3: atributo 'data' não disponível. Aguardando...")
            page.wait_for_timeout(2000)

    raise RuntimeError(
        "O elemento <object> do PDF apareceu, mas o atributo 'data' não ficou disponível. "
        f"Último valor: {ultimo_data!r}"
    )


def download_pdf(context: BrowserContext, pdf_url: str, output_path: Path) -> None:
    """Faz download autenticado do PDF."""
    print(f"[i] Baixando PDF de {pdf_url}...")
    response = context.request.get(pdf_url, timeout=120000)

    if not response.ok:
        raise RuntimeError(f"Falha ao baixar PDF. HTTP {response.status}")

    content_type = (response.headers.get("content-type") or "").lower()
    body = response.body()

    print(f"  Content-Type: {content_type}")
    print(f"  Tamanho: {len(body)} bytes")

    if not body.startswith(b"%PDF-"):
        # Salva para debug
        debug_path = output_path.with_suffix(".debug.html")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_bytes(body)
        raise RuntimeError(
            f"Conteúdo retornado não é um PDF válido. Salvo em: {debug_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)
    print(f"[i] PDF salvo em: {output_path}")


# ---------------------------------------------------------------------------
# Extração da tabela do PDF
# ---------------------------------------------------------------------------
# O PDF de altas do dia é gerado em landscape (rotação 90°).
# Os pacientes são dispostos em colunas verticais ("bands" no eixo X).
# Cada banda de paciente contém:
#   - Coluna principal (x): Pront, Nome, CRM, Médico, Data Int
#   - Coluna secundária (x+1): Leito, Esp, (Alta Ant)
#   - Continuação (x+10~15): nomes longos de médico

# Padrões
_RE_PRONTUARIO = re.compile(r"^\d{2,7}/\d$")          # ex: 123456/7
_RE_DATA_CURTA = re.compile(r"^\d{2}/\d{2}/\d{2}$")    # ex: 15/04/26 (DD/MM/YY)
_RE_DATA_LONGA = re.compile(r"^\d{2}/\d{2}/\d{4}$")    # ex: 15/04/2026 (DD/MM/YYYY)
_RE_CRM = re.compile(r"^\d{4,6}$")                       # CRM: 4-6 dígitos
_RE_CRM_PLACEHOLDER = re.compile(r"^CRM([A-Z]{2})?$", re.IGNORECASE)  # placeholder: "CRM" ou "CRMBA"
_RE_SO_NUMEROS = re.compile(r"\D")
# Prefixos entre prontuário e nome: 1-2 caracteres maiúsculos (ex: "O"=óbito, "RN"=recém-nascido)
_RE_PREFIXO = re.compile(r"^[A-Z]{1,2}$")


def _clean_prontuario(raw: str) -> str:
    """Remove `/` e mantém só dígitos. Ex: '123456/7' → '1234567'."""
    return _RE_SO_NUMEROS.sub("", raw)


def _normalize_data(raw: str) -> str:
    """Normaliza data para DD/MM/YYYY. Ex: '15/04/26' → '15/04/2026'."""
    if not raw:
        return raw
    parts = raw.split("/")
    if len(parts) != 3:
        return raw
    day, month, year = parts
    if len(year) == 2:
        year = "20" + year
    return f"{day}/{month}/{year}"


def extract_patients_from_pdf(pdf_path: Path) -> list[dict[str, str]]:
    """
    Extrai a lista de pacientes do PDF de altas.

    Usa análise de coordenadas x/y pois o PDF é landscape rotacionado
    e o texto extraído não segue a ordem visual das colunas.
    """
    if not pdf_path.exists():
        raise RuntimeError(f"PDF não encontrado: {pdf_path}")

    print(f"[i] Extraindo tabela de {pdf_path}...")
    all_patients: list[dict[str, str]] = []

    with pymupdf.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            words = page.get_text("words")  # [(x0,y0,x1,y1,text,block,line,word), ...]
            if not words:
                continue

            print(f"  Página {page_num}: {len(words)} palavras, analisando bandas X...")
            patients = _extract_patients_by_x_bands(words)
            print(f"  Pacientes encontrados: {len(patients)}")
            all_patients.extend(patients)

    # Pós-processamento: limpa prontuários e normaliza datas
    for p in all_patients:
        if p.get("prontuario"):
            p["prontuario"] = _clean_prontuario(p["prontuario"])
        if p.get("data_internacao"):
            p["data_internacao"] = _normalize_data(p["data_internacao"])

    return all_patients


def _extract_patients_by_x_bands(words: list) -> list[dict[str, str]]:
    """
    Agrupa palavras por bandas de coordenada X e extrai pacientes.
    """
    # Encontra todas as palavras que são prontuários (marcam início de paciente)
    pront_words = []
    for w in words:
        if _RE_PRONTUARIO.match(w[4]):
            pront_words.append(w)

    if not pront_words:
        return []

    # Agrupa prontuários por banda X (tolerância de ±1.5px)
    bands = _group_by_x_band(pront_words, tolerance=1.5)

    patients = []
    for band_x in sorted(bands.keys()):
        # Coleta todas as palavras na banda principal (x) e secundária (x+1)
        main_words = []
        secondary_words = []

        for w in words:
            wx = round(w[0], 1)
            if abs(wx - band_x) < 1.0:
                main_words.append(w)
            elif abs(wx - (band_x + 1.0)) < 1.0:
                secondary_words.append(w)

        if not main_words:
            continue

        # Ordena do topo para baixo (y decrescente)
        main_words.sort(key=lambda w: -w[1])
        secondary_words.sort(key=lambda w: -w[1])

        patient = _parse_patient_band(main_words, secondary_words)
        if patient:
            patients.append(patient)

    return patients


def _group_by_x_band(pront_words: list, tolerance: float = 1.5) -> dict[float, list]:
    """Agrupa palavras por bandas de coordenada X."""
    sorted_words = sorted(pront_words, key=lambda w: w[0])
    bands: dict[float, list] = {}
    current_band_x = None

    for w in sorted_words:
        wx = round(w[0], 1)
        if current_band_x is None or (wx - current_band_x) > tolerance:
            current_band_x = wx
            bands[current_band_x] = []
        bands[current_band_x].append(w)

    return bands


def _parse_patient_band(
    main_words: list, secondary_words: list
) -> dict[str, str] | None:
    """
    Faz parsing dos campos de um paciente a partir das palavras da banda.

    Estrutura do PDF (landscape rotacionado 90°):
      Coluna principal (y decrescente = topo → base):
        Pront → [prefixo 1-2 char] → Nome... → CRM → Médico... → Data Int

      Coluna secundária (y decrescente):
        Leito → Esp → [Alta Ant (data opcional)]

    Robustez:
      - Prefixos detectados por tamanho (1-2 char maiúsculo), não por lista fixa.
      - Especialidade e leito extraídos por posição estrutural (ordem y),
        não por regex de conteúdo — funciona com qualquer código novo.
      - Datas aceitas em DD/MM/YY e DD/MM/YYYY.
    """
    pront = ""
    nome_parts: list[str] = []
    data_int = ""
    leito = ""
    esp = ""

    # --- Coluna principal ---
    i = 0
    mw = main_words

    # 1. Prontuário (sempre o primeiro)
    if i < len(mw) and _RE_PRONTUARIO.match(mw[i][4]):
        pront = mw[i][4]
        i += 1

    # 2. Pula prefixos: palavras de 1-2 caracteres maiúsculos entre Pront e Nome
    #    Exemplos conhecidos: "O" (óbito), "RN" (recém-nascido).
    #    Qualquer prefixo novo no mesmo formato será ignorado automaticamente.
    while i < len(mw) and _RE_PREFIXO.match(mw[i][4]):
        i += 1

    # 3. Nome do paciente: palavras até o CRM (número de 4-6 dígitos ou placeholder "CRM")
    while i < len(mw):
        word = mw[i][4]
        if _RE_CRM.match(word) or _RE_CRM_PLACEHOLDER.match(word):
            i += 1
            break
        nome_parts.append(word)
        i += 1

    # 4. Pula nome do médico e captura Data Int (DD/MM/YY ou DD/MM/YYYY)
    while i < len(mw):
        word = mw[i][4]
        if _RE_DATA_CURTA.match(word) or _RE_DATA_LONGA.match(word):
            data_int = word
            i += 1
            break
        i += 1

    # Se não achou Data Int, varre o restante
    if not data_int:
        while i < len(mw):
            word = mw[i][4]
            if _RE_DATA_CURTA.match(word) or _RE_DATA_LONGA.match(word):
                data_int = word
                break
            i += 1

    # --- Coluna secundária ---
    # Estrutura física (y decrescente): Leito → Esp → [Alta Ant]
    # Em vez de adivinhar conteúdo, usamos a posição: primeiro não-data = leito,
    # último não-data (se diferente do primeiro) = especialidade.
    # Isso funciona com QUALQUER código de especialidade e qualquer formato de leito.
    sw = secondary_words
    seen_texts: set[str] = set()
    sw_dedup = []
    for w in sw:
        if w[4] not in seen_texts:
            seen_texts.add(w[4])
            sw_dedup.append(w)

    # Remove datas (Alta Ant) — aceita ambos os formatos
    valid = [
        w for w in sw_dedup
        if not _RE_DATA_CURTA.match(w[4]) and not _RE_DATA_LONGA.match(w[4])
    ]

    if len(valid) >= 2:
        # Caso normal: Leito (1ª posição) + Esp (última posição)
        leito = valid[0][4]
        esp = valid[-1][4]
    elif len(valid) == 1:
        # Caso ambíguo: um único valor não-data.
        # Heurística: se parece especialidade (2-4 letras maiúsculas), é esp;
        # caso contrário, assume leito.
        word = valid[0][4]
        if 2 <= len(word) <= 4 and word.isupper() and word.isalpha():
            esp = word
        else:
            leito = word
    # len(valid) == 0: ambos vazios (raro mas possível)

    # --- Validação ---
    nome = " ".join(nome_parts).strip()
    if not pront and not nome:
        return None

    return {
        "prontuario": pront,
        "nome": nome,
        "leito": leito,
        "especialidade": esp,
        "data_internacao": data_int,
    }


# ---------------------------------------------------------------------------
# Salvamento
# ---------------------------------------------------------------------------
def save_results(patients: list[dict[str, str]]) -> Path:
    """Salva lista de pacientes como JSON em downloads/."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    json_path = DOWNLOADS_DIR / f"{JSON_OUTPUT_PREFIX}-{ts}.json"

    data = {
        "data": time.strftime("%Y-%m-%d"),
        "total": len(patients),
        "pacientes": patients,
    }

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def save_debug(page: Page, label: str = "altas-hoje") -> None:
    """Salva screenshot e HTML para debug."""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{label}-{ts}.png"), full_page=True)
        (DEBUG_DIR / f"{label}-{ts}.html").write_text(page.content(), encoding="utf-8")

        # Também salva conteúdo do iframe de altas
        altas_frame = page.frame(name=ALTAS_IFRAME_NAME)
        if altas_frame:
            (DEBUG_DIR / f"{label}-{ts}-iframe.html").write_text(
                altas_frame.content(), encoding="utf-8"
            )

        print(f"[i] Debug salvo em debug/{label}-{ts}.*")
    except Exception as e:
        print(f"[!] Falha ao salvar debug: {e}")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def capturar_altas_hoje(
    *,
    source_system_url: str,
    username: str,
    password: str,
    headless: bool = True,
    pdf_output_path: Path | None = None,
    salvar_json: bool = False,
) -> list[dict[str, str]]:
    """
    Automação completa: loga no sistema fonte, navega até Altas do Dia,
    clica em Visualizar Impressão, baixa o PDF e extrai a lista de pacientes.

    Args:
        source_system_url: URL do sistema fonte (ex: .env → SOURCE_SYSTEM_URL)
        username: Nome de usuário
        password: Senha
        headless: Se True, executa sem abrir janela do navegador
        pdf_output_path: Caminho para salvar o PDF (default: downloads/altas-hoje.pdf)
        salvar_json: Se True, também salva o resultado como JSON em downloads/

    Returns:
        Lista de pacientes, cada um com:
          prontuario, nome, leito, especialidade, data_internacao

    Exemplo de uso como módulo:
        from busca_altas_hoje import capturar_altas_hoje

        pacientes = capturar_altas_hoje(
            source_system_url="https://...",
            username="...",
            password="...",
            headless=True,
        )
        for p in pacientes:
            print(p["prontuario"], p["nome"])
    """

    with sync_playwright() as pw:
        browser = context = page = None

        try:
            # --- Navegador ---
            print("[i] Abrindo navegador...")
            browser = pw.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            # --- Login ---
            print(f"[i] Acessando {source_system_url}...")
            page.goto(source_system_url)

            print("[i] Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("[i] Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            # --- Navegar para Altas do Dia ---
            print("[i] Clicando no ícone Altas do Dia...")
            click_altas_icon(page)

            # Aguarda iframe
            frame_locator = wait_altas_frame_ready(page)
            page.wait_for_timeout(1500)

            # --- Visualizar Impressão ---
            print("[i] Clicando em Visualizar Impressão...")
            click_visualizar_impressao(frame_locator)
            page.wait_for_timeout(3000)

            # --- Capturar PDF ---
            print("[i] Capturando URL do PDF...")
            pdf_url = get_pdf_url_from_frame(frame_locator, page)

            if pdf_output_path is None:
                pdf_output_path = DOWNLOADS_DIR / PDF_OUTPUT_NAME
            download_pdf(context, pdf_url, pdf_output_path)

            # --- Extrair tabela ---
            print("[i] Extraindo pacientes do PDF...")
            patients = extract_patients_from_pdf(pdf_output_path)

            # --- Salvar resultados (opcional) ---
            if salvar_json and patients:
                json_path = save_results(patients)
                print(f"[i] JSON salvo em: {json_path}")

            return patients

        except Exception as e:
            print(f"\n[ERRO] {e}")
            if page is not None:
                save_debug(page)
            raise
        finally:
            if context:
                context.close()
            if browser:
                browser.close()


def _print_patients(patients: list[dict[str, str]]) -> None:
    """Exibe a lista de pacientes formatada no terminal."""
    if not patients:
        print("\n[!] Nenhum paciente encontrado.")
        return

    print(f"\n{'=' * 60}")
    print(f"Pacientes com alta hoje: {len(patients)}")
    print(f"{'=' * 60}")
    for i, p in enumerate(patients, start=1):
        print(
            f"  {i:3d}. {p.get('prontuario','?'):10s}  "
            f"{p.get('nome','?'):30s}  "
            f"{p.get('leito','?'):8s}  "
            f"{p.get('especialidade','?'):6s}  "
            f"{p.get('data_internacao','?')}"
        )
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    """Entry point CLI: lê .env e executa a captura, exibindo e salvando o resultado."""
    load_dotenv()
    args = parse_args()

    try:
        source_system_url = required_env("SOURCE_SYSTEM_URL")
        username = required_env("SOURCE_SYSTEM_USERNAME")
        password = required_env("SOURCE_SYSTEM_PASSWORD")
    except RuntimeError as e:
        print(f"[ERRO] {e}")
        print("Certifique-se de que o arquivo .env existe e contém as variáveis necessárias.")
        return

    patients = capturar_altas_hoje(
        source_system_url=source_system_url,
        username=username,
        password=password,
        headless=args.headless,
        salvar_json=True,
    )

    _print_patients(patients)


if __name__ == "__main__":
    main()
