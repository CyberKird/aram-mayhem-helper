@echo off
REM Porneste helperul din sursa: interfata Electron (ui\) porneste singura
REM motorul cu interpretorul din .venv.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto install
if not exist "ui\node_modules\electron\dist\electron.exe" goto install
start "" "ui\node_modules\electron\dist\electron.exe" ui
exit /b

:install
echo Lipsesc dependentele. Rulez instalarea automata...
call INSTALL.bat
