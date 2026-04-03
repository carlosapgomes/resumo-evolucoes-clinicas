document.addEventListener("DOMContentLoaded", () => {
  setupWorkForm();
  setupResultPage();
  setupCopySummaryButton();
});

function setupWorkForm() {
  const form = document.getElementById("work-form");
  if (!form) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const input = document.getElementById("patient_record");
    const button = document.getElementById("submit-button");
    const alertBox = document.getElementById("form-alert");
    const patientRecord = input.value.trim();

    hideAlert(alertBox);

    if (!patientRecord) {
      showAlert(alertBox, "Informe o registro do paciente.");
      input.focus();
      return;
    }

    button.disabled = true;
    button.textContent = "Iniciando...";

    try {
      const response = await fetch("/api/work", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ patient_record: patientRecord }),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload?.error?.message || "Não foi possível iniciar o processamento.");
      }

      window.location.href = payload.result_url;
    } catch (error) {
      showAlert(alertBox, error.message || "Não foi possível iniciar o processamento.");
      button.disabled = false;
      button.textContent = "Pesquisar e resumir";
    }
  });
}

function setupResultPage() {
  const resultPage = document.getElementById("result-page");
  if (!resultPage) {
    return;
  }

  const workId = resultPage.dataset.workId;
  if (!workId) {
    return;
  }

  let timer = null;

  const tick = async () => {
    const shouldStop = await pollWorkStatus(workId);
    if (shouldStop && timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  };

  tick();
  timer = window.setInterval(tick, 2000);
}

async function pollWorkStatus(workId) {
  try {
    const response = await fetch(`/api/work/${workId}/status`, {
      headers: {
        Accept: "application/json",
      },
    });

    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload?.error?.message || "Falha ao consultar o status do processamento.");
    }

    const work = payload.work;

    if (work.status === "running") {
      renderRunning(work);
      return false;
    }

    if (work.status === "completed") {
      renderCompleted(work);
      return true;
    }

    renderError(work);
    return true;
  } catch (error) {
    renderError({
      message: "Falha ao consultar o status do processamento.",
      error: error.message || "Erro inesperado.",
    });
    return true;
  }
}

function renderRunning(work) {
  const spinner = document.getElementById("status-spinner");
  const statusCard = document.getElementById("status-card");
  const errorAlert = document.getElementById("error-alert");
  const resultContent = document.getElementById("result-content");
  const statusMessage = document.getElementById("status-message");
  const statusPhase = document.getElementById("status-phase");
  const statusProgress = document.getElementById("status-progress");
  const copyButton = document.getElementById("copy-summary-button");

  statusCard.classList.remove("d-none");
  spinner.classList.remove("d-none");
  hideAlert(errorAlert);
  resultContent.classList.add("d-none");

  if (copyButton) {
    copyButton.disabled = true;
    copyButton.textContent = "Copiar";
    copyButton.dataset.summary = "";
  }

  statusMessage.textContent = work.message || "Processando...";
  statusPhase.textContent = phaseLabel(work.phase);
  statusProgress.style.width = `${phaseProgress(work.phase)}%`;
}

function renderCompleted(work) {
  const spinner = document.getElementById("status-spinner");
  const statusCard = document.getElementById("status-card");
  const errorAlert = document.getElementById("error-alert");
  const resultContent = document.getElementById("result-content");
  const statusMessage = document.getElementById("status-message");
  const statusPhase = document.getElementById("status-phase");
  const statusProgress = document.getElementById("status-progress");
  const rawText = document.getElementById("raw-text");
  const summaryText = document.getElementById("summary-text");
  const copyButton = document.getElementById("copy-summary-button");
  const summary = work.summary || "";

  hideAlert(errorAlert);
  statusCard.classList.remove("d-none");
  spinner.classList.add("d-none");
  statusMessage.textContent = work.message || "Resumo concluído.";
  statusPhase.textContent = "Concluído";
  statusProgress.classList.remove("progress-bar-animated", "progress-bar-striped");
  statusProgress.style.width = "100%";

  rawText.textContent = work.raw_text || "";
  renderMarkdown(summaryText, summary);

  if (copyButton) {
    copyButton.disabled = !summary;
    copyButton.textContent = "Copiar";
    copyButton.dataset.summary = summary;
  }

  resultContent.classList.remove("d-none");
}

function renderError(work) {
  const spinner = document.getElementById("status-spinner");
  const statusCard = document.getElementById("status-card");
  const resultContent = document.getElementById("result-content");
  const errorAlert = document.getElementById("error-alert");
  const copyButton = document.getElementById("copy-summary-button");

  statusCard.classList.add("d-none");
  resultContent.classList.add("d-none");
  spinner.classList.add("d-none");

  if (copyButton) {
    copyButton.disabled = true;
    copyButton.textContent = "Copiar";
    copyButton.dataset.summary = "";
  }

  const message = [work.message, work.error].filter(Boolean).join(" ");
  showAlert(errorAlert, message || "Falha ao processar a solicitação.");
}

function phaseLabel(phase) {
  switch (phase) {
    case "starting":
      return "Preparando";
    case "capturing":
      return "Capturando evoluções";
    case "summarizing":
      return "Gerando resumo";
    case "completed":
      return "Concluído";
    case "error":
      return "Erro";
    default:
      return "Processando";
  }
}

function phaseProgress(phase) {
  switch (phase) {
    case "starting":
      return 15;
    case "capturing":
      return 45;
    case "summarizing":
      return 80;
    case "completed":
      return 100;
    case "error":
      return 100;
    default:
      return 20;
  }
}

function setupCopySummaryButton() {
  const copyButton = document.getElementById("copy-summary-button");
  if (!copyButton) {
    return;
  }

  copyButton.addEventListener("click", async () => {
    const summary = copyButton.dataset.summary || "";
    if (!summary) {
      return;
    }

    try {
      await copyTextToClipboard(summary);
      copyButton.textContent = "Copiado!";
      window.setTimeout(() => {
        copyButton.textContent = "Copiar";
      }, 1800);
    } catch (error) {
      copyButton.textContent = "Falha ao copiar";
      window.setTimeout(() => {
        copyButton.textContent = "Copiar";
      }, 2200);
    }
  });
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.top = "-9999px";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);

  if (!copied) {
    throw new Error("Não foi possível copiar o texto.");
  }
}

function renderMarkdown(element, markdown) {
  const source = (markdown || "").trim();
  if (!source) {
    element.textContent = "";
    return;
  }

  if (window.marked && window.DOMPurify) {
    const html = window.marked.parse(source, {
      breaks: false,
      gfm: true,
    });
    element.innerHTML = window.DOMPurify.sanitize(html);
    return;
  }

  element.textContent = source;
}

function showAlert(element, message) {
  element.textContent = message;
  element.classList.remove("d-none");
}

function hideAlert(element) {
  element.textContent = "";
  element.classList.add("d-none");
}
