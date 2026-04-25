import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.goto("https://10.252.17.132/aghu/pages/casca/casca.xhtml")
    page.locator("#j_idt34").click()
    page.get_by_role("textbox", name="Nome de usuário").fill("16390588852")
    page.get_by_role("textbox", name="Senha").click()
    page.get_by_role("textbox", name="Senha").fill("Napoli2026)")
    page.get_by_role("button", name="Entrar").click()
    page.get_by_role("button", name="Fechar").click()
    page.locator("[id=\"_icon_img_20323\"]").click()
    page.locator("iframe[name=\"i_frame_censo_diário_dos_pacientes\"]").content_frame.locator("[id=\"unidadeFuncional:unidadeFuncional:suggestion_button\"]").click()
    page.locator("iframe[name=\"i_frame_censo_diário_dos_pacientes\"]").content_frame.get_by_role("cell", name="S - INTERMEDIÁRIO ALA B - HGRS").click()
    page.locator("iframe[name=\"i_frame_censo_diário_dos_pacientes\"]").content_frame.get_by_role("button", name="Pesquisar").click()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
