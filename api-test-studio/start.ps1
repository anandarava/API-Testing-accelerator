param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
& ./.venv/Scripts/python.exe -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

Push-Location -LiteralPath 'web'
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Web dependency installation failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
} finally { Pop-Location }

Write-Host ""
Write-Host "API Test Studio is starting on http://127.0.0.1:$Port  (Ctrl+C to stop)"
& ./.venv/Scripts/python.exe -m uvicorn studio.main:app --host 127.0.0.1 --port $Port
