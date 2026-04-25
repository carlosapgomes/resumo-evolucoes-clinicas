#!/usr/bin/env python3
"""
Automação para extrair pacientes de TODOS os setores do Censo Diário.

Fluxo:
  1. Autentica no sistema fonte
  2. Fecha diálogos iniciais
  3. Clica no ícone "Censo Diário de Pacientes"
  4. Aguarda o iframe do Censo carregar
  5. Abre o dropdown de unidades funcionais e extrai a lista completa de setores
  6. Para cada setor:
     a. Limpa a seleção anterior (botão sgClear)
     b. Seleciona o setor no dropdown
     c. Clica em "Pesquisar"
     d. Aguarda a tabela de resultados
     e. Extrai todos os pacientes (Qrt/Leito, Prontuário, Nome, Esp)
     f. Registra progresso [i/total]
  7. Salva JSON consolidado (array de setores com pacientes) e CSV único
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
        description="Extrai pacientes de todos os setores do Censo Diário."
    )
    parser.add_argument("--headless", action="store_true", help="Executa em modo headless")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers de navegação (compartilhados com busca_pacientes_censo.py)
# ---------------------------------------------------------------------------


def wait_for_visible(locator: Locator, timeout: int = 30000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def click_locator(locator: Locator, description: str, timeout: int = 30000) -> bool:
    if not wait_for_visible(locator, timeout=timeout):
        print(f"  Aviso: elemento não visível para clique: {description}")
        return False

    target = locator.first
    for method_name, extra_args in [
        ("click", {}),
        ("click", {"force": True}),
    ]:
        try:
            method = getattr(target, method_name)
            method(timeout=timeout, **extra_args)
            return True
        except Exception as e:
            print(f"  Aviso: {method_name} falhou em {description}: {e}")

    try:
        target.evaluate("(el) => el.click()")
        return True
    except Exception as e:
        print(f"  Falha final em {description}: {e}")
        return False


def get_censo_frame(page: Page) -> Frame | None:
    return page.frame(name=CENSO_FRAME_NAME)


def get_censo_frame_locator(page: Page) -> FrameLocator:
    return page.frame_locator(CENSO_IFRAME_SELECTOR)


def wait_for_censo_content(page: Page, timeout: int = 60000) -> FrameLocator:
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
# Extração da lista de setores (adaptado de censo_unidades.py)
# ---------------------------------------------------------------------------


def extract_all_sectors(page: Page) -> list[str]:
    """
    Abre o dropdown de unidades funcionais e extrai todos os setores.
    Retorna a lista de nomes dos setores (ex.: 'S - INTERMEDIÁRIO ALA B - HGRS').
    """
    print("\nExtraindo lista de setores do dropdown...")

    frame_locator = get_censo_frame_locator(page)

    # 1. Clica no botão de sugestão
    suggestion_button = frame_locator.locator(
        '[id="unidadeFuncional:unidadeFuncional:suggestion_button"]'
    )
    if not wait_for_visible(suggestion_button, timeout=10000):
        suggestion_button = frame_locator.locator("button[id*='suggestion_button']")

    if not click_locator(suggestion_button, "botão de sugestão (extração de setores)"):
        raise RuntimeError("Não foi possível abrir o dropdown de setores.")

    # 2. Aguarda o painel de sugestões do autocomplete aparecer
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        raise RuntimeError("Frame do Censo não encontrado para extração de setores.")

    print("  Aguardando dropdown carregar...")

    # Espera explícita pelo painel do autocomplete (dentro ou fora do iframe)
    dropdown_panel = None
    for selector in [
        "div.ui-autocomplete-panel",
        "div.ui-autocomplete",
        "table[role='grid']",
        "[role='cell']",
    ]:
        try:
            # Tenta no iframe
            el = censo_frame.locator(selector)
            el.first.wait_for(state="attached", timeout=5000)
            dropdown_panel = "iframe"
            print(f"  Dropdown detectado no iframe: {selector}")
            break
        except Exception:
            pass
        try:
            # Tenta no documento principal
            el = page.locator(selector)
            el.first.wait_for(state="attached", timeout=5000)
            dropdown_panel = "main"
            print(f"  Dropdown detectado no documento principal: {selector}")
            break
        except Exception:
            pass

    if dropdown_panel is None:
        print("  Aviso: painel do dropdown não detectado, tentando extração mesmo assim...")

    # Aguarda mais um pouco para o conteúdo assíncrono
    page.wait_for_timeout(2000)

    # 3. Extrai setores
    sectors: list[str] = []
    max_wait = 15  # segundos
    start = time.time()

    while time.time() - start < max_wait and not sectors:
        # Estratégia JS: extrai células que contenham ' - ' (padrão dos setores)
        try:
            js_sectors = censo_frame.evaluate("""
                () => {
                    const options = [];
                    const seen = new Set();
                    // Busca em toda a árvore do iframe
                    const allCells = document.querySelectorAll('[role="cell"]');
                    for (const cell of allCells) {
                        const text = (cell.textContent || '').trim();
                        if (text && text.length > 5 && text.includes(' - ')) {
                            if (!seen.has(text)) {
                                seen.add(text);
                                options.push(text);
                            }
                        }
                    }
                    // Tenta também em elementos de lista/tabela do autocomplete
                    if (!options.length) {
                        const altSelectors = [
                            '.ui-autocomplete-items tr td',
                            '.ui-autocomplete-list-item',
                            'tr[role="row"] td[role="gridcell"]',
                            '.ui-widget-content tr td',
                        ];
                        for (const sel of altSelectors) {
                            const items = document.querySelectorAll(sel);
                            for (const item of items) {
                                const text = (item.textContent || '').trim();
                                if (text && text.length > 5 && text.includes(' - ') && !seen.has(text)) {
                                    seen.add(text);
                                    options.push(text);
                                }
                            }
                            if (options.length) break;
                        }
                    }
                    return options;
                }
            """)

            if isinstance(js_sectors, list) and js_sectors:
                sectors = js_sectors
                print(f"  Setores encontrados (JS, iframe): {len(sectors)}")
                break
        except Exception as e:
            print(f"  Tentativa JS (iframe): {e}")

        # Estratégia JS no documento principal
        if not sectors:
            try:
                js_sectors_main = page.evaluate("""
                    () => {
                        const options = [];
                        const seen = new Set();
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
                        return options;
                    }
                """)
                if isinstance(js_sectors_main, list) and js_sectors_main:
                    sectors = js_sectors_main
                    print(f"  Setores encontrados (JS, main doc): {len(sectors)}")
                    break
            except Exception as e:
                pass

        # Estratégia Playwright: espera células aparecerem no iframe
        if not sectors:
            try:
                cells = censo_frame.locator("[role='cell']")
                cells.first.wait_for(state="attached", timeout=3000)
                count = cells.count()
                if count > 0:
                    seen: set[str] = set()
                    for i in range(count):
                        text = (cells.nth(i).inner_text() or "").strip()
                        if text and len(text) > 5 and " - " in text and text not in seen:
                            seen.add(text)
                            sectors.append(text)
                    if sectors:
                        print(f"  Setores encontrados (locators): {len(sectors)}")
                        break
            except Exception:
                pass

        # Se ainda não encontrou, aguarda mais um pouco
        if not sectors:
            page.wait_for_timeout(1000)

    if not sectors:
        print("  AVISO: nenhum setor encontrado após timeout.")

    # 3. Fecha o dropdown clicando fora
    try:
        censo_frame.locator("body").click(position={"x": 0, "y": 0})
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        page.locator("body").click(position={"x": 0, "y": 0})
        page.wait_for_timeout(300)
    except Exception:
        pass

    return sectors


# ---------------------------------------------------------------------------
# Selecionar setor no dropdown
# ---------------------------------------------------------------------------


def select_sector(frame_locator: FrameLocator, sector_name: str, page: Page) -> bool:
    """
    Abre o dropdown de unidades funcionais e seleciona o setor pelo nome.
    Retorna True se selecionou, False se não encontrou.
    """
    # 1. Clica no botão de sugestão
    suggestion_button = frame_locator.locator(
        '[id="unidadeFuncional:unidadeFuncional:suggestion_button"]'
    )
    if not wait_for_visible(suggestion_button, timeout=10000):
        suggestion_button = frame_locator.locator("button[id*='suggestion_button']")

    if not click_locator(suggestion_button, "botão de sugestão"):
        print(f"  ERRO: não foi possível abrir dropdown para setor '{sector_name}'")
        return False

    page.wait_for_timeout(1200)

    # 2. Localiza e clica na célula com o nome do setor
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        print(f"  ERRO: frame do Censo não encontrado")
        return False

    sector_cell = censo_frame.get_by_role("cell", name=sector_name)
    if sector_cell.count() == 0:
        sector_cell = censo_frame.locator("[role='cell']", has_text=sector_name)

    if not click_locator(sector_cell, f"setor '{sector_name}'", timeout=5000):
        print(f"  ERRO: setor '{sector_name}' não encontrado no dropdown")
        return False

    page.wait_for_timeout(500)
    return True


# ---------------------------------------------------------------------------
# Pesquisar e aguardar tabela
# ---------------------------------------------------------------------------


def click_search_button(frame_locator: FrameLocator) -> bool:
    search_button = frame_locator.get_by_role("button", name="Pesquisar")
    return click_locator(search_button, "botão Pesquisar")


def wait_for_results_table(frame_locator: FrameLocator, timeout: int = 30000) -> bool:
    try:
        # Aguarda o container da datatable ficar visível
        frame_locator.locator('[id="tabelaCensoDiario:resultList"]').wait_for(
            state="visible", timeout=timeout
        )
        return True
    except Exception:
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

    stable_count = 0
    prev_count = -1
    stable_cycles = 0
    max_cycles = 20

    for _ in range(max_cycles):
        try:
            # Também verifica se o paginator já apareceu (indica que a tabela carregou)
            paginator = censo_frame.locator(".ui-paginator-current")
            paginator_visible = paginator.count() > 0

            rows = censo_frame.locator('[id="tabelaCensoDiario:resultList_data"] tr')
            count = rows.count()

            if count == prev_count and count > 0:
                stable_cycles += 1
                if stable_cycles >= 2:
                    if paginator_visible:
                        try:
                            pag_text = paginator.inner_text()
                            print(f"  Paginador: {pag_text}")
                        except Exception:
                            pass
                    return count
            else:
                stable_cycles = 0

            prev_count = count
            page.wait_for_timeout(500)
        except Exception:
            page.wait_for_timeout(500)

    # Fallback: retorna o que tiver após min_wait_ms
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
# Extração de pacientes de uma tabela (copiado de busca_pacientes_censo.py)
# ---------------------------------------------------------------------------


def extract_patients(page: Page) -> list[dict[str, str]]:
    censo_frame = get_censo_frame(page)
    if censo_frame is None:
        return []

    patients: list[dict[str, str]] = []

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
    except Exception:
        pass

    # Fallback Playwright
    if not patients:
        rows = censo_frame.locator('[id="tabelaCensoDiario:resultList_data"] tr')
        row_count = rows.count()
        for i in range(row_count):
            row = rows.nth(i)
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
# Saída consolidada
# ---------------------------------------------------------------------------


def save_consolidated_results(results: list[dict]) -> None:
    """Salva JSON consolidado e CSV único com coluna de setor."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # --- JSON consolidado ---
    json_path = DOWNLOADS_DIR / f"censo-todos-pacientes-{timestamp}.json"
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nJSON consolidado salvo em: {json_path}")

    # --- CSV único (achatado) ---
    csv_path = DOWNLOADS_DIR / f"censo-todos-pacientes-{timestamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["setor", "qrt_leito", "prontuario", "nome", "esp"])
        writer.writeheader()
        for entry in results:
            setor = entry.get("setor", "")
            for p in entry.get("pacientes", []):
                writer.writerow({
                    "setor": setor,
                    "qrt_leito": p.get("qrt_leito", ""),
                    "prontuario": p.get("prontuario", ""),
                    "nome": p.get("nome", ""),
                    "esp": p.get("esp", ""),
                })
    print(f"CSV consolidado salvo em: {csv_path}")


