from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, unquote, urljoin, urlparse
import html

from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, Locator, Page, Frame, sync_playwright

from datetime import datetime

from processa_evolucoes_txt import remove_page_artifacts
from source_system import (
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    baixar_pdf_autenticado,
    extrair_texto_do_pdf,
    fechar_dialogos_iniciais,
    obter_pdf_url_do_object,
    salvar_debug,
    salvar_texto_extraido,
)

DEFAULT_PATIENT_RECORD: Final[str] = "8920415"
DEFAULT_START_DATE: Final[str] = "05/06/2024"
DEFAULT_END_DATE: Final[str] = "01/07/2024"
DEFAULT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.pdf")
DEFAULT_DEBUG_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.debug.html")
DEFAULT_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.txt")
DEFAULT_NORMALIZED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-normalizado.txt")
DEFAULT_PROCESSED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-processado.txt")
DEFAULT_SORTED_TXT_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo-ordenado.txt")
DEFAULT_JSON_OUTPUT_PATH: Final[Path] = Path("downloads/path2-evolucoes-intervalo.json")
FRAME_NAME: Final[str] = "frame_pol"
REPORT_WAIT_TIMEOUT_MS: Final[int] = 600000
REPORT_POLL_INTERVAL_MS: Final[int] = 5000
REPORT_DOWNLOAD_TIMEOUT_MS: Final[int] = 600000
PAGE_HEADER_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'(?ms)^(===== PÁGINA \d+ =====)\nEVOLUÇÃO\n(/\s*\d+)\n(\d+)\n'
)
DATETIME_WITHOUT_SECONDS_RE: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\d{2}/\d{2}/\d{4} \d{2}:\d{2})$'
)
DATETIME_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}(?::\d{2})?$'
)
EVOLUTION_END_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r'^Elaborado\b.*\bem:?\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?$',
    re.IGNORECASE,
)
SIGNATURE_AUTHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'\bpor[:\s]+(.+?)\s*(?:,|-)?\s*(?:Crm|Coren|Crefito|Crefono|Crn\d*|Cro(?:-?[A-Z]{2})?)\b',
    re.IGNORECASE,
)
SIGNATURE_DATETIME_RE: Final[re.Pattern[str]] = re.compile(
    r'\bem:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)\s*$',
    re.IGNORECASE,
)


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Navega pelo caminho de internações, abre a evolução por intervalo, baixa o PDF bruto, "
            "extrai o texto e organiza as evoluções em arquivos TXT."
        )
    )
    parser.add_argument("--patient-record", default=DEFAULT_PATIENT_RECORD)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--internacao-index", type=int, default=0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--debug-output", type=Path, default=DEFAULT_DEBUG_PATH)
    parser.add_argument("--txt-output", type=Path, default=DEFAULT_TXT_OUTPUT_PATH)
    parser.add_argument("--normalized-txt-output", type=Path, default=DEFAULT_NORMALIZED_TXT_OUTPUT_PATH)
    parser.add_argument("--processed-output", type=Path, default=DEFAULT_PROCESSED_TXT_OUTPUT_PATH)
    parser.add_argument("--sorted-output", type=Path, default=DEFAULT_SORTED_TXT_OUTPUT_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT_PATH)
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def wait_visible(locator: Locator, timeout: int = 5000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_if_visible(locator: Locator, description: str, timeout: int = 5000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        return False

    locator.first.click()
    print(f"OK: {description}")
    return True


def click_with_fallback(locator: Locator, description: str, timeout: int = 5000) -> bool:
    if not wait_visible(locator, timeout=timeout):
        return False

    target = locator.first

    try:
        target.click(timeout=timeout)
        print(f"OK: {description}")
        return True
    except Exception as click_error:
        print(f"Aviso: clique padrão falhou em {description}: {click_error}")

    try:
        target.click(timeout=timeout, force=True)
        print(f"OK: {description} (force=True)")
        return True
    except Exception as force_error:
        print(f"Aviso: clique forçado falhou em {description}: {force_error}")

    try:
        target.evaluate("(element) => element.click()")
        print(f"OK: {description} (DOM click)")
        return True
    except Exception as eval_error:
        print(f"Aviso: DOM click falhou em {description}: {eval_error}")

    return False


def normalize_patient_record(value: str) -> str:
    digits_only = re.sub(r"\D", "", value)
    return digits_only or value.strip()


def open_pol_menu(page: Page) -> bool:
    locator = page.locator("#polMenu")
    if not wait_visible(locator, timeout=5000):
        return False

    try:
        locator.first.evaluate("(element) => element.click()")
        print("OK: botão #polMenu (DOM click)")
        return True
    except Exception as error:
        print(f"Aviso: DOM click falhou em #polMenu: {error}")

    return click_with_fallback(locator, "botão #polMenu", timeout=5000)


def ensure_search_screen(page: Page) -> None:
    promptuario = page.locator("#prontuarioInput")
    if wait_visible(promptuario, timeout=5000):
        print("Tela de pesquisa já está visível.")
        return

    print("Tentando abrir a tela de pesquisa avançada...")

    strategies = [
        (open_pol_menu, "botão #polMenu"),
        (
            lambda current_page: click_with_fallback(
                current_page.get_by_role("button", name=re.compile(r"Clique aqui para acessar o", re.IGNORECASE)),
                "atalho principal do dashboard",
                timeout=5000,
            ),
            "atalho principal do dashboard",
        ),
        (
            lambda current_page: click_with_fallback(
                current_page.locator(".casca-menu-center"),
                "área central do dashboard",
                timeout=5000,
            ),
            "área central do dashboard",
        ),
        (open_pol_menu, "botão #polMenu (nova tentativa)"),
    ]

    for action, description in strategies:
        if action(page):
            page.wait_for_timeout(1800)
            if wait_visible(promptuario, timeout=6000):
                print(f"Tela de pesquisa avançada aberta com sucesso após {description}.")
                return

    raise RuntimeError("A tela de pesquisa não ficou disponível após as tentativas de navegação.")


def click_nth(locator: Locator, index: int, description: str) -> None:
    count = locator.count()
    print(f"{description}: {count} opção(ões) encontrada(s).")

    if count == 0:
        raise RuntimeError(f"Nenhuma opção encontrada para: {description}")

    if index < 0 or index >= count:
        raise RuntimeError(
            f"Índice inválido para {description}: {index}. Faixa disponível: 0 a {count - 1}."
        )

    target = locator.nth(index)
    target.wait_for(state="visible", timeout=15000)
    target.click()


def wait_for_modal_evolucao(page: Page, timeout: int = 120000) -> None:
    overlay = page.locator("#modalEvolucao_modal")

    if overlay.count() == 0:
        return

    print("Aguardando liberação do modal de evolução...")
    try:
        overlay.wait_for(state="hidden", timeout=timeout)
        print("OK: modal de evolução liberado.")
    except Exception:
        try:
            visible = overlay.is_visible()
        except Exception:
            visible = None
        print(f"Aviso: modal de evolução ainda não ficou hidden dentro do timeout. visible={visible}")


def select_order_crescente(frame, page: Page) -> None:
    result = frame.locator('#ordenacaoCrescente\\:ordenacaoCrescente\\:inputId_input').evaluate(
        """
        (select) => {
            if (!(select instanceof HTMLSelectElement)) {
                return { ok: false, reason: 'select não encontrado' };
            }

            const option = Array.from(select.options).find((item) =>
                (item.textContent || '').trim() === 'Crescente'
            );

            if (!option) {
                return {
                    ok: false,
                    reason: 'opção Crescente não encontrada',
                    options: Array.from(select.options).map((item) => ({
                        value: item.value,
                        text: (item.textContent || '').trim(),
                    })),
                };
            }

            select.value = option.value;
            select.selectedIndex = Array.from(select.options).indexOf(option);
            select.dispatchEvent(new Event('change', { bubbles: true }));

            const label = document.getElementById('ordenacaoCrescente:ordenacaoCrescente:inputId_label');
            if (label) {
                label.textContent = (option.textContent || '').trim();
            }

            return {
                ok: true,
                value: option.value,
                text: (option.textContent || '').trim(),
                label: label ? (label.textContent || '').trim() : null,
            };
        }
        """
    )

    if not result.get("ok"):
        raise RuntimeError(f"Não foi possível selecionar ordenação Crescente: {result}")

    print(f"OK: ordenação ajustada para Crescente via select oculto: {result}")
    page.wait_for_timeout(800)


def obter_pdf_url_via_viewer(page: Page) -> str | None:
    frame = page.frame(name=FRAME_NAME)
    if frame is None:
        print("Aviso: iframe frame_pol não foi encontrado para inspecionar o viewer.")
        return None

    frame_url = frame.url
    print(f"URL atual do iframe {FRAME_NAME}: {frame_url!r}")
    if not frame_url:
        return None

    parsed = urlparse(frame_url)
    if parsed.path.lower().endswith(".pdf"):
        pdf_url = urljoin(frame_url, frame_url)
        print(f"PDF identificado diretamente na URL do iframe: {pdf_url}")
        return pdf_url

    query = parse_qs(parsed.query)
    file_candidates = query.get("file", [])
    for file_candidate in file_candidates:
        decoded = unquote(file_candidate)
        absolute_pdf_url = urljoin(frame_url, decoded)
        print(f"PDF identificado pelo parâmetro file do viewer: {absolute_pdf_url}")
        return absolute_pdf_url

    iframe_src = page.locator(f'iframe[name="{FRAME_NAME}"]').get_attribute("src")
    if iframe_src:
        print(f"Atributo src do iframe {FRAME_NAME}: {iframe_src!r}")
        iframe_src_abs = urljoin(page.url, iframe_src)
        iframe_src_parsed = urlparse(iframe_src_abs)
        if iframe_src_parsed.path.lower().endswith(".pdf"):
            return iframe_src_abs

        iframe_query = parse_qs(iframe_src_parsed.query)
        file_candidates = iframe_query.get("file", [])
        for file_candidate in file_candidates:
            decoded = unquote(file_candidate)
            absolute_pdf_url = urljoin(iframe_src_abs, decoded)
            print(f"PDF identificado pelo src do iframe: {absolute_pdf_url}")
            return absolute_pdf_url

    return None


def normalize_pol_report_text(raw_text: str) -> str:
    text = PAGE_HEADER_BLOCK_RE.sub(r"\1\n\2\n\3\nEVOLUÇÃO\n", raw_text)
    text = DATETIME_WITHOUT_SECONDS_RE.sub(r"\1:00", text)
    return text


def normalize_datetime_line(value: str) -> str:
    stripped = value.strip()
    if DATETIME_LINE_RE.match(stripped) and len(stripped) == 16:
        return f"{stripped}:00"
    return stripped


def trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    return lines[start:end]


def is_evolution_end_line(value: str) -> bool:
    return bool(EVOLUTION_END_LINE_RE.match(value.strip()))


def split_evolutions_by_signature(cleaned_lines: list[str]) -> list[list[str]]:
    evolutions: list[list[str]] = []
    current: list[str] = []
    seen_first_datetime = False
    current_closed = False

    for line in cleaned_lines:
        stripped = line.strip()

        if DATETIME_LINE_RE.match(stripped):
            normalized_dt = normalize_datetime_line(stripped)

            if not seen_first_datetime:
                current = [normalized_dt]
                seen_first_datetime = True
                current_closed = False
                continue

            if current_closed:
                candidate = trim_blank_edges(current)
                if candidate:
                    evolutions.append(candidate)
                current = [normalized_dt]
                current_closed = False
                continue

            if current and current[0].strip() == normalized_dt:
                # Quebra de página de evolução longa: ignora data/hora repetida.
                continue

            # Data/hora isolada sem marcador de fechamento imediatamente anterior: ignora como ruído.
            continue

        if not seen_first_datetime:
            continue

        if current_closed:
            # Após linha final "Elaborado ... em DD/MM/YYYY HH:MM", ignora cauda até a próxima data.
            continue

        current.append(stripped)

        if stripped and is_evolution_end_line(stripped):
            current_closed = True

    candidate = trim_blank_edges(current)
    if candidate:
        evolutions.append(candidate)

    return evolutions


def extract_initial_datetime(evolution_lines: list[str]) -> datetime:
    for line in evolution_lines:
        stripped = normalize_datetime_line(line)
        if DATETIME_LINE_RE.match(stripped):
            return datetime.strptime(stripped, "%d/%m/%Y %H:%M:%S")

    raise RuntimeError("Não foi possível localizar a data/hora inicial de uma evolução.")


def build_evolutions_output(evolutions: list[list[str]]) -> str:
    blocks: list[str] = []

    for index, evolution_lines in enumerate(evolutions, start=1):
        body = "\n".join(trim_blank_edges(evolution_lines)).strip()
        blocks.append(f"===== EVOLUÇÃO {index} =====\n{body}")

    return "\n\n".join(blocks).strip() + "\n"


def find_signature_line(evolution_lines: list[str]) -> str | None:
    for line in reversed(evolution_lines):
        if is_evolution_end_line(line):
            return line.strip()
    return None


def classify_evolution_type(signature_line: str | None, content: str) -> str:
    signature_lowered = (signature_line or "").casefold()
    content_lowered = content.casefold()

    if "crm" in signature_lowered:
        return "medical"
    if "coren" in signature_lowered:
        return "nursing"
    if "crefito" in signature_lowered:
        return "phisiotherapy"
    if "crn" in signature_lowered:
        return "nutrition"
    if "crefono" in signature_lowered:
        return "speech_therapy"
    if "cro" in signature_lowered:
        return "dentistry"

    if "odontologia" in content_lowered or "odontolog" in content_lowered:
        return "dentistry"

    return "other"


def extract_created_by(signature_line: str | None) -> str:
    if not signature_line:
        return ""

    match = SIGNATURE_AUTHOR_RE.search(signature_line)
    if match:
        return match.group(1).strip(" ,-:")

    fallback = re.search(r"\bpor[:\s]+(.+?)\s+em:?\s*\d{2}/\d{2}/\d{4}", signature_line, re.IGNORECASE)
    if fallback:
        return fallback.group(1).strip(" ,-:")

    return ""


def build_evolution_content(evolution_lines: list[str], signature_line: str | None) -> str:
    lines = trim_blank_edges(evolution_lines)

    if lines and DATETIME_LINE_RE.match(normalize_datetime_line(lines[0])):
        lines = lines[1:]

    if signature_line and lines and lines[-1].strip() == signature_line:
        lines = lines[:-1]

    return "\n".join(trim_blank_edges(lines)).strip()


def extract_signature_datetime(signature_line: str | None) -> str:
    if not signature_line:
        return ""

    match = SIGNATURE_DATETIME_RE.search(signature_line)
    if not match:
        return ""

    raw_value = normalize_datetime_line(match.group(1).strip())
    try:
        return datetime.strptime(raw_value, "%d/%m/%Y %H:%M:%S").isoformat()
    except ValueError:
        return ""


def extract_confidence(evolution_type: str) -> str:
    return (
        "high"
        if evolution_type
        in {"medical", "nursing", "phisiotherapy", "nutrition", "speech_therapy", "dentistry"}
        else "low"
    )


def build_evolutions_json_payload(evolutions: list[list[str]]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []

    for source_index, evolution in enumerate(evolutions, start=1):
        signature_line = find_signature_line(evolution)
        created_at = extract_initial_datetime(evolution).isoformat()
        signed_at = extract_signature_datetime(signature_line)
        created_by = extract_created_by(signature_line)
        content = build_evolution_content(evolution, signature_line)
        evolution_type = classify_evolution_type(signature_line, content)
        confidence = extract_confidence(evolution_type)

        payload.append(
            {
                "createdAt": created_at,
                "signedAt": signed_at,
                "content": content,
                "createdBy": created_by,
                "type": evolution_type,
                "sourceIndex": source_index,
                "confidence": confidence,
                "signatureLine": signature_line or "",
            }
        )

    payload.sort(key=lambda item: (str(item["createdAt"]), int(item["sourceIndex"])))
    return payload


def salvar_evolucoes_json(payload: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extrair_e_processar_pdf_pol(
    pdf_path: Path,
    txt_output_path: Path,
    normalized_txt_output_path: Path,
    processed_txt_output_path: Path,
    sorted_txt_output_path: Path,
    json_output_path: Path,
) -> None:
    print(f"Extraindo texto do PDF salvo em: {pdf_path}")
    raw_text = extrair_texto_do_pdf(pdf_path)
    normalized_text = normalize_pol_report_text(raw_text)

    salvar_texto_extraido(raw_text, txt_output_path)
    salvar_texto_extraido(normalized_text, normalized_txt_output_path)

    cleaned_lines = remove_page_artifacts(normalized_text)
    evolutions = split_evolutions_by_signature(cleaned_lines)

    if not evolutions:
        raise RuntimeError("Nenhuma evolução foi identificada após a limpeza do texto extraído.")

    sorted_evolutions = sorted(evolutions, key=extract_initial_datetime)

    processed_text = build_evolutions_output(evolutions)
    sorted_text = build_evolutions_output(sorted_evolutions)
    json_payload = build_evolutions_json_payload(evolutions)

    salvar_texto_extraido(processed_text, processed_txt_output_path)
    salvar_texto_extraido(sorted_text, sorted_txt_output_path)
    salvar_evolucoes_json(json_payload, json_output_path)

    end_marker_lines = sum(1 for line in cleaned_lines if is_evolution_end_line(line))

    print(f"TXT bruto salvo em: {txt_output_path}")
    print(f"TXT normalizado salvo em: {normalized_txt_output_path}")
    print(f"TXT processado salvo em: {processed_txt_output_path}")
    print(f"TXT ordenado salvo em: {sorted_txt_output_path}")
    print(f"JSON de evoluções salvo em: {json_output_path}")
    print(f"Linhas após limpeza: {len(cleaned_lines)}")
    print(f"Marcadores de fim ('Elaborado ... em DD/MM/YYYY HH:MM'): {end_marker_lines}")
    print(f"Evoluções identificadas: {len(evolutions)}")


def resolve_pdf_url(page: Page) -> str:
    frame_locator = page.frame_locator(f'iframe[name="{FRAME_NAME}"]')

    try:
        return obter_pdf_url_do_object(frame_locator, page, page.url)
    except Exception as object_error:
        print(
            "Aviso: não foi possível obter a URL do PDF via <object>. "
            "Tentando descobrir a URL pelo viewer do iframe..."
        )
        print(f"Motivo original: {object_error}")

    viewer_pdf_url = obter_pdf_url_via_viewer(page)
    if viewer_pdf_url:
        return viewer_pdf_url

    raise RuntimeError(
        "O PDF não foi localizado nem via <object> nem via URL do viewer do iframe. "
        "Revise os artefatos de debug para confirmar como essa rota renderiza o relatório."
    )


def click_visualizar_relatorio(frame, page: Page) -> None:
    button = frame.locator('#bt_UltimosQuinzedias\\:button')
    button.wait_for(state='visible', timeout=30000)

    try:
        button.click(timeout=10000)
        print('OK: botão Visualizar do modal acionado com clique padrão')
    except Exception as click_error:
        print(f"Aviso: clique padrão no botão Visualizar falhou: {click_error}")
        try:
            button.click(timeout=10000, force=True)
            print('OK: botão Visualizar do modal acionado com force=True')
        except Exception as force_error:
            print(f"Aviso: clique forçado no botão Visualizar falhou: {force_error}")
            button.evaluate('(element) => element.click()')
            print('OK: botão Visualizar do modal acionado com DOM click')

    page.wait_for_timeout(1500)


def wait_for_report_page(page: Page) -> Frame:
    elapsed = 0

    while elapsed < REPORT_WAIT_TIMEOUT_MS:
        frame = page.frame(name=FRAME_NAME)
        if frame is None:
            raise RuntimeError(f'Iframe {FRAME_NAME} não encontrado durante a espera pelo relatório.')

        frame_url = frame.url or ''
        print(f'Aguardando relatório... {elapsed // 1000}s · frame={frame_url}')

        if 'relatorioAnaEvoInternacaoPdf.xhtml' in frame_url:
            print('OK: tela de relatório detectada pela URL do iframe.')
            return frame

        try:
            if frame.locator('#printLinks').count() > 0:
                print('OK: tela de relatório detectada pelo form printLinks.')
                return frame
        except Exception:
            pass

        page.wait_for_timeout(REPORT_POLL_INTERVAL_MS)
        elapsed += REPORT_POLL_INTERVAL_MS

    raise RuntimeError(
        'A tela de relatório não ficou disponível dentro do tempo limite. '
        'O sistema fonte pode ainda estar processando o relatório.'
    )


def baixar_pdf_via_formulario_relatorio(
    context: BrowserContext,
    report_frame: Frame,
    output_path: Path,
    debug_output_path: Path,
) -> bool:
    html_content = report_frame.content()

    action_match = re.search(r'<form id="printLinks"[^>]*action="([^"]+)"', html_content)
    viewstate_match = re.search(
        r'<form id="printLinks".*?name="javax.faces.ViewState"[^>]*value="([^"]+)"',
        html_content,
        re.S,
    )

    if not action_match or not viewstate_match:
        print('Aviso: form printLinks não encontrado na tela de relatório.')
        return False

    action_url = html.unescape(action_match.group(1))
    viewstate = html.unescape(viewstate_match.group(1))
    absolute_action_url = urljoin(report_frame.url, action_url)

    print(f'Tentando baixar PDF via form printLinks: {absolute_action_url}')

    response = context.request.post(
        absolute_action_url,
        form={
            'printLinks': 'printLinks',
            'downloadLinkAjax': 'downloadLinkAjax',
            'javax.faces.ViewState': viewstate,
        },
        timeout=REPORT_DOWNLOAD_TIMEOUT_MS,
    )

    if not response.ok:
        raise RuntimeError(
            f'Falha ao baixar PDF via form printLinks. HTTP {response.status}.'
        )

    body = response.body()
    content_type = (response.headers.get('content-type') or '').lower()
    content_disposition = response.headers.get('content-disposition') or ''

    print(f'Content-Type via printLinks: {content_type}')
    print(f'Content-Disposition via printLinks: {content_disposition}')
    print(f'Tamanho retornado via printLinks: {len(body)} bytes')

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if body.startswith(b'%PDF-'):
        output_path.write_bytes(body)
        print(f'PDF salvo com sucesso em: {output_path}')
        return True

    debug_output_path.parent.mkdir(parents=True, exist_ok=True)
    debug_output_path.write_bytes(body)
    print(
        'Aviso: o download via printLinks não retornou um PDF válido. '
        f'Conteúdo salvo para inspeção em: {debug_output_path}'
    )
    return False


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    patient_record: str,
    start_date: str,
    end_date: str,
    internacao_index: int,
    output_path: Path,
    debug_output_path: Path,
    txt_output_path: Path,
    normalized_txt_output_path: Path,
    processed_txt_output_path: Path,
    sorted_txt_output_path: Path,
    json_output_path: Path,
    headless: bool,
) -> None:
    patient_record = normalize_patient_record(patient_record)

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            print("Abrindo navegador...")
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            print("Acessando sistema fonte...")
            page.goto(source_system_url, timeout=DEFAULT_TIMEOUT_MS)

            print("Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            ensure_search_screen(page)

            print(f"Pesquisando prontuário {patient_record}...")
            promptuario_input = page.locator("#prontuarioInput")
            promptuario_input.wait_for(state="visible", timeout=15000)
            promptuario_input.click()
            promptuario_input.fill(patient_record)

            pesquisa_avancada = page.get_by_role("link", name="Pesquisa Avançada")
            pesquisa_avancada.wait_for(state="visible", timeout=15000)
            pesquisa_avancada.click()
            page.wait_for_timeout(1200)

            internacoes = page.get_by_text("Internações", exact=True)
            internacoes.wait_for(state="visible", timeout=15000)
            internacoes.click()
            page.wait_for_timeout(1500)

            frame_locator = page.frame_locator(f'iframe[name="{FRAME_NAME}"]')
            detalhes_internacao = frame_locator.get_by_role("link", name="Detalhes da Internação")
            detalhes_internacao.first.wait_for(state="visible", timeout=30000)
            click_nth(detalhes_internacao, internacao_index, "Detalhes da Internação")
            page.wait_for_timeout(1500)

            botao_evolucao = frame_locator.get_by_role("button", name="Evolução")
            botao_evolucao.wait_for(state="visible", timeout=30000)
            botao_evolucao.click()
            page.wait_for_timeout(1200)

            print(f"Aplicando intervalo {start_date} até {end_date}...")
            wait_for_modal_evolucao(page)

            data_inicio = frame_locator.locator('[id="dataInicio:dataInicio:inputId_input"]')
            data_inicio.wait_for(state="visible", timeout=30000)
            data_inicio.click()
            data_inicio.fill(start_date)

            data_fim = frame_locator.locator('[id="dataFim:dataFim:inputId_input"]')
            data_fim.wait_for(state="visible", timeout=30000)
            data_fim.click()
            data_fim.fill(end_date)

            wait_for_modal_evolucao(page)
            select_order_crescente(frame_locator, page)

            print("Solicitando visualização do relatório...")
            wait_for_modal_evolucao(page)
            click_visualizar_relatorio(frame_locator, page)

            report_frame = wait_for_report_page(page)

            print("Tentando localizar a URL do PDF...")
            try:
                pdf_url = resolve_pdf_url(page)
                print(f"Baixando PDF autenticado para {output_path}...")
                baixar_pdf_autenticado(context, pdf_url, output_path, debug_output_path)
                print(f"PDF salvo com sucesso em: {output_path}")
            except Exception as pdf_error:
                print(
                    'Aviso: extração direta da URL do PDF falhou nesta rota. '
                    'Tentando download pelo formulário interno do relatório...'
                )
                print(f'Motivo original: {pdf_error}')

                if not baixar_pdf_via_formulario_relatorio(
                    context,
                    report_frame,
                    output_path,
                    debug_output_path,
                ):
                    raise

            extrair_e_processar_pdf_pol(
                output_path,
                txt_output_path,
                normalized_txt_output_path,
                processed_txt_output_path,
                sorted_txt_output_path,
                json_output_path,
            )
        except Exception:
            if page is not None:
                salvar_debug(page)
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def main() -> None:
    load_dotenv()
    args = parse_args()

    source_system_url = required_env("SOURCE_SYSTEM_URL")
    username = required_env("SOURCE_SYSTEM_USERNAME")
    password = required_env("SOURCE_SYSTEM_PASSWORD")

    run(
        source_system_url=source_system_url,
        username=username,
        password=password,
        patient_record=args.patient_record,
        start_date=args.start_date,
        end_date=args.end_date,
        internacao_index=args.internacao_index,
        output_path=args.output,
        debug_output_path=args.debug_output,
        txt_output_path=args.txt_output,
        normalized_txt_output_path=args.normalized_txt_output,
        processed_txt_output_path=args.processed_output,
        sorted_txt_output_path=args.sorted_output,
        json_output_path=args.json_output,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
