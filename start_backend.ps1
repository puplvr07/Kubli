$ErrorActionPreference = 'Stop'

$repositoryRoot = $PSScriptRoot
$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$backend = Join-Path $repositoryRoot 'backend'
$whisperModel = Join-Path $repositoryRoot '.wardnote\models\whisper-small'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python was not found at $python. Create .venv and install backend requirements first."
}
if (-not (Test-Path -LiteralPath $whisperModel -PathType Container)) {
    throw "Whisper model was not found at $whisperModel. Download it before starting the backend."
}

$env:WHISPER_MODEL_PATH = (Resolve-Path -LiteralPath $whisperModel).Path
Push-Location -LiteralPath $backend
try {
    & $python -m app.main
    $backendExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $backendExitCode