def print_summary(results: list[dict]) -> None:
    """Imprime resumo final da extração."""
    total_sectors = len(results)
    ok_sectors = sum(1 for r in results if "erro" not in r)
    error_sectors = sum(1 for r in results if "erro" in r)
    total_patients = sum(len(r.get("pacientes", [])) for r in results)

    print(f"\n{'='*70}")
    print(f"  RESUMO FINAL")
    print(f"  Setores processados: {total_sectors}")
    print(f"  Setores OK:          {ok_sectors}")
    print(f"  Setores com erro:    {error_sectors}")
    print(f"  Total de pacientes:  {total_patients}")
    print(f"{'='*70}")

    if error_sectors > 0:
        print(f"\n  Setores com erro:")
        for r in results:
            if "erro" in r:
                print(f"    - {r['setor']}: {r['erro']}")


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------


def _save_debug(page: Page) -> None:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    DEBUG_DIR.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"todos-{timestamp}.png"), full_page=True)
        (DEBUG_DIR / f"todos-{timestamp}.html").write_text(page.content(), encoding="utf-8")
        censo_frame = get_censo_frame(page)
        if censo_frame:
            (DEBUG_DIR / f"todos-{timestamp}-iframe.html").write_text(censo_frame.content(), encoding="utf-8")
        print(f"Debug salvo em: debug/todos-{timestamp}.*")
    except Exception as e:
        print(f"Aviso: falha ao salvar debug: {e}")


