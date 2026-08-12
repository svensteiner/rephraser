# Text verbessern – Editorial Transformer

## Portabler Windows-Download

Für einen zweiten oder gesperrten Windows-PC gibt es eine portable Version ohne
Python-Installation:

1. [`TextVerbessern-Windows.zip`](https://github.com/svensteiner/rephraser/releases/download/portable-latest/TextVerbessern-Windows.zip) herunterladen.
2. ZIP-Datei entpacken.
3. `TextVerbessern.exe` doppelklicken.
4. Text einfügen, **Text verbessern** und **Ergebnis kopieren**.

Für den direkten Kopierablauf gibt es in der Windows-App die Schaltfläche
**Aus Zwischenablage einfügen**. Die App zeigt nur Funktionen an, die auf dem jeweiligen
PC wirklich verfügbar sind. **Schnell verbessern** arbeitet regelbasiert, vollständig
lokal und typischerweise in deutlich unter einer Sekunde. Wirkungslose Optionen werden
nicht angeboten. Nach der Bearbeitung öffnet **Änderungen ansehen** eine optionale
Gegenüberstellung: Rot markiert die frühere, Grün die neue Formulierung. Dort kann mit
einem Klick das Original oder die Verbesserung als kopierbare Fassung ausgewählt werden.
Bei bis zu 100 Änderungsbereichen ermöglicht **Änderungen einzeln auswählen** eine
Mischfassung. Jede Kombination wird vor der Übernahme erneut auf geschützte Zahlen,
Daten, Namen, Quellen, Zitate, Verneinungen, Unsicherheiten und Markdown-Struktur
geprüft. Eine auffällige Auswahl wird nicht still übernommen.
Eine verständliche Inhaltsprüfung nennt den tatsächlich geprüften Umfang und zeigt klar,
ob keine überwachte Abweichung gefunden, eine unsichere Fassung automatisch verworfen
oder eine Stelle manuell zu kontrollieren ist. Sie weist ausdrücklich darauf hin, dass
wichtige Texte weiterhin selbst gelesen werden sollten.
Während einer gründlichen Mistral-Bearbeitung liefert **Sichere Fassung jetzt** ohne
weiteres Warten die lokale Schnellbearbeitung.

**Info & Hilfe** zeigt die installierte Version und den lokalen Modellstatus. Für den
Support lassen sich datenschutzarme Diagnoseinformationen kopieren. Sie enthalten nur
Laufzeitmetadaten und den Hinweis, ob ein Metadatenprotokoll vorhanden ist – niemals den
eingefügten Text, Dokumentinhalte, Benutzernamen oder Fehlermeldungsinhalte.

Die Browser-Oberfläche zeigt nach der Bearbeitung **Original und Ergebnis nebeneinander**.
Unter **Bearbeitung anpassen** lassen sich Sprache sowie der exakte Schutz von Zahlen
und Daten, Quellen und Links sowie wörtlichen Zitaten einstellen. Eigennamen und
Tatsachenbehauptungen werden immer geprüft. Der Bereich **Änderungen und Prüfung**
enthält Diff, Unicode-Befunde und die Qualitätskennzahlen vor und nach der Bearbeitung.
Die lokale Modellbearbeitung ist auf 45 Sekunden begrenzt. Antwortet Mistral nicht
rechtzeitig, zeigt die App automatisch die sofort verfügbare sichere Bereinigung an.

Die sichere Grundbereinigung funktioniert direkt. Die sprachliche Überarbeitung steht
zusätzlich zur Verfügung, wenn auf dem jeweiligen PC Ollama mit `mistral` lokal läuft.
Es gibt keinen Cloud-Fallback. Da die EXE derzeit nicht kommerziell codesigniert ist,
kann Windows beim ersten Start eine Sicherheitsabfrage anzeigen.

## Einfachster Start unter Windows

1. Doppelklicke im Projektordner auf **`TEXT VERBESSERN.cmd`**.
2. Füge einen Text aus Claude oder einer anderen Quelle ein.
3. Klicke auf **Text verbessern**.
4. Klicke auf **Ergebnis kopieren**.

Beim ersten Start richtet das Startprogramm eine private Laufzeitumgebung unter
`%LOCALAPPDATA%\LLP\EditorialTransformer` ein. Administratorrechte sind nicht nötig.
Danach öffnet sich die Anwendung automatisch im Browser und ist ausschließlich unter
`127.0.0.1` erreichbar. Eine bebilderungsfreie Kurzfassung steht in
[`SCHNELLSTART.md`](SCHNELLSTART.md).

A production-oriented, local-first Python application for turning draft text into an
edited version while auditing preservation of facts, numbers, dates, names, quotations,
citations, URLs, uncertainty, Markdown, and argument structure.

This application optimizes editorial quality—not detector scores. It does not calculate
an “AI probability,” claim that text is undetectable, or attempt to defeat AI provenance
or statistical watermarking systems.

## DE/EN quality regression gate

Realistic German and English business-text cases are versioned in
`app/evaluation_cases.json`. They cover the paste-from-Claude email workflow,
conciseness edits, negative controls, protected quotations, Markdown, URLs, numbers,
dates, negation, uncertainty, Unicode cleanup, and emoji. Every case fixes the expected
output, protected values, warning state, and applied local provider. Run the same gate
used by GitHub Actions with:

```powershell
python -m app.evaluation
```

The command exits non-zero and reports the exact mismatch if a future change alters a
golden output, loses protected content, introduces a semantic warning, or silently falls
back to another provider.

## Privacy and provider model

The default `fast-editor` stage is deterministic, offline, and immediate. It applies a
small set of tested business-language improvements while protecting quotations and code.
It sends neither text nor derived features anywhere. The optional thorough mode uses
`mistral-local` when the local model is available. It talks to an Ollama-compatible endpoint
on `127.0.0.1`, `localhost`, or `::1`; non-loopback URLs are rejected. A Mistral failure
never triggers a cloud fallback. OpenAI and Anthropic adapter classes are present as
interchangeable extension points but deliberately disabled pending an explicit data
transmission review.

The pure cleanup mode is deliberately conservative: it normalizes NFC/line endings and
cleans known copy/paste artifacts. The instant editor performs only narrowly scoped,
audited phrase improvements; any preservation warning discards that draft. Broader
rewriting remains available through local Mistral. Unknown invisible characters are
reported and retained.

GitHub stores source code, tests, documentation, and releases only. Pasted text, edited
results, audit reports, and local logs are never committed or uploaded automatically.

## Install

```powershell
cd 'K:\LLP Wirtschaftsprüfung\AI Tools\paraphraser\editorial-transformer'
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,ui]"
```

## Run

CLI, fully offline:

```powershell
editorial-transformer examples\sample.md -o edited.md --provider fast-editor
Get-Content input.txt -Raw | editorial-transformer --stdin --provider fast-editor
```

Local Mistral through Ollama:

```powershell
ollama pull mistral
ollama serve
$env:MISTRAL_MODEL='mistral'
editorial-transformer input.md -o edited.md --provider mistral-local
```

REST API and interactive docs:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# Open http://127.0.0.1:8000/docs
```

Streamlit (manual developer start):

```powershell
streamlit run app/ui/streamlit_app.py
```

Tests:

```powershell
pytest
```

## REST example

```powershell
$body = @{
  text = 'Es ist wichtig zu beachten, dass der Wert 4,25 % beträgt.'
  options = @{ provider = 'rules'; tone = 'concise'; rewrite_strength = 'medium'; language = 'German' }
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/transform -Method Post -ContentType application/json -Body $body
```

Each result includes the rewritten text and an audit with SHA-256 input/output hashes, UTC time,
pipeline version, requested/applied local provider and effective options, before/after Unicode
inspection, grouped code-point counts and positions, semantic constraints, transformations with
explicit offsets and code points, preservation warnings, word/sentence diff, and before/after
descriptive quality metrics.

File export writes the result, JSON audit and sentence diff as three separate files.
Each target is replaced atomically so an interrupted write does not leave a partial file.

## Fail-safe limits

Deterministic validation can prove exact-string preservation, but it cannot prove full
semantic equivalence. Any missing protected value, introduced number/date/citation, changed
negation or uncertainty, altered Markdown structure, or weakly supported claim becomes a
warning. Unsafe editorial candidates are rejected in favor of conservative local cleanup.
Publication remains a human editorial decision.

When a document contains multiple protected values, the validator also checks for strong evidence
that numbers, dates, names, quotations or citations were reassigned between factual contexts—for
example, a revenue figure swapped with an operating-profit figure even though both exact numbers
still appear. Paragraph and Markdown-list boundaries are treated as separate contexts.

Local Mistral calls have both socket limits and a hard wall-clock deadline. If the model is
unavailable or responds too slowly, the application returns conservative local cleanup and never
falls back to a cloud service.

The optional single-pass Mistral mode is offered for inputs up to 12,000 characters. Longer
documents remain fully supported by the fast local editor and safe Unicode/format cleanup; the UI
selects that path before processing and the audit records `model_input_too_long` for direct API
requests. No document is truncated and no hidden network request is attempted at the boundary.

The Windows download uses a portable folder build for faster startup. Keep `TextVerbessern.exe`
and its `_internal` folder together after extracting the ZIP. `VERSION.txt` and
`release-manifest.json` identify the exact version, commit and SHA-256 file hashes. Privacy-safe
desktop diagnostics contain only event codes, version and exception type—not entered text—and are
stored under `%LOCALAPPDATA%\LLP\EditorialTransformer\logs`.

## Open-source design influences

The implementation does not copy third-party code, but it adopts useful product ideas from mature
open-source paraphrasing work. Parrot's separation of adequacy, fluency and surface diversity
inspired the explicit surface-change indicator and the strict preservation gate. Rasa's scored
paraphrase workflow reinforced the decision to keep generation separate from validation. Unlike
those augmentation tools, Editorial Transformer is optimized for complete business documents,
Markdown preservation and a single reviewed result rather than many candidate sentences.

- [Parrot Paraphraser (Apache-2.0)](https://github.com/PrithivirajDamodaran/Parrot_Paraphraser)
- [RasaHQ Paraphraser](https://github.com/RasaHQ/paraphraser)
