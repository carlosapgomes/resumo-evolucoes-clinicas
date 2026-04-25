#!/usr/bin/env python3
"""
Automação para extrair a lista de pacientes do Censo Diário filtrada por setor.

Fluxo:
  1. Autentica no sistema fonte
  2. Fecha diálogos iniciais
  3. Clica no ícone "Censo Diário de Pacientes"
  4. Aguarda o iframe do Censo carregar
  5. Seleciona o setor/unidade funcional configurado
  6. Clica em "Pesquisar"
  7. Aguarda a tabela de resultados (PrimeFaces datatable)
  8. Garante 100 registros por página (já é o default)
  9. Extrai de cada paciente: Qrt/Leito, Prontuário, Nome, Esp
 10. Imprime no console e salva JSON + CSV em downloads/
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Frame, FrameLocator, Locator, Page, sync_playwright

from source_system import (
    DEFAULT_TIMEOUT_MS,
    aguardar_pagina_estavel,
    fechar_dialogos_iniciais,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DOWNLOADS_DIR = Path("downloads")
DEBUG_DIR = Path("debug")
CENSO_IFRAME_SELECTOR = "#i_frame_censo_diário_dos_pacientes"
CENSO_FRAME_NAME = "i_frame_censo_diário_dos_pacientes"

# ---------------------------------------------------------------------------
# Helpers de ambiente e argumentos
# ---------------------------------------------------------------------------


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai lista de pacientes do Censo Diário para um setor específico."
    )
    parser.add_argument("--headless", action="store_true", default=True, help="Executa em modo headless")
    parser.add_argument(
        "--setor",
        default=None,
        help=(
            "Nome do setor/unidade funcional (ex.: 'S - INTERMEDIÁRIO ALA B - HGRS'). "
            "Se omitido, usa a variável de ambiente SETOR_CENSO."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers de navegação (padrão censo_unidades.py)
# ---------------------------------------------------------------------------


def wait_for_visible(locator: Locator, timeout: int = 30000) -> bool:
    """Aguarda elemento ficar visível."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_locator(locator: Locator, description: str, timeout: int = 30000) -> bool:
    """Clica em um locator com fallback progressivo."""
    if not wait_for_visible(locator, timeout=timeout):
        print(f"Aviso: elemento não visível para clique: {description}")
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
    return page.frame(name=CENSO_FRAME_NAME)


def get_censo_frame_locator(page: Page) -> FrameLocator:
    """Retorna o frame locator do Censo usando o ID exato do iframe."""
    return page.frame_locator(CENSO_IFRAME_SELECTOR)


def wait_for_censo_content(page: Page, timeout: int = 60000) -> FrameLocator:
    """Aguarda o conteúdo do iframe do Censo carregar."""
    print("Aguardando conteúdo do Censo carregar...")
    frame_locator = get_censo_frame_locator(page)
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


# ---------------------------------------------------------------------------
# Etapas específicas do fluxo de pacientes por setor
# ---------------------------------------------------------------------------


def select_sector(frame_locator: FrameLocator, sector_name: str, page: Page) -> None:
    """
    Abre o dropdown de unidades funcionais e seleciona o setor pelo nome.
    """
    print(f"Selecionando setor: '{sector_name}'...")

    # 1. Clica no botão de sugestão (dropdown) do campo unidadeFuncional
    suggestion_button = frame_locator.locator(
        '[id="unidadeFuncional:unidadeFuncional:suggestion_button"]'
    )
    if not wait_for_visible(suggestion_button, timeout=10000):
        suggestion_button = frame_locator.locator("button[id*='suggestion_button']")

    if not click_locator(suggestion_button, "botão de sugestão da unidade funcional"):
        raise RuntimeError("Não foi possível clicar no botão de sugestão da unidade funcional.")

    # Aguarda o dropdown renderizar
    page.wait_for_timeout(1500)

    # 2. Localiza e clica na célula com o nome do setor dentro do frame
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        raise RuntimeError("Frame do Censo não encontrado para seleção de setor.")

    # Tenta correspondência exata primeiro, depois parcial
    sector_cell = censo_frame.get_by_role("cell", name=sector_name)
    if sector_cell.count() == 0:
        # Fallback: busca parcial
        print(f"  Setor exato não encontrado, tentando busca parcial...")
        sector_cell = censo_frame.locator(f"[role='cell']", has_text=sector_name)

    if not click_locator(sector_cell, f"setor '{sector_name}'"):
        raise RuntimeError(f"Setor '{sector_name}' não encontrado no dropdown de unidades funcionais.")

    page.wait_for_timeout(500)
    print(f"OK: setor '{sector_name}' selecionado.")


