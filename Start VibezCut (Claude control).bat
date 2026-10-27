@echo off
rem Starts VibezCut with its control channel so Claude can edit live in this window.
rem A fresh secret token is made for every session and stored only in your user profile.
setlocal
set "REPO=%~dp0"
set "FC_HOME="
if exist "%REPO%studio\studio.json" for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-Content -Raw '%REPO%studio\studio.json' | ConvertFrom-Json).filmcraft_home"`) do set "FC_HOME=%%H"
if "%FC_HOME%"=="" call :find "%REPO%."
if "%FC_HOME%"=="" call :find "%REPO%target\x86_64-pc-windows-msvc\release"
if "%FC_HOME%"=="" call :find "%REPO%target\release"
set "APP="
if exist "%FC_HOME%\VibezCut.exe" set "APP=%FC_HOME%\VibezCut.exe"
if "%APP%"=="" if exist "%FC_HOME%\filmcraft.exe" set "APP=%FC_HOME%\filmcraft.exe"
if "%APP%"=="" (
  echo Could not find VibezCut.exe. Build the repo or set filmcraft_home in studio\studio.json.
  pause
  exit /b 1
)
set "STATE=%USERPROFILE%\.filmcraft-studio"
if not exist "%STATE%" mkdir "%STATE%"
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString('x2') }) -join ''"`) do set "FILMCRAFT_CONTROL_TOKEN=%%T"
> "%STATE%\control.token" echo %FILMCRAFT_CONTROL_TOKEN%
start "" "%APP%" --control 9876 %*
endlocal
exit /b 0

:find
if exist "%~1\VibezCut.exe" set "FC_HOME=%~1"
if "%FC_HOME%"=="" if exist "%~1\filmcraft.exe" set "FC_HOME=%~1"
exit /b 0
