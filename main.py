import os
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright, expect

load_dotenv()

DEFAULT_TIMEOUT_MS = 180000
UI_TIMEOUT_MS = 60000


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def fechar_dialogos_iniciais(page) -> None:
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

    page.wait_for_load_state("domcontentloaded")

    fechar_dialogos_iniciais(page)

    botao_internacao_atual = page.locator("#_icon_img_404335")
    expect(botao_internacao_atual).to_be_visible(timeout=UI_TIMEOUT_MS)
    botao_internacao_atual.click()

    frame_internacao = page.frame_locator('iframe[name="i_frame_internação_atual"]')

    campo_registro = frame_internacao.locator('[id="prontuario:prontuario:inputId"]')
    expect(campo_registro).to_be_visible(timeout=UI_TIMEOUT_MS)
    campo_registro.click()
    campo_registro.fill(patient_rec_number)

    seletor_categoria = frame_internacao.locator('[id="categoriaProfissional:categoriaProfissional:inputId"] span')
    expect(seletor_categoria).to_be_visible(timeout=UI_TIMEOUT_MS)
    seletor_categoria.click()
    frame_internacao.get_by_role("option", name="Médico", exact=True).click()

    texto_paciente = frame_internacao.locator("#j_idt175")
    expect(texto_paciente).to_be_visible(timeout=UI_TIMEOUT_MS)
    conteudo_texto = (texto_paciente.text_content() or "").strip()
    print(f"Conteúdo de #j_idt175: {conteudo_texto}")

    # ---------------------
    context.close()
    browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
