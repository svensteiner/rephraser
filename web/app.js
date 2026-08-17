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
  fileButton: document.querySelector("#file-button"),
  pasteButton: document.querySelector("#paste-button"),
  transformButton: document.querySelector("#transform-button"),
  status: document.querySelector("#status-message"),
  error: document.querySelector("#error-message"),
  characterCount: document.querySelector("#character-count"),
  modeHelp: document.querySelector("#mode-help"),
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
  reviewConfirmation: document.querySelector("#review-confirmation"),
  reviewCheckbox: document.querySelector("#review-checkbox"),
};

let currentResult = null;
let isTransforming = false;
let inputVersion = 0;
let nextRequestId = 0;
let activeRequestId = null;

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

function transformButtonLabel() {
  return selectedMode() === MODE_FAST ? "Formulierungen glätten" : "Format bereinigen";
}

function resultNeedsReview(result = currentResult) {
  return Boolean(
    result
    && result.mode === MODE_FAST
    && result.modifications.some((change) => change.kind.startsWith("phrase_rule_")),
  );
}

function setResultActions() {
  const hasResult = Boolean(currentResult);
  const reviewRequired = resultNeedsReview();
  const reviewConfirmed = elements.reviewCheckbox.checked;
  elements.reviewConfirmation.hidden = !reviewRequired;
  elements.reviewCheckbox.disabled = isTransforming || !reviewRequired;
  elements.copyButton.disabled = isTransforming || !hasResult || (reviewRequired && !reviewConfirmed);
  elements.saveButton.disabled = isTransforming || !hasResult;
  elements.auditButton.disabled = isTransforming || !hasResult;
  elements.clearButton.disabled = isTransforming;
}

function updateModeGuidance() {
  const usingFastMode = selectedMode() === MODE_FAST;
  elements.modeHelp.textContent = usingFastMode
    ? "Sprachliche Glättung ist aktiv. Prüfe die Änderungen; Kopieren wird erst nach deiner Bestätigung freigegeben."
    : "Standard: Nur Copy/Paste- und Format-Artefakte bereinigen. Danach kannst du direkt kopieren.";
  if (!isTransforming) {
    elements.transformButton.textContent = transformButtonLabel();
  }
}

function createTransformationRequest(source, mode, protectedTermsInput, protectedTerms) {
  return Object.freeze({
    id: ++nextRequestId,
    inputVersion,
    source,
    mode,
    protectedTermsInput,
    protectedTerms: Object.freeze([...protectedTerms]),
  });
}

function isCurrentRequest(request) {
  return activeRequestId === request.id
    && inputVersion === request.inputVersion
    && elements.source.value === request.source
    && selectedMode() === request.mode
    && elements.protectedTerms.value === request.protectedTermsInput;
}

function discardStaleRequest() {
  setStatus("Die Eingabe wurde während der Bearbeitung geändert. Das Ergebnis wurde verworfen – bitte erneut starten.", "ready");
}

function updateCharacterCount() {
  const count = Array.from(elements.source.value).length;
  elements.characterCount.textContent = `${formatNumber(count)} Zeichen`;
  if (count > MAX_INPUT_CHARACTERS) {
    elements.characterCount.textContent += " – zu lang";
  }
}

function invalidateResult({ announce = true } = {}) {
  const hadResult = Boolean(currentResult);
  currentResult = null;
  elements.resultSection.hidden = true;
  elements.resultText.value = "";
  elements.originalPreview.value = "";
  elements.reviewCheckbox.checked = false;
  setResultActions();
  if (announce && hadResult) {
    setStatus("Eingabe geändert. Bitte Text erneut verbessern.", "ready");
  }
}

function noteInputChanged() {
  inputVersion += 1;
  invalidateResult({ announce: !isTransforming });
  if (isTransforming) {
    setStatus("Eingabe geändert. Das laufende Ergebnis wird verworfen.", "working");
  }
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
  elements.reviewCheckbox.checked = false;
  elements.originalPreview.value = result.original;
  elements.resultText.value = result.rewritten;
  elements.beforeStats.textContent = statLabel(result.before_statistics);
  elements.afterStats.textContent = statLabel(result.after_statistics);
  renderChanges(result);
  renderFindings(result);
  elements.resultSection.hidden = false;
  setResultActions();
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  elements.resultSection.scrollIntoView({ behavior, block: "start" });
  elements.resultHeading.focus({ preventScroll: true });
  if (resultNeedsReview(result)) {
    setStatus("Sprachliche Glättung fertig. Prüfe die Änderungen und bestätige sie vor dem Kopieren.", "ready");
  } else {
    setStatus("Formatbereinigung fertig. Du kannst das Ergebnis kopieren.", "ready");
  }
}

function setTransformBusy(isBusy) {
  elements.transformButton.disabled = isBusy;
  elements.transformButton.textContent = isBusy ? "Wird lokal bearbeitet …" : transformButtonLabel();
  elements.source.readOnly = isBusy;
  elements.protectedTerms.readOnly = isBusy;
  elements.pasteButton.disabled = isBusy;
  elements.fileButton.disabled = isBusy;
  elements.fileInput.disabled = isBusy;
  document.querySelectorAll("input[name='mode']").forEach((input) => {
    input.disabled = isBusy;
  });
  setResultActions();
}

function nextPaint() {
  return new Promise((resolve) => {
    let finished = false;
    const finish = () => {
      if (!finished) {
        finished = true;
        resolve();
      }
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(finish);
    }
    // Background tabs may pause animation frames. Keep the visible progress
    // state from turning into an indefinite wait in that case.
    window.setTimeout(finish, 250);
  });
}