# ---------------------------------------------------------------------------
# Loop principal de clear + select
# ---------------------------------------------------------------------------


def clear_and_select(
    frame_locator: FrameLocator,
    page: Page,
    sector_name: str,
) -> bool:
    """
    Limpa o setor atual e seleciona o próximo.
    Combina clear + open dropdown + click cell.
    Retorna True se selecionou com sucesso.
    """
    # 1. Clica no botão de limpar (sgClear)
    clear_button = frame_locator.locator(
        '[id="unidadeFuncional:unidadeFuncional:sgClear"]'
    )
    if clear_button.count() > 0 and wait_for_visible(clear_button, timeout=3000):
        click_locator(clear_button, "botão limpar setor (sgClear)", timeout=5000)
        page.wait_for_timeout(800)
    else:
        # Fallback: tenta por seletor parcial ou DOM
        censo_frame = get_censo_frame(page)
        if censo_frame:
            try:
                # Tenta forçar clear via PrimeFaces JavaScript
                censo_frame.evaluate("""
                    () => {
                        const btn = document.querySelector('[id$="sgClear"]');
                        if (btn) btn.click();
                    }
                """)
                page.wait_for_timeout(800)
            except Exception:
                pass

    # 2. Seleciona o novo setor
    return select_sector(frame_locator, sector_name, page)


