<#
.SYNOPSIS
  Put a private Python into the VibezCut package, so the filmcraft-studio MCP server (Claude's live
  editing tools) runs on any PC without installing Python first.

.DESCRIPTION
  -Dest gets the official python.org embeddable CPython (Windows x64) with site-packages enabled and the
  live-editing packages (numpy<2, pillow, mcp) installed as prebuilt wheels. Transcription (PyTorch,
  faster-whisper) is NOT bundled: it needs gigabytes and an NVIDIA GPU; the updater prefers a system
  Python that already has the studio packages, so a full install keeps working.
  Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
  pwsh packaging/vibezcut/bundle-python.ps1 -Dest dist\vibezcut\VibezCut-0.2.11\python
#>
param(
  [Parameter(Mandatory = $true)] [string] $Dest,
  [string] $PyVersion = '3.12.10',
  [string] $Sha256 = ''
)
$ErrorActionPreference = 'Stop'

$url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$cache = Join-Path ([IO.Path]::GetTempPath()) "vibezcut-python-$PyVersion"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$zip = Join-Path $cache 'embed.zip'
if (-not (Test-Path $zip)) {
  Write-Output "==> download $url"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
}
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
if ($Sha256 -and $hash -ne $Sha256.ToLower()) {
  Remove-Item -Force $zip
  throw "Python embeddable zip: SHA-256 $hash does not match the pinned $Sha256"
}
Write-Output "    python-$PyVersion-embed-amd64.zip sha256 $hash"

if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
Expand-Archive -Path $zip -DestinationPath $Dest

# The embeddable Python ignores site-packages until its ._pth file says `import site`.
$pth = Get-ChildItem -Path $Dest -Filter 'python*._pth' | Select-Object -First 1
if (-not $pth) { throw "no ._pth file in the embeddable Python" }
$lines = @(Get-Content $pth.FullName | ForEach-Object { if ($_ -match '^\s*#\s*import site') { 'import site' } else { $_ } })
if ($lines -notcontains 'Lib\site-packages') { $lines += 'Lib\site-packages' }
if ($lines -notcontains 'import site') { $lines += 'import site' }
Set-Content -Path $pth.FullName -Value $lines -Encoding Ascii

$site = Join-Path $Dest 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $site | Out-Null

# The build machine's Python downloads wheels for CPython 3.12 / win_amd64 into the bundle.
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $pyExe = 'py'; $pyArgs = @('-3') } else { $pyExe = 'python'; $pyArgs = @() }
$pip = $pyArgs + @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile', '--target', $site,
  '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.12', '--implementation', 'cp',
  'numpy<2', 'pillow', 'mcp>=1.16,<2')
Write-Output "==> pip install numpy<2 pillow mcp>=1.16,<2 into the bundle"
& $pyExe @pip
if ($LASTEXITCODE -ne 0) { throw "pip install into the bundled Python failed ($LASTEXITCODE)" }

# Sanity: the bundled interpreter itself imports the packages.
& (Join-Path $Dest 'python.exe') -c "import mcp, numpy, PIL, sys; print('bundled python ok', sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw "the bundled Python cannot import the studio packages" }
$mb = [int]((Get-ChildItem -Recurse $Dest | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Output "==> $Dest ($mb MB)"