async function runTransformation() {
  if (isTransforming) {
    return;
  }
  clearError();
  const source = elements.source.value;
  const mode = selectedMode();
  const protectedTermsInput = elements.protectedTerms.value;
  if (!source.trim()) {
    showError(["Bitte zuerst Text einfügen oder eine .txt/.md-Datei öffnen."]);
    elements.source.focus();
    return;
  }
  const protectedTerms = normalizeProtectedTerms(protectedTermsInput);
  if (protectedTerms.errors.length) {
    showError(protectedTerms.errors);
    return;
  }
  const request = createTransformationRequest(source, mode, protectedTermsInput, protectedTerms.terms);
  activeRequestId = request.id;
  invalidateResult({ announce: false });
  isTransforming = true;
  setTransformBusy(true);
  setStatus("Bearbeite lokal in diesem Browser-Tab …", "working");
  try {
    await nextPaint();
    if (!isCurrentRequest(request)) {
      discardStaleRequest();
      return;
    }
    const result = transformText(request.source, { mode: request.mode, protectedTerms: request.protectedTerms });
    if (!isCurrentRequest(request)) {
      discardStaleRequest();
      return;
    }
    if (result.blocked) {
      const messages = [...result.errors];
      if (result.missing_protected_terms.length) {
        messages.push(`Nicht im Ausgangstext gefunden: ${result.missing_protected_terms.join(", ")}.`);
      }
      showError(messages);
      return;
    }
    renderResult(result);
  } catch (_error) {
    showError(["Die lokale Bearbeitung konnte nicht abgeschlossen werden. Bitte Eingabe prüfen und erneut versuchen."]);
  } finally {
    if (activeRequestId === request.id) {
      activeRequestId = null;
      isTransforming = false;
      setTransformBusy(false);
    }
  }
}

async function pasteFromClipboard() {
  if (isTransforming) {
    return;
  }
  clearError();
  try {
    if (!navigator.clipboard?.readText) {
      throw new Error("Zwischenablagezugriff wird von diesem Browser nicht angeboten.");
    }
    const text = await navigator.clipboard.readText();
    elements.source.value = text;
    updateCharacterCount();
    noteInputChanged();
    setStatus("Zwischenablage eingefügt. Du kannst den Text jetzt verbessern.", "ready");
    elements.source.focus();
  } catch (_error) {
    showError(["Die Zwischenablage darf hier nicht automatisch gelesen werden. Bitte den Text mit Strg+V einfügen."]);
  }
}

async function loadLocalFile() {
  if (isTransforming) {
    return;
  }
  clearError();
  const [file] = elements.fileInput.files;
  if (!file) {
    return;
  }
  if (!/\.(txt|md)$/iu.test(file.name)) {
    showError(["Bitte nur eine .txt- oder .md-Datei auswählen."]);
    // Reset even after a rejected selection so the same corrected file can be
    // selected again and still emits a change event in every browser.
    elements.fileInput.value = "";
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
    noteInputChanged();
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
  if (!currentResult || isTransforming) {
    return;
  }
  if (resultNeedsReview() && !elements.reviewCheckbox.checked) {
    elements.reviewCheckbox.focus();
    setStatus("Bitte bestätige nach der Prüfung die sprachlichen Änderungen, bevor du kopierst.", "ready");
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
  if (!currentResult || isTransforming) {
    return;
  }
  download("text-verbessert.txt", currentResult.rewritten, "text/plain;charset=utf-8");
  setStatus("Ergebnis wurde als lokale .txt-Datei gespeichert.", "ready");
}

async function saveAudit() {
  if (!currentResult || isTransforming) {
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
  if (isTransforming) {
    return;
  }
  const hasLocalContent = Boolean(
    elements.source.value || elements.resultText.value || elements.protectedTerms.value,
  );
  if (hasLocalContent && !window.confirm("Eingabe, Ergebnis und geschützte Begriffe wirklich leeren?")) {
    setStatus("Leeren abgebrochen. Dein Text bleibt erhalten.", "ready");
    return;
  }
  inputVersion += 1;
  invalidateResult({ announce: false });
  elements.source.value = "";
  elements.protectedTerms.value = "";
  clearError();
  updateCharacterCount();
  setStatus("Bereit. Standardmäßig wird nur das Format lokal bereinigt.", "ready");
  elements.source.focus();
}

elements.source.addEventListener("input", () => {
  updateCharacterCount();
  noteInputChanged();
});
elements.protectedTerms.addEventListener("input", noteInputChanged);
document.querySelectorAll("input[name='mode']").forEach((input) => input.addEventListener("change", () => {
  noteInputChanged();
  updateModeGuidance();
}));
elements.transformButton.addEventListener("click", runTransformation);
elements.pasteButton.addEventListener("click", pasteFromClipboard);
elements.fileButton.addEventListener("click", () => {
  if (!isTransforming) {
    elements.fileInput.click();
  }
});
elements.fileInput.addEventListener("change", loadLocalFile);
elements.copyButton.addEventListener("click", copyResult);
elements.saveButton.addEventListener("click", saveResult);
elements.auditButton.addEventListener("click", saveAudit);
elements.clearButton.addEventListener("click", clearAll);
elements.reviewCheckbox.addEventListener("change", () => {
  setResultActions();
  if (currentResult && resultNeedsReview() && elements.reviewCheckbox.checked) {
    setStatus("Prüfung bestätigt. Das Ergebnis kann jetzt kopiert werden.", "ready");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    event.preventDefault();
    runTransformation();
  }
});

updateCharacterCount();
updateModeGuidance();
setResultActions();
