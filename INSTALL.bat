@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title ARAM Mayhem Helper - instalare
echo === ARAM Mayhem Helper: instalare ===
echo.

rem 1) Gaseste Python (launcherul "py", apoi "python", apoi foldere standard).
rem Daca nu e niciunul, il instaleaza singur prin winget.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (python --version >nul 2>nul && set "PY=python")
if not defined PY (
  for %%v in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
  )
)
if not defined PY (
  echo Python nu e instalat. Incerc instalarea automata prin winget...
  winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
  for %%v in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
  )
  if not defined PY (where py >nul 2>nul && set "PY=py -3")
)
if not defined PY (
  echo.
  echo Nu am reusit sa instalez Python automat.
  echo Descarca-l de pe https://www.python.org/downloads/ si bifeaza
  echo "Add python.exe to PATH" la instalare, apoi ruleaza din nou INSTALL.bat.
  pause
  exit /b 1
)
echo Python gasit.
echo.

rem 2) Creeaza mediul virtual daca lipseste sau e stricat (ex. Python-ul din
rem sistem s-a schimbat intre timp). Test rapid: daca pywin32 importa, venv-ul
rem e bun si il refolosim; altfel il recreem de la zero.
set "VENV_OK="
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\python.exe" -c "import win32gui" >nul 2>nul && set "VENV_OK=1"
)
if defined VENV_OK (
  echo Mediul virtual exista si e OK - il refolosesc.
) else (
  if exist ".venv" rmdir /s /q ".venv"
  echo [1/3] Creez mediul virtual .venv...
  !PY! -m venv .venv
  if errorlevel 1 (
    echo Eroare la crearea mediului virtual.
    pause
    exit /b 1
  )
)

rem 3) Instaleaza dependentele de rulare.
echo [2/3] Instalez dependentele (dureaza 1-2 minute)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Eroare la instalarea dependentelor. Verifica conexiunea la internet si ruleaza din nou.
  pause
  exit /b 1
)

rem 4) Verifica instalarea cu selfcheck-ul (offline, fara League pornit).
echo [3/3] Verific instalarea...
".venv\Scripts\python.exe" app.py --selfcheck
if errorlevel 1 (
  echo.
  echo Selfcheck-ul a esuat - vezi mesajele de mai sus.
  pause
  exit /b 1
)

rem 5) Lasa o scurtatura pe desktop.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ARAM Mayhem Helper.lnk')); $lnk.TargetPath = '%cd%\.venv\Scripts\pythonw.exe'; $lnk.Arguments = 'app.py'; $lnk.WorkingDirectory = '%cd%'; $lnk.IconLocation = '%cd%\icon.ico'; $lnk.Save()"

echo.
echo === Gata! ===
echo Porneste aplicatia din scurtatura "ARAM Mayhem Helper" de pe desktop
echo (sau cu START.bat din acest folder).
pause
