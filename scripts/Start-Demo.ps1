param(
    [ValidateSet('offline', 'databricks', 'foundry')]
    [string]$Mode = 'offline',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [switch]$DownloadPublic
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($DownloadPublic) {
    & $python -m app.corpus --public
} elseif (-not (Test-Path 'data\manifest.json')) {
    & $python -m app.corpus
}
if ($LASTEXITCODE -ne 0) { throw 'Corpus preparation failed.' }
$env:RAG_MODE = $Mode
$selectedPort = $Port
while ($true) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $selectedPort)
    try {
        $listener.Start()
        $listener.Stop()
        break
    } catch {
        $selectedPort++
        if ($selectedPort -gt 65535) { throw 'No available local port.' }
    }
}
Write-Host "Presenter URL: http://127.0.0.1:$selectedPort"
Write-Host "Mode: $Mode. This application is loopback-only, not a public authenticated service."
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $selectedPort
