import os
from typing import Callable
from dotenv import load_dotenv
from playwright.sync_api import Locator, Page, Playwright, sync_playwright, expect

load_dotenv()

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000
NETWORKIDLE_TIMEOUT_MS = 30000
RETRY_INTERVAL_MS = 3000
RETRY_ATTEMPTS = 3


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


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

    page.evaluate("""() => {
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
    }""")

    expect(page.locator("#central_pendencias")).to_be_hidden(timeout=UI_TIMEOUT_MS)
    expect(page.locator("#msgDocsDialog")).to_be_hidden(timeout=UI_TIMEOUT_MS)



def run(playwright: Playwright) -> None:
    aghuse_url = required_env("AGHUSE_URL")
    user_name = required_env("USER_NAME")
    user_pw = required_env("USER_PW")
    patient_rec_number = required_env("PATIENT_REC_NUMBER")

    browser = playwright.chromium.launch(
        headless=False,
        args=['--ignore-certificate-errors']
    )
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
    page.goto(aghuse_url, timeout=DEFAULT_TIMEOUT_MS)
    page.get_by_role("textbox", name="Nome de usuário").fill(user_name)
    page.get_by_role("textbox", name="Senha").fill(user_pw)
    page.get_by_role("button", name="Entrar").click()

    aguardar_pagina_estavel(page)

    fechar_dialogos_iniciais(page)

    botao_internacao_atual = esperar_locator_com_retry(
        page,
        "botão de Internação Atual",
        lambda: page.locator("#_icon_img_404335"),
    )
    botao_internacao_atual.click()
    aguardar_pagina_estavel(page)

    frame_internacao = page.frame_locator('iframe[name="i_frame_internação_atual"]')

    campo_registro = esperar_locator_com_retry(
        page,
        "campo de registro no iframe de internação",
        lambda: frame_internacao.locator('[id="prontuario:prontuario:inputId"]'),
    )
    campo_registro.click()
    campo_registro.fill(patient_rec_number)

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

    texto_paciente = esperar_locator_com_retry(
        page,
        "texto do paciente (#j_idt175) no iframe de internação",
        lambda: frame_internacao.locator("#j_idt175"),
    )
    conteudo_texto = (texto_paciente.text_content() or "").strip()
    print(f"Conteúdo de #j_idt175: {conteudo_texto}")

    # ---------------------
    context.close()
    browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
