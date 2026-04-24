#!/usr/bin/env python3
"""
Automação para capturar a lista de unidades funcionais do Censo Diário de Pacientes.

Fluxo:
  1. Abre navegador e autentica.
  2. Fecha diálogos iniciais.
  3. Clica no ícone "Censo Diário de Pacientes".
  4. Aguarda a tab do Censo carregar.
  5. Clica no botão de sugestão (dropdown) do campo unidadeFuncional.
  6. Extrai TODAS as opções do dropdown e imprime no console.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, FrameLocator, Locator, Page, Frame, sync_playwright

from source_system import (
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    fechar_dialogos_iniciais,
)


DEFAULT_SOURCE_SYSTEM_URL = "https://localhost"


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Navega até o Censo Diário de Pacientes, abre o dropdown de unidades funcionais "
            "e imprime a lista de opções no console."
        )
    )
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def wait_for_visible(locator: Locator, timeout: int = 30000) -> bool:
    """Aguarda elemento ficar visível."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_locator(locator: Locator, description: str, timeout: int = 30000) -> bool:
    """Clica em um locator com fallback."""
    if not wait_for_visible(locator, timeout=timeout):
        return False

    target = locator.first

    for method_name, extra_args in [
        ("click", {}),
        ("click", {"force": True}),
    ]:
        try:
            method = getattr(target, method_name)
            method(timeout=timeout, **extra_args)
            print(f"OK: {description}")
            return True
        except Exception as e:
            print(f"Aviso: {method_name} falhou em {description}: {e}")

    # Último recurso: DOM click
    try:
        target.evaluate("(el) => el.click()")
        print(f"OK: {description} (DOM click)")
        return True
    except Exception as e:
        print(f"Falha final em {description}: {e}")
        return False


def get_censo_frame(page: Page) -> Frame | None:
    """Retorna o frame do Censo."""
    return page.frame(name="i_frame_censo_diário_dos_pacientes")


def get_censo_frame_locator(page: Page) -> FrameLocator:
    """Retorna o frame locator do Censo usando o ID exato do iframe."""
    return page.frame_locator("#i_frame_censo_diário_dos_pacientes")


def wait_for_censo_content(page: Page, timeout: int = 60000) -> FrameLocator:
    """Aguarda o conteúdo do iframe do Censo carregar."""
    print("Aguardando conteúdo do Censo carregar...")

    frame_locator = get_censo_frame_locator(page)

    # Espera que um elemento visível apareça dentro do iframe
    start = time.time()
    while time.time() - start < timeout / 1000:
        try:
            frame_locator.locator("body").wait_for(state="attached", timeout=2000)
            print("OK: conteúdo do Censo carregou.")
            return frame_locator
        except Exception:
            pass

        time.sleep(0.5)

    raise RuntimeError("Timeout aguardando conteúdo do Censo carregar.")


def click_suggestion_button(frame_locator: FrameLocator, page: Page) -> None:
    """Clica no botão de sugestão do campo unidadeFuncional."""
    # Usa content_frame para clicar no botão
    locator = frame_locator.locator("[id=\"unidadeFuncional:unidadeFuncional:suggestion_button\"]")

    if not wait_for_visible(locator, timeout=10000):
        print("Aviso: botão não visível diretamente, tentando force click...")
        locator = frame_locator.locator("button[id*='suggestion_button']")

    if not click_locator(locator, "botão de sugestão da unidade funcional"):
        raise RuntimeError("Não foi possível clicar no botão de sugestão.")

    page.wait_for_timeout(1000)


