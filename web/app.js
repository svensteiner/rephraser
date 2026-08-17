import {
  MAX_INPUT_FILE_BYTES,
  MAX_INPUT_CHARACTERS,
  MODE_FAST,
  createContentlessAudit,
  decodeTextFileBytes,
  normalizeProtectedTerms,
  transformText,
} from "./editor.js";

const elements = {
  source: document.querySelector("#source-text"),
  protectedTerms: document.querySelector("#protected-terms"),
  fileInput: document.querySelector("#file-input"),
  pasteButton: document.querySelector("#paste-button"),
  transformButton: document.querySelector("#transform-button"),
  status: document.querySelector("#status-message"),
  error: document.querySelector("#error-message"),
  characterCount: document.querySelector("#character-count"),
  resultSection: document.querySelector("#result-section"),
  resultHeading: document.querySelector("#result-heading"),
  originalPreview: document.querySelector("#original-preview"),
  resultText: document.querySelector("#result-text"),
  beforeStats: document.querySelector("#before-stats"),
  afterStats: document.querySelector("#after-stats"),
  changeList: document.querySelector("#change-list"),
  characterFindings: document.querySelector("#character-findings"),
  copyButton: document.querySelector("#copy-button"),
  saveButton: document.querySelector("#save-button"),
  auditButton: document.querySelector("#audit-button"),
  clearButton: document.querySelector("#clear-button"),
};

let currentResult = null;
let isTransforming = false;

function formatNumber(value) {
  return Number(value).toLocaleString("de-DE");
}

function setStatus(message, state = "ready") {
  elements.status.textContent = message;
  elements.status.className = `status state-${state}`;
}

function showError(messages) {
  elements.error.textContent = messages.join(" ");
  elements.error.hidden = false;
  setStatus("Bitte Eingabe prüfen.", "error");
}

function clearError() {
  elements.error.textContent = "";
  elements.error.hidden = true;
}

function selectedMode() {
  return document.querySelector("input[name='mode']:checked").value;
}

function updateCharacterCount() {
  const count = Array.from(elements.source.value).length;
  elements.characterCount.textContent = `${formatNumber(count)} Zeichen`;
  if (count > MAX_INPUT_CHARACTERS) {
    elements.characterCount.textContent += " – zu lang";
  }
}

function invalidateResult() {
  if (!currentResult) {
    return;
  }
  currentResult = null;
  elements.resultSection.hidden = true;
  elements.resultText.value = "";
  elements.originalPreview.value = "";
  setStatus("Eingabe geändert. Bitte Text erneut verbessern.", "ready");
}

function statLabel(statistics) {
  return `${formatNumber(statistics.characters)} Zeichen · ${formatNumber(statistics.words)} Wörter · ${formatNumber(statistics.paragraphs)} Absätze`;
}

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function addEmptyNote(container, text) {
  const note = document.createElement(container.tagName === "UL" ? "li" : "p");
  note.className = "empty-note";
  note.textContent = text;
  container.append(note);
}

function renderChanges(result) {
  clearNode(elements.changeList);
  if (!result.modifications.length) {
    addEmptyNote(elements.changeList, "Keine bereinigungsbedürftigen Zeichen oder festen Formulierungen gefunden.");
    return;
  }
  for (const change of result.modifications) {
    const item = document.createElement("li");
    item.textContent = `${change.label} (${formatNumber(change.count)}×)`;
    elements.changeList.append(item);
  }
}

function renderFindings(result) {
  clearNode(elements.characterFindings);
  const summaries = [
    ...result.before_inspection.character_summary,
    ...result.after_inspection.character_summary.filter((after) => !result.before_inspection.character_summary.some((before) => before.code_point === after.code_point && before.kind === after.kind)),
  ];
  if (!summaries.length) {
    addEmptyNote(elements.characterFindings, "Keine ungewöhnlichen oder unsichtbaren Zeichen gefunden.");
    return;
  }
  for (const finding of summaries) {
    const item = document.createElement("article");
    item.className = "finding-item";
    const title = document.createElement("strong");
    title.textContent = `${finding.code_point} · ${finding.name}`;
    const description = document.createElement("span");
    const positions = finding.positions.length ? `Positionen (ab 1): ${finding.positions.join(", ")}${finding.positions_truncated ? " …" : ""}` : "";
    description.textContent = `${finding.kind} · ${formatNumber(finding.count)}×${positions ? ` · ${positions}` : ""}`;
    item.append(title, description);
    elements.characterFindings.append(item);
  }
}

function renderResult(result) {
  currentResult = result;
  elements.originalPreview.value = result.original;
  elements.resultText.value = result.rewritten;
  elements.beforeStats.textContent = statLabel(result.before_statistics);
  elements.afterStats.textContent = statLabel(result.after_statistics);
  renderChanges(result);
  renderFindings(result);
  elements.resultSection.hidden = false;
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  elements.resultSection.scrollIntoView({ behavior, block: "start" });
  elements.resultHeading.focus({ preventScroll: true });
  const modeDescription = result.mode === MODE_FAST ? "Schnellfassung" : "Formatbereinigung";
  setStatus(`${modeDescription} fertig. Bitte Ergebnis vor dem Verwenden lesen.`, "ready");
}

function setTransformBusy(isBusy) {
  elements.transformButton.disabled = isBusy;
  elements.transformButton.textContent = isBusy ? "Wird lokal bearbeitet …" : "Text verbessern";
}

function nextPaint() {
  return new Promise((resolve) => window.requestAnimationFrame(resolve));
}

