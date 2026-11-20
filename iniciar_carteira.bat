@echo off
rem Abre a Carteira de Aportes. Para abrir junto com o Windows, veja TAILSCALE.md (passo 7).
cd /d "%~dp0"
title Carteira de Aportes
python app.py
pause
