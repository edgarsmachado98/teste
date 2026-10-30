@echo off
chcp 65001 >nul
title VigIA - instalar inicializacao automatica
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Este instalador precisa de permissao de administrador.
    echo Clique com o botao direito em instalar_servico.bat e escolha "Executar como administrador".
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 vigia.py --instalar-servico
) else (
    python vigia.py --instalar-servico
)
pause
