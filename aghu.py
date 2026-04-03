from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time

from playwright.sync_api import Locator, Page, expect, sync_playwright

from config import load_settings

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000
NETWORKIDLE_TIMEOUT_MS = 30000
RETRY_INTERVAL_MS = 3000
RETRY_ATTEMPTS = 3

ProgressCallback = Callable[[str, str], None]


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

            print(f"Tentativa {tentativa}/{tentativas} falhou ao localizar {descricao}. Tentando novamente...")
            page.wait_for_timeout(RETRY_INTERVAL_MS)
            aguardar_pagina_estavel(page)

    raise ultimo_erro


def fechar_dialogos_iniciais(page: Page) -> None:
    pendencias_modal = page.locator("#central_pendencias")

    try:
        expect(pendencias_modal).to_be_visible(timeout=UI_TIMEOUT_MS)
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

    expect(page.locator("#central_pendencias")).to_be_hidden(timeout=UI_TIMEOUT_MS)
    expect(page.locator("#msgDocsDialog")).to_be_hidden(timeout=UI_TIMEOUT_MS)


def capture_evolution_text(
    patient_record: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    settings = load_settings()

    def report(phase: str, message: str) -> None:
        print(message)
        if progress_callback:
            progress_callback(phase, message)

    if settings.evolution_fixture_path:
        return capture_evolution_text_from_fixture(
            patient_record,
            fixture_path=settings.evolution_fixture_path,
            progress_callback=progress_callback,
        )

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            report("capturing", "Abrindo navegador para acessar o AGHUse...")
            browser = playwright.chromium.launch(
                headless=False,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            report("capturing", "Abrindo a tela inicial do AGHUse...")
            page.goto(settings.aghuse_url, timeout=DEFAULT_TIMEOUT_MS)

            report("capturing", "Autenticando no AGHUse...")
            page.get_by_role("textbox", name="Nome de usuário").fill(settings.user_name)
            page.get_by_role("textbox", name="Senha").fill(settings.user_pw)
            page.get_by_role("button", name="Entrar").click()

            aguardar_pagina_estavel(page)

            report("capturing", "Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            report("capturing", "Acessando o módulo Internação Atual...")
            botao_internacao_atual = esperar_locator_com_retry(
                page,
                "botão de Internação Atual",
                lambda: page.locator("#_icon_img_404335"),
            )
            botao_internacao_atual.click()
            aguardar_pagina_estavel(page)

            report("capturing", "Entrando na tela de Internação Atual...")
            frame_internacao = page.frame_locator('iframe[name="i_frame_internação_atual"]')

            report("capturing", "Preenchendo o registro do paciente...")
            campo_registro = esperar_locator_com_retry(
                page,
                "campo de registro no iframe de internação",
                lambda: frame_internacao.locator('[id="prontuario:prontuario:inputId"]'),
            )
            campo_registro.click()
            campo_registro.fill(patient_record)

            report("capturing", "Selecionando a categoria profissional Médico...")
            seletor_categoria = esperar_locator_com_retry(
                page,
                "seletor de categoria profissional no iframe de internação",
                lambda: frame_internacao.locator('[id="categoriaProfissional:categoriaProfissional:inputId"] span'),
            )
            seletor_categoria.click()

            opcao_medico = esperar_locator_com_retry(
                page,
                "opção Médico no seletor de categoria profissional",
                lambda: frame_internacao.get_by_role("option", name="Médico", exact=True),
            )
            opcao_medico.click()
            aguardar_pagina_estavel(page)

            report("capturing", "Capturando o texto das evoluções...")
            texto_paciente = esperar_locator_com_retry(
                page,
                "texto do paciente (#j_idt175) no iframe de internação",
                lambda: frame_internacao.locator("#j_idt175"),
            )
            conteudo_texto = (texto_paciente.text_content() or "").strip()

            if not conteudo_texto:
                raise RuntimeError("O texto capturado do paciente veio vazio.")

            return conteudo_texto
        except Exception:
            if page is not None:
                salvar_debug(page)
            raise
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def capture_evolution_text_from_fixture(
    patient_record: str,
    fixture_path: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    fixture = Path(fixture_path)
    if not fixture.exists():
        raise RuntimeError(f"Arquivo de fixture não encontrado: {fixture}")

    def report(phase: str, message: str) -> None:
        print(message)
        if progress_callback:
            progress_callback(phase, message)

    report("capturing", f"Carregando texto de teste a partir de {fixture.name}...")
    time.sleep(1)
    text = fixture.read_text(encoding="utf-8").strip()

    if not text:
        raise RuntimeError(f"O arquivo de fixture está vazio: {fixture}")

    report("capturing", f"Texto de teste carregado para o registro {patient_record}.")
    time.sleep(1)
    return text


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