async function runTransformation() {
  if (isTransforming) {
    return;
  }
  clearError();
  const source = elements.source.value;
  if (!source.trim()) {
    showError(["Bitte zuerst Text einfügen oder eine .txt/.md-Datei öffnen."]);
    elements.source.focus();
    return;
  }
  const protectedTerms = normalizeProtectedTerms(elements.protectedTerms.value);
  if (protectedTerms.errors.length) {
    showError(protectedTerms.errors);
    return;
  }
  isTransforming = true;
  setTransformBusy(true);
  setStatus("Bearbeite lokal in diesem Browser-Tab …", "working");
  try {
    await nextPaint();
    const result = transformText(source, { mode: selectedMode(), protectedTerms: protectedTerms.terms });
    if (result.blocked) {
      const messages = [...result.errors];
      if (result.missing_protected_terms.length) {
        messages.push(`Nicht im Ausgangstext gefunden: ${result.missing_protected_terms.join(", ")}.`);
      }
      showError(messages);
      return;
    }
    renderResult(result);
  } finally {
    isTransforming = false;
    setTransformBusy(false);
  }
}

async function pasteFromClipboard() {
  clearError();
  try {
    if (!navigator.clipboard?.readText) {
      throw new Error("Zwischenablagezugriff wird von diesem Browser nicht angeboten.");
    }
    const text = await navigator.clipboard.readText();
    elements.source.value = text;
    updateCharacterCount();
    invalidateResult();
    setStatus("Zwischenablage eingefügt. Du kannst den Text jetzt verbessern.", "ready");
    elements.source.focus();
  } catch (_error) {
    showError(["Die Zwischenablage darf hier nicht automatisch gelesen werden. Bitte den Text mit Strg+V einfügen."]);
  }
}

async function loadLocalFile() {
  clearError();
  const [file] = elements.fileInput.files;
  if (!file) {
    return;
  }
  if (!/\.(txt|md)$/iu.test(file.name)) {
    showError(["Bitte nur eine .txt- oder .md-Datei auswählen."]);
    return;
  }
  if (file.size > MAX_INPUT_FILE_BYTES) {
    showError(["Die Datei ist zu groß. Bitte maximal 2.000.000 Zeichen als UTF-8- oder UTF-16-Datei verwenden."]);
    elements.fileInput.value = "";
    return;
  }
  try {
    const text = decodeTextFileBytes(new Uint8Array(await file.arrayBuffer()));
    if (Array.from(text).length > MAX_INPUT_CHARACTERS) {
      throw new Error("file_too_long");
    }
    elements.source.value = text;
    updateCharacterCount();
    invalidateResult();
    setStatus(`Datei „${file.name}“ lokal geöffnet.`, "ready");
  } catch (_error) {
    showError(["Die Datei muss UTF-8 oder UTF-16 sein und darf maximal 2.000.000 Zeichen enthalten."]);
  } finally {
    elements.fileInput.value = "";
  }
}

function download(filename, content, mediaType) {
  const link = document.createElement("a");
  const objectUrl = URL.createObjectURL(new Blob([content], { type: mediaType }));
  link.href = objectUrl;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 5_000);
}

async function copyResult() {
  if (!currentResult) {
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(currentResult.rewritten);
    } else {
      elements.resultText.focus();
      elements.resultText.select();
      if (!document.execCommand("copy")) {
        throw new Error("copy failed");
      }
    }
    setStatus("Ergebnis wurde in die Zwischenablage kopiert.", "ready");
  } catch (_error) {
    showError(["Kopieren wurde vom Browser verhindert. Bitte Ergebnis markieren und mit Strg+C kopieren."]);
  }
}

function saveResult() {
  if (!currentResult) {
    return;
  }
  download("text-verbessert.txt", currentResult.rewritten, "text/plain;charset=utf-8");
  setStatus("Ergebnis wurde als lokale .txt-Datei gespeichert.", "ready");
}

async function saveAudit() {
  if (!currentResult) {
    return;
  }
  try {
    const audit = await createContentlessAudit(currentResult);
    download("text-verbessert-pruefbericht.json", JSON.stringify(audit, null, 2), "application/json;charset=utf-8");
    setStatus("Datensparsamer Prüfbericht gespeichert.", "ready");
  } catch (_error) {
    showError(["Der Prüfbericht konnte in diesem Browser nicht erstellt werden."]);
  }
}

function clearAll() {
  if ((elements.source.value || elements.resultText.value) && !window.confirm("Eingabe und Ergebnis wirklich leeren?")) {
    return;
  }
  currentResult = null;
  elements.source.value = "";
  elements.protectedTerms.value = "";
  elements.resultText.value = "";
  elements.originalPreview.value = "";
  elements.resultSection.hidden = true;
  clearError();
  updateCharacterCount();
  setStatus("Bereit. Die Bearbeitung erfolgt lokal in diesem Tab.", "ready");
  elements.source.focus();
}

elements.source.addEventListener("input", () => {
  updateCharacterCount();
  invalidateResult();
});
elements.protectedTerms.addEventListener("input", invalidateResult);
document.querySelectorAll("input[name='mode']").forEach((input) => input.addEventListener("change", invalidateResult));
elements.transformButton.addEventListener("click", runTransformation);
elements.pasteButton.addEventListener("click", pasteFromClipboard);
elements.fileInput.addEventListener("change", loadLocalFile);
elements.copyButton.addEventListener("click", copyResult);
elements.saveButton.addEventListener("click", saveResult);
elements.auditButton.addEventListener("click", saveAudit);
elements.clearButton.addEventListener("click", clearAll);
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    event.preventDefault();
    runTransformation();
  }
});

updateCharacterCount();
