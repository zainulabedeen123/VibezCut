<#
.SYNOPSIS
  Download the caption fonts listed in fonts-lock.json into <Dest>\<Family>\, checking each SHA-256.

.DESCRIPTION
  Every font is openly licensed (SIL OFL 1.1 or Apache 2.0) and its licence file is listed in the lock
  next to it, so it lands in the same folder. Fonts are not committed to the repository; this runs at
  packaging time. VibezCut loads <exe dir>\fonts at startup (see filmcraft_engine::load_bundled_fonts).

.EXAMPLE
  pwsh packaging/vibezcut/bundle-fonts.ps1 -Dest dist\vibezcut\VibezCut-0.2.14\fonts
#>
param(
  [Parameter(Mandatory)] [string] $Dest,
  [string] $Lock
)
$ErrorActionPreference = 'Stop'
if (-not $Lock) { $Lock = Join-Path $PSScriptRoot 'fonts-lock.json' }
$ProgressPreference = 'SilentlyContinue'
$lockData = Get-Content -Raw $Lock | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$total = 0
foreach ($f in $lockData.files) {
  $out = Join-Path $Dest $f.file
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
  $ok = $false
  for ($try = 1; $try -le 3 -and -not $ok; $try++) {
    try {
      Invoke-WebRequest -Uri $f.url -OutFile $out -UseBasicParsing
      $ok = $true
    } catch {
      if ($try -eq 3) { throw "download failed: $($f.url): $_" }
      Start-Sleep -Seconds (2 * $try)
    }
  }
  $hash = (Get-FileHash -Algorithm SHA256 $out).Hash.ToLower()
  if ($hash -ne $f.sha256) { throw "sha256 mismatch for $($f.file): got $hash, want $($f.sha256)" }
  $total += (Get-Item $out).Length
}
Write-Output ("==> fonts: {0} files, {1:N1} MB in {2}" -f $lockData.files.Count, ($total / 1MB), $Dest)
