@echo off
REM Porneste helperul cu interpretorul din .venv. Nu folosi "python app.py"
REM direct: pe sistemul asta "python" rezolva catre venv-ul altui program.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" app.py