def extract_all_options_from_dropdown(page: Page) -> list[str]:
    """Extrai todas as opções visíveis no dropdown de unidades funcionais."""
    print("Extraindo opções do dropdown...")

    options: list[str] = []

    # Primeiro obtém o frame do Censo
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        print("Aviso: não foi possível obter o frame do Censo")
        return []

    # Estratégia 1: cells de tabela (identificado via codegen)
    cells = censo_frame.locator("[role='cell']")
    count = cells.count()
    print(f"  Células encontradas (role=cell): {count}")

    if count > 0:
        for cell in cells.all():
            text = (cell.inner_text() or "").strip()
            # Filtra apenas textos que parecem nomes de unidades funcionais
            if text and len(text) > 5 and " - " in text:
                options.append(text)

    # Estratégia 2: via JavaScript no contexto do iframe
    if not options:
        print("  Tentando extração via JavaScript...")
        try:
            js_options = censo_frame.evaluate("""
                () => {
                    const options = [];
                    const seen = new Set();

                    // Procura todas as células da tabela do dropdown
                    const cells = document.querySelectorAll('[role="cell"]');
                    for (const cell of cells) {
                        const text = (cell.textContent || '').trim();
                        if (text && text.length > 5 && text.includes(' - ')) {
                            if (!seen.has(text)) {
                                seen.add(text);
                                options.push(text);
                            }
                        }
                    }

                    // Tenta other seletores
                    if (!options.length) {
                        const lists = document.querySelectorAll(
                            '.ui-autocomplete-list li, ' +
                            '.ui-selectlistbox-item, ' +
                            'table td, ' +
                            '.ui-widget-content li'
                        );
                        for (const item of lists) {
                            const text = (item.textContent || '').trim();
                            if (text && text.length > 5 && text.includes(' - ')) {
                                if (!seen.has(text)) {
                                    seen.add(text);
                                    options.push(text);
                                }
                            }
                        }
                    }

                    return options;
                }
            """)
            if js_options and isinstance(js_options, list):
                print(f"  JS encontrou: {len(js_options)} opções")
                options.extend(js_options)
        except Exception as e:
            print(f"  Aviso: JS falhou: {e}")

    # Remove duplicatas mantendo ordem
    seen = set()
    unique_options = []
    for opt in options:
        if opt not in seen:
            seen.add(opt)
            unique_options.append(opt)

    return unique_options


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    headless: bool,
) -> None:
    """Executa a automação completa de captura de unidades funcionais."""

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
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            print(f"Acessando {source_system_url}...")
            page.goto(source_system_url, timeout=DEFAULT_TIMEOUT_MS)

            print("Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            print("Clicando no botão do Censo Diário de Pacientes...")
            locator = page.locator("[id=\"_icon_img_20323\"]")
            if not click_locator(locator, "botão Census Diário de Pacientes"):
                raise RuntimeError("Não foi possível clicar no botão do Censo.")

            print("Aguardando iframe do Censo...")
            frame_locator = wait_for_censo_content(page)

            print("Clicando no botão de sugestão...")
            click_suggestion_button(frame_locator, page)

            print("Aguardando dropdown aparecer...")
            page.wait_for_timeout(2000)

            print("Extraindo opções...")
            options = extract_all_options_from_dropdown(page)

            if options:
                print(f"\n{'='*60}")
                print(f"UNIDADES FUNCIONAIS ENCONTRADAS: {len(options)}")
                print(f"{'='*60}")
                for i, opt in enumerate(options, start=1):
                    print(f"  {i:3d}. {opt}")
                print(f"{'='*60}\n")
            else:
                print("Nenhuma opção encontrada. Salvando debug...")
                _save_debug(page)

        except Exception as e:
            print(f"Erro durante a execução: {e}")
            _save_debug(page)
            raise
        finally:
            if context:
                context.close()
            if browser:
                browser.close()


def _save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(debug_dir / f"censo-{timestamp}.png"), full_page=True)
        (debug_dir / f"censo-{timestamp}.html").write_text(page.content(), encoding="utf-8")

        # Também salva o conteúdo do iframe do Censo
        censo_frame = get_censo_frame(page)
        if censo_frame:
            (debug_dir / f"censo-{timestamp}-iframe.html").write_text(
                censo_frame.content(), encoding="utf-8"
            )
            print(f"Debug salvo em: debug/censo-{timestamp}.* (inclui iframe)")

    except Exception:
        pass


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
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
