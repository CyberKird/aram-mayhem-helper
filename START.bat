@echo off
REM Porneste helperul cu interpretorul din .venv. Nu folosi "python app.py"
REM direct: pe sistemul asta "python" rezolva catre venv-ul altui program.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Mediul virtual lipseste. Rulez instalarea automata...
  call INSTALL.bat
  exit /b
)
start "" ".venv\Scripts\pythonw.exe" app.py
