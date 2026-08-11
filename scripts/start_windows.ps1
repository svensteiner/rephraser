param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA "LLP\EditorialTransformer"
$venvRoot = Join-Path $runtimeRoot "venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$logRoot = Join-Path $runtimeRoot "logs"
$logPath = Join-Path $logRoot "start.log"
$markerPath = Join-Path $runtimeRoot "pyproject.sha256"

New-Item -ItemType Directory -Force -Path $runtimeRoot, $logRoot | Out-Null
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Host "Text verbessern wird gestartet ..." -ForegroundColor Cyan
    Set-Location -LiteralPath $projectRoot

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Einmalige Einrichtung: Programmpakete werden geladen." -ForegroundColor Yellow
        Write-Host "Dabei wird kein eingegebener Text uebertragen." -ForegroundColor DarkGray

        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            & $pyLauncher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
            if ($LASTEXITCODE -ne 0) { throw "Python 3.12 oder neuer ist erforderlich." }
            & $pyLauncher.Source -3 -m venv $venvRoot
        }
        else {
            $python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $python) { throw "Python wurde nicht gefunden. Bitte Python 3.12 oder neuer installieren." }
            & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
            if ($LASTEXITCODE -ne 0) { throw "Python 3.12 oder neuer ist erforderlich." }
            & $python.Source -m venv $venvRoot
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            throw "Die lokale Programmumgebung konnte nicht erstellt werden."
        }
    }

    $pyproject = Join-Path $projectRoot "pyproject.toml"
    $currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $pyproject).Hash
    $installedHash = if (Test-Path -LiteralPath $markerPath) {
        (Get-Content -Raw -LiteralPath $markerPath).Trim()
    } else { "" }

    if ($currentHash -ne $installedHash) {
        Write-Host "Anwendung wird eingerichtet oder aktualisiert ..." -ForegroundColor Yellow
        & $venvPython -m pip install --disable-pip-version-check -e "${projectRoot}[ui]"
        if ($LASTEXITCODE -ne 0) { throw "Die benoetigten Programmpakete konnten nicht installiert werden." }
        Set-Content -LiteralPath $markerPath -Value $currentHash -Encoding ASCII
    }

    if ($CheckOnly) {
        Write-Host "Startpruefung erfolgreich." -ForegroundColor Green
        exit 0
    }

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ($listener.LocalEndpoint).Port
    $listener.Stop()

    Write-Host "Der Browser oeffnet sich gleich." -ForegroundColor Green
    Write-Host "Dieses Fenster offen lassen. Schliessen beendet die Anwendung." -ForegroundColor DarkGray
    & $venvPython -m streamlit run "app/ui/streamlit_app.py" `
        --server.address 127.0.0.1 `
        --server.port $port `
        --server.headless false `
        --server.fileWatcherType none `
        --browser.gatherUsageStats false
    if ($LASTEXITCODE -ne 0) { throw "Die Benutzeroberflaeche wurde unerwartet beendet." }
}
catch {
    Write-Host ""
    Write-Host "Start nicht moeglich: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Protokoll: $logPath" -ForegroundColor Yellow
    exit 1
}
finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
