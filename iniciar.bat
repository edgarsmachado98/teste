@echo off
chcp 65001 >nul
title VigIA
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 vigia.py
) else (
    python vigia.py
)

if errorlevel 1 (
    echo.
    echo Ocorreu um erro. Se o Python nao estiver instalado, baixe em https://www.python.org/downloads/
    echo e marque a opcao "Add python.exe to PATH" durante a instalacao.
)
pause
