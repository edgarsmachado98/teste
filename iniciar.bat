@echo off
rem Inicia o sistema de orcamentos no Windows
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" http://127.0.0.1:5000
.venv\Scripts\python app.py
