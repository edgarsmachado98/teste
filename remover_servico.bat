@echo off
chcp 65001 >nul
title VigIA - remover inicializacao automatica
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Clique com o botao direito em remover_servico.bat e escolha "Executar como administrador".
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 vigia.py --remover-servico
) else (
    python vigia.py --remover-servico
)
pause
