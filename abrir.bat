@echo off
cd /d "%~dp0"
.venv\Scripts\python -W ignore -m auditoria_contratos %*
