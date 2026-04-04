from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import shutil

import pymupdf
from playwright.sync_api import BrowserContext, Locator, Page, expect, sync_playwright

from config import Settings, load_settings
from processa_evolucoes_txt import process_file

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000
NETWORKIDLE_TIMEOUT_MS = 30000
RETRY_INTERVAL_MS = 2000
RETRY_ATTEMPTS = 3

ProgressCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class CaptureResult:
    patient_summary: str | None
    raw_text: str


def aguardar_pagina_estavel(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)

    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
    except Exception:
        print("Aviso: networkidle não foi atingido dentro do tempo limite; seguindo com a automação.")


def esperar_locator_com_retry(
    page: Page,
    descricao: str,
    locator_factory: Callable[[], Locator],
    *,
    timeout: int = UI_TIMEOUT_MS,
    tentativas: int = RETRY_ATTEMPTS,
) -> Locator:
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        locator = locator_factory()

        try:
            expect(locator).to_be_visible(timeout=timeout)
            return locator
        except Exception as erro:
            ultimo_erro = erro
            if tentativa == tentativas:
                break

            print(
                f"Tentativa {tentativa}/{tentativas} falhou ao localizar {descricao}. Tentando novamente..."
            )
            page.wait_for_timeout(RETRY_INTERVAL_MS)
            aguardar_pagina_estavel(page)

    raise ultimo_erro


def fechar_dialogos_iniciais(page: Page) -> None:
    botao_fechar = page.get_by_role("button", name="Fechar")

    try:
        expect(botao_fechar).to_be_visible(timeout=5000)
        botao_fechar.click()
        page.wait_for_timeout(1000)
    except Exception:
        pass

    pendencias_modal = page.locator("#central_pendencias")

    try:
        expect(pendencias_modal).to_be_visible(timeout=5000)
        page.wait_for_timeout(1500)
        page.locator("body").press("Escape")
        page.wait_for_timeout(1000)
    except Exception:
        pass

    page.evaluate(
        """() => {
        const seletores = [
            '#central_pendencias',
            '#msgDocsDialog',
            '.ui-dialog[aria-hidden="false"]',
            '.ui-widget-overlay'
        ];

        for (const seletor of seletores) {
            document.querySelectorAll(seletor).forEach((elemento) => {
                elemento.setAttribute('aria-hidden', 'true');
                elemento.style.display = 'none';
                elemento.style.visibility = 'hidden';
                elemento.style.opacity = '0';
                elemento.style.pointerEvents = 'none';
            });
        }
    }"""
    )

    try:
        expect(page.locator("#central_pendencias")).to_be_hidden(timeout=5000)
    except Exception:
        pass

    try:
        expect(page.locator("#msgDocsDialog")).to_be_hidden(timeout=5000)
    except Exception:
        pass


def capturar_resumo_paciente(frame, page: Page) -> tuple[str, str | None]:
    container_paciente = esperar_locator_com_retry(
        page,
        "resumo do paciente na tela",
        lambda: frame.locator("#valCodPaciente").locator("xpath=.."),
    )

    resumo_paciente = " ".join((container_paciente.inner_text() or "").split())
    if not resumo_paciente:
        raise RuntimeError("O resumo do paciente foi localizado, mas o texto veio vazio.")

    nome_paciente = resumo_paciente.split(",", 1)[0].strip() if "," in resumo_paciente else None
    return resumo_paciente, nome_paciente


def obter_pdf_url_do_object(frame, page: Page, page_url: str) -> str:
    pdf_object = esperar_locator_com_retry(
        page,
        "visualizador PDF embutido",
        lambda: frame.locator('object[type="application/pdf"]'),
        timeout=120000,
    )

    ultimo_data = None

    for tentativa in range(1, RETRY_ATTEMPTS + 1):
        pdf_url = pdf_object.get_attribute("data")
        if pdf_url:
            absolute_pdf_url = urljoin(page_url, pdf_url)
            print(f"URL do PDF identificada no <object>: {absolute_pdf_url}")
            return absolute_pdf_url

        ultimo_data = pdf_url
        if tentativa < RETRY_ATTEMPTS:
            print(
                f"Tentativa {tentativa}/{RETRY_ATTEMPTS} falhou ao ler o atributo data do PDF. Tentando novamente..."
            )
            page.wait_for_timeout(RETRY_INTERVAL_MS)

    raise RuntimeError(
        "O elemento <object> do PDF apareceu, mas o atributo 'data' não ficou disponível. "
        f"Último valor observado: {ultimo_data!r}"
    )