# ---------------------------------------------------------------------------
# Orquestração principal
# ---------------------------------------------------------------------------


def run(
    *,
    source_system_url: str,
    username: str,
    password: str,
    headless: bool,
) -> None:
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

            # --- Extrai lista de setores ---
            sectors = extract_all_sectors(page)
            if not sectors:
                raise RuntimeError("Nenhum setor encontrado no dropdown.")

            print(f"\nTotal de setores a processar: {len(sectors)}")

            # --- Processa cada setor ---
            results: list[dict] = []
            total = len(sectors)

            for idx, sector_name in enumerate(sectors, start=1):
                print(f"\n{'─'*60}")
                print(f"[{idx}/{total}] Processando: {sector_name}")

                # --- Seleciona o setor (com ou sem clear) ---
                if idx == 1:
                    # Primeiro setor: não precisa limpar, só selecionar
                    if not select_sector(frame_locator, sector_name, page):
                        results.append({
                            "setor": sector_name,
                            "erro": f"Setor não encontrado no dropdown",
                            "pacientes": [],
                        })
                        print(f"  ERRO: setor não encontrado")
                        continue
                else:
                    # Demais setores: limpa o anterior, depois seleciona
                    if not clear_and_select(frame_locator, page, sector_name):
                        results.append({
                            "setor": sector_name,
                            "erro": "Falha ao limpar/selecionar setor",
                            "pacientes": [],
                        })
                        print(f"  ERRO: falha ao limpar/selecionar")
                        continue

                # --- Pesquisa e extrai (comum a todos os setores) ---
                if not click_search_button(frame_locator):
                    results.append({
                        "setor": sector_name,
                        "erro": "Falha ao clicar em Pesquisar",
                        "pacientes": [],
                    })
                    print(f"  ERRO: falha no Pesquisar")
                    continue

                if wait_for_results_table(frame_locator):
                    # Aguarda todas as linhas da datatable carregarem via AJAX
                    row_count = wait_for_table_rows_ready(page, min_wait_ms=2000)
                    if row_count > 0:
                        print(f"  Linhas detectadas: {row_count}")
                    # Garante 100 por página (se houver troca, aguarda estabilizar de novo)
                    select_100_rows_per_page(page)
                    wait_for_table_rows_ready(page, min_wait_ms=1000)
                    patients = extract_patients(page)
                    result = {"setor": sector_name, "pacientes": patients}
                else:
                    result = {"setor": sector_name, "pacientes": []}

                print(f"  OK: {len(result['pacientes'])} paciente(s)")
                results.append(result)

            # --- Saída consolidada ---
            save_consolidated_results(results)
            print_summary(results)

        except Exception as e:
            print(f"\nErro fatal durante a execução: {e}")
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

    run(
        source_system_url=source_system_url,
        username=username,
        password=password,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
