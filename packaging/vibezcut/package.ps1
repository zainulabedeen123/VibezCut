<#
.SYNOPSIS
  Build and package VibezCut for Windows x64.

.DESCRIPTION
  Produces in dist\vibezcut\:
    VibezCut-<version>-windows-x64.zip   the editor + CLI + the VibezCut Studio layer, unzip and run

  Layout inside the zip (VibezCut-<version>\):
    VibezCut.exe, vibezcut-cli.exe        the editor and its command line (MCP server)
    Start VibezCut (Claude control).bat   start the editor so Claude can edit live
    studio\                               Python pipeline + filmcraft-studio MCP server
    docs\                                 STUDIO.md, WORKFLOW.md
    claude-skill\                         the Claude skills (filmcraft-edit, pack-for-editor)
    python\                               private Python 3.12 for the MCP server (live editing; no transcription)
    fonts\                                caption fonts (OFL / Apache 2.0, licence next to each family)
    LICENSE-MIT, LICENSE-APACHE, NOTICE, ATTRIBUTION.md

  The binaries link the C runtime statically, so no Visual C++ redistributable is needed.

.EXAMPLE
  pwsh packaging/vibezcut/package.ps1 -Version 0.1.0
  pwsh packaging/vibezcut/package.ps1 -Version 0.1.0 -SkipBuild
#>
param(
  [string] $Version = $env:VIBEZCUT_VERSION,
  [switch] $SkipBuild,
  [switch] $SkipPython,
  [switch] $SkipFonts
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Version) { $Version = '0.1.0-dev' }
$Version = $Version.TrimStart('v')
$env:VIBEZCUT_VERSION = $Version
$Target = 'x86_64-pc-windows-msvc'
$TargetDir = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $Root 'target' }

if (-not $SkipBuild) {
  $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS = '-C target-feature=+crt-static'
  $env:FILMCRAFT_REQUIRE_WINRES = '1'
  if (-not $env:FILMCRAFT_BUILD_SHA) { $env:FILMCRAFT_BUILD_SHA = (git -C $Root rev-parse HEAD) }
  Write-Output "==> cargo build VibezCut $Version ($Target)"
  cargo build --release --locked -p filmcraft -p filmcraft-cli --target $Target
  if ($LASTEXITCODE -ne 0) { throw "cargo build failed ($LASTEXITCODE)" }
}

$Bin = Join-Path $TargetDir "$Target\release"
$Name = "VibezCut-$Version"
$Out = Join-Path $Root 'dist\vibezcut'
$Stage = Join-Path $Out $Name
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Copy-Item (Join-Path $Bin 'filmcraft.exe') (Join-Path $Stage 'VibezCut.exe')
Copy-Item (Join-Path $Bin 'filmcraft-cli.exe') (Join-Path $Stage 'vibezcut-cli.exe')
Copy-Item (Join-Path $Root 'Start VibezCut (Claude control).bat') $Stage

# Studio layer (no per-machine settings, no caches)
$Studio = Join-Path $Stage 'studio'
New-Item -ItemType Directory -Force -Path $Studio | Out-Null
Copy-Item (Join-Path $Root 'studio\run_server.py') $Studio
Copy-Item -Recurse (Join-Path $Root 'studio\studio') $Studio
Copy-Item -Recurse (Join-Path $Root 'studio\assets') $Studio
Get-ChildItem -Recurse -Path $Studio -Include '__pycache__', 'studio.json' | Remove-Item -Recurse -Force
Copy-Item (Join-Path $Root 'studio\requirements.txt') $Studio

New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'docs') | Out-Null
Copy-Item (Join-Path $Root 'docs\vibezcut\*.md') (Join-Path $Stage 'docs')
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'claude-skill') | Out-Null
foreach ($skill in 'filmcraft-edit', 'pack-for-editor') {
  Copy-Item -Recurse (Join-Path $Root ".claude\skills\$skill") (Join-Path $Stage 'claude-skill')
}
# private Python for the MCP server, so Claude's live editing tools work without installing Python
if (-not $SkipPython) {
  & (Join-Path $PSScriptRoot 'bundle-python.ps1') -Dest (Join-Path $Stage 'python') -PyVersion '3.12.10' `
    -Sha256 '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
}
# caption fonts, loaded at startup from <exe dir>\fonts
if (-not $SkipFonts) {
  & (Join-Path $PSScriptRoot 'bundle-fonts.ps1') -Dest (Join-Path $Stage 'fonts')
  # Inter is compiled into VibezCut; the caption tools also need the files to measure text
  $Inter = Join-Path $Stage 'fonts\Inter'
  New-Item -ItemType Directory -Force -Path $Inter | Out-Null
  Copy-Item (Join-Path $Root 'assets\fonts\Inter-*.ttf') $Inter
  Copy-Item (Join-Path $Root 'assets\fonts\OFL-Inter.txt') (Join-Path $Inter 'OFL.txt')
}
foreach ($f in 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'ATTRIBUTION.md') { Copy-Item (Join-Path $Root $f) $Stage }
$Base = (Select-String -Path (Join-Path $Root 'Cargo.toml') -Pattern '^version = "(.+)"' | Select-Object -First 1).Matches[0].Groups[1].Value
$Commit = (git -C $Root rev-parse --short HEAD)
Set-Content -Path (Join-Path $Stage 'VERSION.txt') -Value "VibezCut $Version`nbased on FilmCraft $Base`ncommit $Commit"

$Zip = Join-Path $Out "$Name-windows-x64.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path $Stage -DestinationPath $Zip
$Hash = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
Set-Content -Path "$Zip.sha256" -Value "$Hash  $(Split-Path -Leaf $Zip)"
Write-Output "==> $Zip"
Write-Output "    sha256 $Hash"