def baixar_pdf_autenticado(
    context: BrowserContext,
    pdf_url: str,
    output_path: Path,
    debug_html_path: Path,
) -> None:
    response = context.request.get(pdf_url, timeout=120000)
    if not response.ok:
        raise RuntimeError(
            f"Falha ao baixar o PDF pela URL do <object>. HTTP {response.status}."
        )

    content_type = (response.headers.get("content-type") or "").lower()
    content_disposition = response.headers.get("content-disposition") or ""
    body = response.body()

    print(f"Content-Type retornado: {content_type}")
    print(f"Content-Disposition retornado: {content_disposition}")
    print(f"Tamanho baixado: {len(body)} bytes")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not body.startswith(b"%PDF-"):
        debug_html_path.parent.mkdir(parents=True, exist_ok=True)
        debug_html_path.write_bytes(body)
        raise RuntimeError(
            "A URL do relatório foi acessada, mas o conteúdo retornado não parece ser um PDF válido. "
            f"Corpo salvo para inspeção em: {debug_html_path}"
        )

    output_path.write_bytes(body)


def extrair_texto_do_pdf(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise RuntimeError(f"Arquivo PDF não encontrado para extração: {pdf_path}")

    paginas: list[str] = []

    with pymupdf.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            texto_pagina = (page.get_text("text") or "").strip()
            paginas.append(f"===== PÁGINA {page_number} =====\n{texto_pagina}")

    texto_final = "\n\n".join(paginas).strip()
    if not texto_final:
        raise RuntimeError("A extração do PDF terminou, mas nenhum texto foi encontrado.")

    return texto_final


def salvar_texto_extraido(texto: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(texto, encoding="utf-8")


def _copiar_fixture_pdf(fixture_path: Path, output_path: Path) -> None:
    if not fixture_path.exists():
        raise RuntimeError(f"Arquivo de fixture não encontrado: {fixture_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fixture_path.resolve() == output_path.resolve():
        return

    shutil.copyfile(fixture_path, output_path)


def _processar_pdf_baixado(settings: Settings, report: ProgressCallback) -> str:
    report("extracting_pdf_text", "Extraindo texto do PDF...")
    texto_extraido = extrair_texto_do_pdf(settings.pdf_output_path)
    salvar_texto_extraido(texto_extraido, settings.txt_output_path)

    report("processing_text", "Processando e ordenando evoluções...")
    process_file(
        settings.txt_output_path,
        settings.processed_txt_output_path,
        settings.sorted_txt_output_path,
    )

    texto_ordenado = settings.sorted_txt_output_path.read_text(encoding="utf-8").strip()
    if not texto_ordenado:
        raise RuntimeError("O processamento do PDF terminou, mas o texto ordenado ficou vazio.")

    return texto_ordenado


def capture_evolution_data(
    patient_record: str,
    interval_start_datetime: str,
    interval_end_datetime: str,
    progress_callback: ProgressCallback | None = None,
) -> CaptureResult:
    settings = load_settings()

    def report(phase: str, message: str) -> None:
        print(message)
        if progress_callback:
            progress_callback(phase, message)

    if settings.evolution_fixture_path:
        return capture_evolution_data_from_fixture(
            patient_record,
            interval_start_datetime,
            interval_end_datetime,
            progress_callback=progress_callback,
        )

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            report("starting", "Preparando consulta no sistema fonte...")
            browser = playwright.chromium.launch(
                headless=False,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            report("logging_in", "Abrindo a tela inicial do sistema fonte...")
            page.goto(settings.source_system_url, timeout=DEFAULT_TIMEOUT_MS)

            report("logging_in", "Autenticando no sistema fonte...")
            page.get_by_role("textbox", name="Nome de usuário").fill(settings.source_system_username)
            page.get_by_role("textbox", name="Senha").fill(settings.source_system_password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            report("opening_internacao", "Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            report("opening_internacao", "Abrindo o módulo Internação Atual...")
            botao_internacao_atual = esperar_locator_com_retry(
                page,
                "botão de Internação Atual",
                lambda: page.locator("#_icon_img_404335"),
            )
            botao_internacao_atual.click()
            aguardar_pagina_estavel(page)

            frame_internacao = page.frame_locator('iframe[name="i_frame_internação_atual"]')

            report("filling_patient_record", "Preenchendo o registro do paciente...")
            campo_registro = esperar_locator_com_retry(
                page,
                "campo de registro do paciente",
                lambda: frame_internacao.locator('[id="prontuario:prontuario:inputId"]'),
            )
            campo_registro.click()
            campo_registro.fill(patient_record)

            report(
                "selecting_professional_category",
                "Selecionando a categoria profissional Médico...",
            )
            seletor_categoria = esperar_locator_com_retry(
                page,
                "seletor de categoria profissional",
                lambda: frame_internacao.locator(
                    '[id="categoriaProfissional:categoriaProfissional:inputId"] span'
                ),
            )
            seletor_categoria.click()

            opcao_medico = esperar_locator_com_retry(
                page,
                "opção Médico",
                lambda: frame_internacao.get_by_role("option", name="Médico", exact=True),
            )
            opcao_medico.click()
            page.wait_for_timeout(1000)

            report("capturing_patient_summary", "Capturando resumo do paciente na tela...")
            resumo_paciente, nome_paciente = capturar_resumo_paciente(frame_internacao, page)
            print(f"Resumo do paciente: {resumo_paciente}")
            if nome_paciente:
                print(f"Nome do paciente: {nome_paciente}")

            report("opening_date_range", "Abrindo consulta por intervalo de datas...")
            botao_visualizar_tudo = esperar_locator_com_retry(
                page,
                "botão Visualizar Tudo",
                lambda: frame_internacao.get_by_role("button", name="Visualizar Tudo"),
            )
            botao_visualizar_tudo.click()
            page.wait_for_timeout(1000)

            report("filling_date_range", "Preenchendo o intervalo de datas...")
            campo_data_inicial = esperar_locator_com_retry(
                page,
                "campo de data inicial",
                lambda: frame_internacao.locator(
                    '[id="dataInicialPeriodoEvolucao:dataInicialPeriodoEvolucao:inputId_input"]'
                ),
            )
            campo_data_inicial.click()
            campo_data_inicial.fill(interval_start_datetime)

            campo_data_final = esperar_locator_com_retry(
                page,
                "campo de data final",
                lambda: frame_internacao.locator(
                    '[id="dataFinalPeriodoEvolucao:dataFinalPeriodoEvolucao:inputId_input"]'
                ),
            )
            campo_data_final.click()
            campo_data_final.fill(interval_end_datetime)

            report("requesting_report", "Solicitando a visualização do relatório...")
            botao_visualizar = esperar_locator_com_retry(
                page,
                "botão Visualizar do relatório",
                lambda: frame_internacao.get_by_role("button", name="Visualizar", exact=True),
            )
            botao_visualizar.click()
            page.wait_for_timeout(1500)

            report("downloading_pdf", "Baixando o relatório PDF...")
            pdf_url = obter_pdf_url_do_object(frame_internacao, page, page.url)
            baixar_pdf_autenticado(
                context,
                pdf_url,
                settings.pdf_output_path,
                settings.pdf_debug_html_path,
            )

            texto_ordenado = _processar_pdf_baixado(settings, report)
            return CaptureResult(patient_summary=resumo_paciente, raw_text=texto_ordenado)
        except Exception:
            if page is not None:
                salvar_debug(page)
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def capture_evolution_data_from_fixture(
    patient_record: str,
    interval_start_datetime: str,
    interval_end_datetime: str,
    progress_callback: ProgressCallback | None = None,
) -> CaptureResult:
    settings = load_settings()
    fixture = settings.evolution_fixture_path
    if fixture is None:
        raise RuntimeError("Modo fixture não configurado.")

    def report(phase: str, message: str) -> None:
        print(message)
        if progress_callback:
            progress_callback(phase, message)

    report("starting", "Usando PDF fixture local em vez de acessar o sistema fonte...")
    report(
        "downloading_pdf",
        f"Copiando PDF fixture {fixture.name} para {settings.pdf_output_path}...",
    )
    _copiar_fixture_pdf(fixture, settings.pdf_output_path)

    texto_ordenado = _processar_pdf_baixado(settings, report)
    patient_summary = (
        f"Modo fixture PDF · registro {patient_record} · intervalo {interval_start_datetime} até {interval_end_datetime}"
    )
    return CaptureResult(patient_summary=patient_summary, raw_text=texto_ordenado)


def capture_evolution_text(
    patient_record: str,
    interval_start_datetime: str,
    interval_end_datetime: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    result = capture_evolution_data(
        patient_record,
        interval_start_datetime,
        interval_end_datetime,
        progress_callback=progress_callback,
    )
    return result.raw_text


def salvar_debug(page: Page) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    screenshot_path = debug_dir / f"erro-{timestamp}.png"
    html_path = debug_dir / f"erro-{timestamp}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as erro:
        print(f"Aviso: falha ao salvar screenshot de debug: {erro}")

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as erro:
        print(f"Aviso: falha ao salvar HTML de debug: {erro}")
