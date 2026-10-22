# Buduje instalator agenta druku na Windows:
#   venv (tools/agent_druku/.venv) -> pip install -r requirements.txt -> PyInstaller (onedir
#   AgentDruku\AgentDruku.exe) -> Inno Setup -> packaging\wynik\AgentDruku-<WERSJA>-setup.exe.
# Wersja z agent_druku.WERSJA. Uruchomienie z dowolnego katalogu:
#   powershell -ExecutionPolicy Bypass -File tools\agent_druku\packaging\zbuduj.ps1
# WinSW nie jest w repo: pobierz WinSW-x64.exe v2.12.0 z oficjalnych wydań
#   https://github.com/winsw/winsw/releases/tag/v2.12.0
# do packaging\vendor\ — skrypt sprawdza jego SHA-256 i bez zgodnej sumy nie buduje.
param(
    [string]$Iscc = ''
)
$ErrorActionPreference = 'Stop'

$WinswSha256 = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'

$Pakowanie = $PSScriptRoot
$Agent = Split-Path $Pakowanie -Parent
$Venv = Join-Path $Agent '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Winsw = Join-Path $Pakowanie 'vendor\WinSW-x64.exe'
$Dist = Join-Path $Pakowanie 'dist'
$Build = Join-Path $Pakowanie 'build'
$Wynik = Join-Path $Pakowanie 'wynik'

function Uruchom([string]$Program, [string[]]$Argumenty) {
    # Programy zewnętrzne piszą na stderr także przy sukcesie — o wyniku decyduje kod wyjścia.
    $poprzednie = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Program @Argumenty
        $kod = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $poprzednie
    }
    if ($kod -ne 0) { throw "Polecenie zakończone kodem ${kod}: $Program $($Argumenty -join ' ')" }
}

# 1. WinSW — tylko oficjalne wydanie o znanej sumie.
if (-not (Test-Path $Winsw)) {
    throw "Brak $Winsw. Pobierz WinSW-x64.exe v2.12.0 z https://github.com/winsw/winsw/releases/tag/v2.12.0"
}
$suma = (Get-FileHash -Algorithm SHA256 $Winsw).Hash.ToLowerInvariant()
if ($suma -ne $WinswSha256) {
    throw "WinSW-x64.exe ma inną sumę SHA-256 ($suma) niż oczekiwana ($WinswSha256) — nie buduję."
}

# 2. Inno Setup.
if (-not $Iscc) {
    foreach ($k in @("${env:ProgramFiles(x86)}\Inno Setup 6", "$env:ProgramFiles\Inno Setup 6")) {
        if (Test-Path (Join-Path $k 'ISCC.exe')) { $Iscc = Join-Path $k 'ISCC.exe'; break }
    }
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { throw 'Brak Inno Setup 6 (ISCC.exe) — zainstaluj go albo podaj -Iscc <ścieżka>.' }

# 3. venv i zależności (wersje przypięte w requirements.txt).
if (-not (Test-Path $Python)) {
    Uruchom 'py' @('-3.12', '-m', 'venv', $Venv)
}
Uruchom $Python @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $Agent 'requirements.txt'))

$Wersja = (& $Python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import agent_druku; print(agent_druku.WERSJA)" $Agent).Trim()
if ($LASTEXITCODE -ne 0 -or $Wersja -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$') { throw "Nie odczytano wersji agenta: '$Wersja'" }
Write-Host "Agent druku $Wersja"

# 4. PyInstaller (onedir).
Uruchom $Python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
    '--distpath', $Dist, '--workpath', $Build, (Join-Path $Pakowanie 'agent_druku.spec'))
$Exe = Join-Path $Dist 'AgentDruku\AgentDruku.exe'
if (-not (Test-Path $Exe)) { throw "PyInstaller nie zbudował $Exe" }

# 5. Inno Setup.
New-Item -ItemType Directory -Force $Wynik | Out-Null
Uruchom $Iscc @('/Q', "/DWersja=$Wersja", "/DZrodlo=$(Join-Path $Dist 'AgentDruku')", "/DWinsw=$Winsw",
    "/O$Wynik", (Join-Path $Pakowanie 'instalator.iss'))
$Setup = Join-Path $Wynik "AgentDruku-$Wersja-setup.exe"
if (-not (Test-Path $Setup)) { throw "Inno Setup nie zbudował $Setup" }
$setupSha = (Get-FileHash -Algorithm SHA256 $Setup).Hash.ToLowerInvariant()
Write-Host "Gotowe: $Setup ($((Get-Item $Setup).Length) B, SHA-256 $setupSha)"
