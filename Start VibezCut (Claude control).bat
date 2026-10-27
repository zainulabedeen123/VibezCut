@echo off
rem Starts the editor with its control channel so Claude can edit live in this window.
rem A fresh secret token is made for every session and stored only in your user profile.
setlocal
set "REPO=%~dp0"
set "FC_HOME="
if exist "%REPO%studio\studio.json" for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-Content -Raw '%REPO%studio\studio.json' | ConvertFrom-Json).filmcraft_home"`) do set "FC_HOME=%%H"
if "%FC_HOME%"=="" if exist "%REPO%target\release\filmcraft.exe" set "FC_HOME=%REPO%target\release"
if "%FC_HOME%"=="" if exist "%REPO%dist\filmcraft.exe" set "FC_HOME=%REPO%dist"
if not exist "%FC_HOME%\filmcraft.exe" (
  echo Could not find filmcraft.exe. Build the repo or set filmcraft_home in studio\studio.json.
  pause
  exit /b 1
)
set "STATE=%USERPROFILE%\.filmcraft-studio"
if not exist "%STATE%" mkdir "%STATE%"
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString('x2') }) -join ''"`) do set "FILMCRAFT_CONTROL_TOKEN=%%T"
> "%STATE%\control.token" echo %FILMCRAFT_CONTROL_TOKEN%
start "" "%FC_HOME%\filmcraft.exe" --control 9876 %*
endlocal
