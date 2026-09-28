@echo off
REM TagStock RFID - inicia o servidor no PC (Windows), porta 8100
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python tagstock_servidor.py
