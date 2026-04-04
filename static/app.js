document.addEventListener("DOMContentLoaded", () => {
  setupDateInputs();
  setupWorkForm();
  setupResultPage();
  setupCopySummaryButton();
});

const PHASE_CONFIG = {
  starting: { label: "Preparando", progress: 8 },
  logging_in: { label: "Autenticando no sistema fonte", progress: 15 },
  opening_internacao: { label: "Abrindo Internação Atual", progress: 24 },
  filling_patient_record: { label: "Preenchendo registro do paciente", progress: 34 },
  selecting_professional_category: { label: "Selecionando categoria profissional", progress: 42 },
  capturing_patient_summary: { label: "Capturando resumo do paciente", progress: 50 },
  opening_date_range: { label: "Abrindo consulta por intervalo", progress: 58 },
  filling_date_range: { label: "Preenchendo intervalo de datas", progress: 66 },
  requesting_report: { label: "Solicitando relatório", progress: 74 },
  downloading_pdf: { label: "Baixando PDF", progress: 82 },
  extracting_pdf_text: { label: "Extraindo texto do PDF", progress: 88 },
  processing_text: { label: "Processando e ordenando evoluções", progress: 94 },
  summarizing: { label: "Gerando resumo", progress: 98 },
  completed: { label: "Concluído", progress: 100 },
  error: { label: "Erro", progress: 100 },
};

function setupDateInputs() {
  const startDateInput = document.getElementById("start_date");
  const endDateInput = document.getElementById("end_date");
  if (!startDateInput || !endDateInput) {
    return;
  }

  const today = new Date();
  const fiveDaysAgo = new Date(today);
  fiveDaysAgo.setDate(today.getDate() - 5);

  if (!endDateInput.value) {
    endDateInput.value = formatDateForInput(today);
  }

  if (!startDateInput.value) {
    startDateInput.value = formatDateForInput(fiveDaysAgo);
  }
}

function setupWorkForm() {
  const form = document.getElementById("work-form");
  if (!form) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const patientRecordInput = document.getElementById("patient_record");
    const startDateInput = document.getElementById("start_date");
    const endDateInput = document.getElementById("end_date");
    const button = document.getElementById("submit-button");
    const alertBox = document.getElementById("form-alert");
    const patientRecord = patientRecordInput.value.trim();
    const startDate = startDateInput.value;
    const endDate = endDateInput.value;

    hideAlert(alertBox);

    if (!patientRecord) {
      showAlert(alertBox, "Informe o registro do paciente.");
      patientRecordInput.focus();
      return;
    }

    if (!startDate) {
      showAlert(alertBox, "Informe a data inicial.");
      startDateInput.focus();
      return;
    }

    if (!endDate) {
      showAlert(alertBox, "Informe a data final.");
      endDateInput.focus();
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
        body: JSON.stringify({
          patient_record: patientRecord,
          start_date: startDate,
          end_date: endDate,
        }),
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
    renderWorkMetadata(work);

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

function renderWorkMetadata(work) {
  const patientRecordElement = document.getElementById("meta-patient-record");
  const periodElement = document.getElementById("meta-period");
  const patientSummaryElement = document.getElementById("meta-patient-summary");

  if (patientRecordElement) {
    patientRecordElement.textContent = work.patient_record || "-";
  }

  if (periodElement) {
    periodElement.textContent = formatPeriod(work.start_date, work.end_date);
  }

  if (patientSummaryElement) {
    patientSummaryElement.textContent =
      work.patient_summary || "Aguardando captura do resumo do paciente...";
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

  statusProgress.classList.add("progress-bar-animated", "progress-bar-striped");
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

  if (work && work.patient_record) {
    renderWorkMetadata(work);
  }

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
  return PHASE_CONFIG[phase]?.label || "Processando";
}

function phaseProgress(phase) {
  return PHASE_CONFIG[phase]?.progress || 12;
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

function formatDateForInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatPeriod(startDate, endDate) {
  const start = formatIsoDateForDisplay(startDate);
  const end = formatIsoDateForDisplay(endDate);

  if (!start && !end) {
    return "-";
  }

  if (start && end) {
    return `${start} a ${end}`;
  }

  return start || end;
}

function formatIsoDateForDisplay(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value || "";
  }

  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}
