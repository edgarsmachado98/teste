@echo off
chcp 65001 >nul
title Gestao de Pessoal RH
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js nao encontrado. Instale a versao LTS em https://nodejs.org e tente de novo.
  pause
  exit /b 1
)
node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)"
if errorlevel 1 (
  echo Versao do Node.js muito antiga. Instale a versao LTS em https://nodejs.org
  pause
  exit /b 1
)
echo Abrindo http://localhost:3000 ... Para encerrar, feche esta janela.
start "" cmd /c "timeout /t 2 >nul & start http://localhost:3000"
node --disable-warning=ExperimentalWarning server/server.js
pause
