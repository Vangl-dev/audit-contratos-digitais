@echo off
cd /d "%~dp0"
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -e ".[testes]"
if not exist perfil.yaml copy perfil.exemplo.yaml perfil.yaml
echo.
echo Pronto. Para abrir: abrir.bat
pause