def click_search_button(frame_locator: FrameLocator) -> None:
    """Clica no botão Pesquisar dentro do iframe do Censo."""
    search_button = frame_locator.get_by_role("button", name="Pesquisar")
    if not click_locator(search_button, "botão Pesquisar"):
        raise RuntimeError("Não foi possível clicar no botão Pesquisar.")
    print("OK: pesquisa disparada.")


def wait_for_results_table(frame_locator: FrameLocator, timeout: int = 30000) -> bool:
    """
    Aguarda a tabela de resultados carregar via AJAX.
    Retorna True se a tabela apareceu, False se não há resultados.
    """
    print("Aguardando tabela de resultados...")
    try:
        # Aguarda o container da datatable ficar visível (usa attribute selector para evitar escape de :)
        frame_locator.locator('[id="tabelaCensoDiario:resultList"]').wait_for(
            state="visible", timeout=timeout
        )
        print("OK: tabela de resultados carregou.")
        return True
    except Exception:
        print("Aviso: timeout aguardando tabela de resultados.")
        return False


def wait_for_table_rows_ready(page: Page, min_wait_ms: int = 2000) -> int:
    """
    Aguarda as linhas da tabela terminarem de carregar (AJAX do PrimeFaces).
    Polling: espera o número de <tr> estabilizar por 2 ciclos consecutivos.
    Retorna o número final de linhas.
    """
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        return 0

    prev_count = -1
    stable_cycles = 0
    max_cycles = 20

    for _ in range(max_cycles):
        try:
            rows = censo_frame.locator('[id="tabelaCensoDiario:resultList_data"] tr')
            count = rows.count()

            if count == prev_count and count > 0:
                stable_cycles += 1
                if stable_cycles >= 2:
                    # Mostra o texto do paginador
                    paginator = censo_frame.locator(".ui-paginator-current")
                    if paginator.count() > 0:
                        try:
                            print(f"  Paginador: {paginator.inner_text()}")
                        except Exception:
                            pass
                    return count
            else:
                stable_cycles = 0

            prev_count = count
            page.wait_for_timeout(500)
        except Exception:
            page.wait_for_timeout(500)

    page.wait_for_timeout(min_wait_ms)
    try:
        rows = censo_frame.locator('[id="tabelaCensoDiario:resultList_data"] tr')
        return rows.count()
    except Exception:
        return 0


def select_100_rows_per_page(page: Page) -> None:
    """
    Lê o paginador ("Exibindo: X - Y de Z registros") e só ajusta para 100
    se o total Z > Y (nem todos os registros estão visíveis).
    """
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        return

    try:
        pag_text = censo_frame.locator(".ui-paginator-current").inner_text()
        print(f"  Paginador: {pag_text}")
    except Exception:
        print("  Aviso: não foi possível ler o paginador.")
        return

    import re
    match = re.search(r'(\d+)\s*-\s*(\d+)\s+de\s+(\d+)', pag_text)
    if not match:
        print(f"  Aviso: formato do paginador não reconhecido: {pag_text}")
        return

    first_shown = int(match.group(1))
    last_shown = int(match.group(2))
    total = int(match.group(3))

    if last_shown >= total:
        print(f"  OK: todos os {total} registros já estão visíveis.")
        return

    # Nem todos visíveis — tenta expandir para 100
    print(f"  Exibindo {first_shown}-{last_shown} de {total}. Ajustando para 100...")
    try:
        result = censo_frame.evaluate("""
            () => {
                const sel = document.querySelector('select.ui-paginator-rpp-options');
                if (!sel) return 'select-not-found';
                if (sel.value === '100') return 'already-100';
                sel.value = '100';
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                return 'changed-to-100';
            }
        """)
        if result == "already-100":
            print("  Paginação já estava em 100.")
        elif result == "changed-to-100":
            print("  Paginação ajustada para 100, aguardando reload...")
            wait_for_table_rows_ready(page, min_wait_ms=1000)
        else:
            print(f"  Aviso: resultado inesperado: {result}")
    except Exception as e:
        print(f"  Aviso: erro ao ajustar paginação: {e}")


