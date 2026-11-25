# start-backend.ps1 — lance le serveur Django de MIA.
#
# Usage :
#   .\start-backend.ps1            # mode iPhone : 0.0.0.0:8000 (+ Tailscale)
#   .\start-backend.ps1 -Local     # mode PC local : 127.0.0.1:8000
#
# Il rassemble les réglages décrits dans docs/mobile-iphone.md :
#   - applique les migrations en attente (idempotent, rapide) ;
#   - détecte l'IP/le nom Tailscale du PC et les ajoute à DJANGO_ALLOWED_HOSTS ;
#   - prend les clés depuis l'environnement (session ou utilisateur) ou t'en
#     demande une à la fois si elles manquent ;
#   - lance ensuite runserver (Ctrl+C pour arrêter).
#
# Aucun secret n'est jamais écrit dans le dépôt : seulement en environnement.

param(
    [switch]$Local  # Serveur PC local uniquement (127.0.0.1:8000)
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
$managePy = Join-Path $backend "manage.py"

if (-not (Test-Path $venvPy)) { Write-Error "Venv introuvable : $venvPy"; exit 1 }
if (-not (Test-Path $managePy)) { Write-Error "manage.py introuvable : $managePy"; exit 1 }

function Get-EnvVar([string]$Name) {
    foreach ($scope in @("Process", "User")) {
        $v = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    }
    return ""
}

function Show-Masked([string]$v) {
    if ($v.Length -lt 4) { return "****" }
    return $v.Substring(0, 4) + "…"
}

# Récupère une variable ; si absente, la demande et offre de la conserver
# (setx -> variable utilisateur, disponible dans tous les terminaux).
function Ensure-EnvVar([string]$Name, [string]$Description, [switch]$Optional) {
    $val = Get-EnvVar $Name
    if (-not [string]::IsNullOrWhiteSpace($val)) {
        [Environment]::SetEnvironmentVariable($Name, $val, "Process")
        return $val
    }
    if ($Optional) { return "" }
    $val = Read-Host "  $Description absent -> saisis-la (ou Entree pour ignorer)"
    if ([string]::IsNullOrWhiteSpace($val)) {
        Write-Warning "  $Name non definie : les clients distants seront refuses (401)."
        return ""
    }
    $persist = Read-Host "  Conserver '$Name' en variable utilisateur ? (o/N)"
    if ($persist -match "^(o|y|oui|yes)$") {
        setx $Name $val | Out-Null
        Write-Host "  -> enregistree (accessible dans chaque nouveau terminal)."
    }
    [Environment]::SetEnvironmentVariable($Name, $val, "Process")
    return $val
}

function Get-TailscaleExe {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
        "$env:ProgramFiles\Tailscale\tailscale.exe",
        "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe",
        "$env:LOCALAPPDATA\Programs\Tailscale\tailscale.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "=== MIA - demarrage du backend ===" -ForegroundColor Cyan

# 1) Migrations en attente (idempotent ; applique 0008_brainrotevent si besoin)
Write-Host "`n[1/3] Migrations en attente..."
Push-Location $backend
& $venvPy manage.py migrate
Pop-Location

# 2) Configuration réseau
if ($Local) {
    Write-Host "`n[2/3] Mode PC local (127.0.0.1:8000)."
    $bind = "127.0.0.1:8000"
    [Environment]::SetEnvironmentVariable("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1", "Process")
} else {
    Write-Host "`n[2/3] Mode iPhone (0.0.0.0:8000, via Tailscale)."
    $bind = "0.0.0.0:8000"

    $tsExe = Get-TailscaleExe
    $tsIP = ""
    $tsDNS = ""
    if ($tsExe) {
        $tsIP = (& $tsExe ip -4 2>$null | Select-Object -First 1).Trim()
        try {
            $status = & $tsExe status --json 2>$null | ConvertFrom-Json
            if ($status.Self.DNSName) { $tsDNS = $status.Self.DNSName.TrimEnd(".") }
        } catch {}
    } else {
        Write-Warning "  tailscale introuvable dans le PATH : je te demanderai l'IP/hostname."
    }

    $hosts = @()
    $existing = Get-EnvVar "DJANGO_ALLOWED_HOSTS"
    if ($existing) { $hosts += ($existing -split ",") }
    if ($tsIP)   { $hosts += $tsIP }
    if ($tsDNS)  { $hosts += $tsDNS }
    if ($env:COMPUTERNAME) { $hosts += $env:COMPUTERNAME }
    $hosts = $hosts | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique

    if (-not $hosts) {
        Write-Warning "  Aucun hote Tailscale detecte : ajoute ton IP/hostname manuellement."
        $custom = Read-Host "  DJANGO_ALLOWED_HOSTS (ex. 100.101.102.103,mon-nom.ts.net)"
        if ($custom) { $hosts += ($custom -split ",") }
    }
    if (-not $hosts) { $hosts = @("localhost") }

    [Environment]::SetEnvironmentVariable("DJANGO_ALLOWED_HOSTS", ($hosts -join ","), "Process")
    Write-Host "  ALLOWED_HOSTS : $($hosts -join ', ')"
    if ($tsIP) { Write-Host "  A saisir dans l'app iOS : http://$tsIP`:8000" -ForegroundColor Green }
}

# 3) Clés d'accès
Write-Host "`n[3/3] Cles d'acces."
if ($Local) {
    Write-Host "  Mode local : cles optionnelles, ignorees pour 127.0.0.1."
} else {
    $miaKey = Ensure-EnvVar "MIA_API_KEY" "MIA_API_KEY (a coller dans les Reglages de l'app)"
    $briKey = Ensure-EnvVar "BRIEFING_API_KEY" "BRIEFING_API_KEY (briefing, optionnelle)" -Optional
    if ($miaKey) { Write-Host "  MIA_API_KEY : $(Show-Masked $miaKey)" }
    if ($briKey) { Write-Host "  BRIEFING_API_KEY : $(Show-Masked $briKey)" }
    Write-Host "  ICLOUD_* pour le briefing : repris des variables utilisateur si presentes (sinon briefing hors ligne)."
}

# 4) Lancement
Write-Host "`nDemarrage du serveur... (Ctrl+C pour arreter)" -ForegroundColor Cyan
Push-Location $backend
& $venvPy manage.py runserver $bind
$code = $LASTEXITCODE
Pop-Location
exit $code