# ---------------------------------------------------------------------------
# Extração de dados da tabela
# ---------------------------------------------------------------------------


def extract_patients(page: Page) -> list[dict[str, str]]:
    """
    Extrai todos os pacientes da tabela de resultados do Censo.
    Extrai via JavaScript no contexto do iframe para maior performance.
    """
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        raise RuntimeError("Frame do Censo não encontrado para extração de pacientes.")

    patients: list[dict[str, str]] = []

    # Abordagem primária: JS para performance
    try:
        js_result = censo_frame.evaluate("""
            () => {
                const tbody = document.querySelector('[id="tabelaCensoDiario:resultList_data"]');
                if (!tbody) return [];
                const rows = tbody.querySelectorAll('tr');
                const patients = [];

                const getSpan = (row, suffix) => {
                    const span = row.querySelector('span[id$="' + suffix + '"]');
                    return (span?.textContent || '').replace(/\\u00a0/g, '').trim();
                };

                for (const row of rows) {
                    // Qrt/Leito pode vir como outQrtoLto (preenchido) ou outQrtoLtoSpacer (vazio)
                    let qrt_leito = getSpan(row, 'outQrtoLto');
                    if (!qrt_leito) {
                        qrt_leito = getSpan(row, 'outQrtoLtoSpacer');
                    }

                    patients.push({
                        qrt_leito: qrt_leito,
                        prontuario: getSpan(row, 'outProntuario'),
                        nome: getSpan(row, 'outNomeSituacao'),
                        esp: getSpan(row, 'outSiglaEsp'),
                    });
                }

                return patients;
            }
        """)

        if isinstance(js_result, list):
            patients = js_result
            print(f"Pacientes extraídos (JS): {len(patients)}")
    except Exception as e:
        print(f"Aviso: extração JS falhou: {e}.")

    # Fallback: usa Playwright locators linha por linha
    if not patients:
        rows = censo_frame.locator('[id="tabelaCensoDiario:resultList_data"] tr')
        row_count = rows.count()
        print(f"Extraindo via fallback: {row_count} linha(s)...")

        for i in range(row_count):
            row = rows.nth(i)
            # Qrt/Leito pode vir como outQrtoLto (preenchido) ou outQrtoLtoSpacer (vazio)
            qrt_leito = row.locator("span[id$='outQrtoLto']").inner_text().replace("\u00a0", "").strip()
            if not qrt_leito:
                qrt_leito = row.locator("span[id$='outQrtoLtoSpacer']").inner_text().replace("\u00a0", "").strip()
            patients.append({
                "qrt_leito": qrt_leito,
                "prontuario": row.locator("span[id$='outProntuario']").inner_text().strip(),
                "nome": row.locator("span[id$='outNomeSituacao']").inner_text().strip(),
                "esp": row.locator("span[id$='outSiglaEsp']").inner_text().strip(),
            })

    return patients


# ---------------------------------------------------------------------------
# Saída: console + arquivos
# ---------------------------------------------------------------------------


def print_results(patients: list[dict[str, str]], sector_name: str) -> None:
    """Imprime a lista de pacientes formatada no console."""
    header = f"PACIENTES DO SETOR: {sector_name}"
    print(f"\n{'='*80}")
    print(f"  {header}")
    print(f"  Total: {len(patients)} paciente(s)")
    print(f"{'='*80}")

    if not patients:
        print("  Nenhum paciente encontrado neste setor.")
        print(f"{'='*80}\n")
        return

    print(f"  {'Qrt/Leito':<14} {'Prontuário':<12} {'Nome':<35} {'Esp':<6}")
    print(f"  {'-'*14} {'-'*12} {'-'*35} {'-'*6}")
    for p in patients:
        print(f"  {p['qrt_leito']:<14} {p['prontuario']:<12} {p['nome']:<35} {p['esp']:<6}")
    print(f"{'='*80}\n")


def save_results(patients: list[dict[str, str]], sector_name: str) -> None:
    """Salva os resultados em JSON e CSV na pasta downloads/."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # Nome seguro para arquivo (substitui caracteres problemáticos)
    safe_sector = sector_name.replace("/", "-").replace(" ", "_")[:40]

    # JSON
    json_path = DOWNLOADS_DIR / f"censo-pacientes-{safe_sector}-{timestamp}.json"
    json_path.write_text(
        json.dumps(patients, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"JSON salvo em: {json_path}")

    # CSV
    csv_path = DOWNLOADS_DIR / f"censo-pacientes-{safe_sector}-{timestamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["qrt_leito", "prontuario", "nome", "esp"])
        writer.writeheader()
        writer.writerows(patients)
    print(f"CSV salvo em: {csv_path}")


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------


def _save_debug(page: Page) -> None:
    """Salva screenshot e HTML para debug em caso de erro."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    DEBUG_DIR.mkdir(exist_ok=True)

    try:
        page.screenshot(path=str(DEBUG_DIR / f"censo-pacientes-{timestamp}.png"), full_page=True)
        (DEBUG_DIR / f"censo-pacientes-{timestamp}.html").write_text(
            page.content(), encoding="utf-8"
        )

        # Também salva o conteúdo do iframe do Censo
        censo_frame = get_censo_frame(page)
        if censo_frame:
            (DEBUG_DIR / f"censo-pacientes-{timestamp}-iframe.html").write_text(
                censo_frame.content(), encoding="utf-8"
            )
        print(f"Debug salvo em: debug/censo-pacientes-{timestamp}.*")
    except Exception as e:
        print(f"Aviso: falha ao salvar debug: {e}")


# ---------------------------------------------------------------------------
# Orquestração principal
# ---------------------------------------------------------------------------


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    sector_name: str,
    headless: bool,
) -> None:
    """Executa a automação completa de extração de pacientes por setor."""

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            # --- Setup do navegador ---
            print("Abrindo navegador...")
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--ignore-certificate-errors"],
            )
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)

            # --- Login ---
            print(f"Acessando {source_system_url}...")
            page.goto(source_system_url, timeout=DEFAULT_TIMEOUT_MS)

            print("Autenticando...")
            page.get_by_role("textbox", name="Nome de usuário").fill(username)
            page.get_by_role("textbox", name="Senha").fill(password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)

            print("Fechando diálogos iniciais...")
            fechar_dialogos_iniciais(page)

            # --- Navegação para o Censo ---
            print("Clicando no botão do Censo Diário de Pacientes...")
            locator = page.locator('[id="_icon_img_20323"]')
            if not click_locator(locator, "botão Censo Diário de Pacientes"):
                raise RuntimeError("Não foi possível clicar no botão do Censo.")

            # --- Aguarda iframe ---
            frame_locator = wait_for_censo_content(page)

            # --- Seleciona setor ---
            select_sector(frame_locator, sector_name, page)

            # --- Pesquisa ---
            click_search_button(frame_locator)

            # --- Aguarda tabela ---
            if not wait_for_results_table(frame_locator):
                print("Nenhum resultado retornado para este setor.")
                patients: list[dict[str, str]] = []
            else:
                # Aguarda todas as linhas carregarem via AJAX
                row_count = wait_for_table_rows_ready(page, min_wait_ms=2000)
                print(f"  Linhas detectadas: {row_count}")
                # Garante 100 rows por página (se houver troca, aguarda estabilizar)
                select_100_rows_per_page(page)
                wait_for_table_rows_ready(page, min_wait_ms=1000)

                # --- Extrai pacientes ---
                patients = extract_patients(page)

            # --- Saída ---
            print_results(patients, sector_name)
            save_results(patients, sector_name)

            print("Concluído com sucesso.")

        except Exception as e:
            print(f"Erro durante a execução: {e}")
            if page is not None:
                _save_debug(page)
            raise
        finally:
            if context:
                context.close()
            if browser:
                browser.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    load_dotenv()
    args = parse_args()

    source_system_url = required_env("SOURCE_SYSTEM_URL")
    username = required_env("SOURCE_SYSTEM_USERNAME")
    password = required_env("SOURCE_SYSTEM_PASSWORD")

    # Setor: CLI tem precedência sobre env var
    sector_name = args.setor or os.getenv("SETOR_CENSO")
    if not sector_name:
        raise RuntimeError(
            "Setor não informado. Use --setor 'Nome do Setor' ou defina a variável SETOR_CENSO."
        )

    run(
        source_system_url=source_system_url,
        username=username,
        password=password,
        sector_name=sector_name,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
