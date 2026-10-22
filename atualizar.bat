@echo off
chcp 65001 >nul
title CORE RH - Atualizar
rem Atualiza o sistema a partir do ZIP baixado do GitHub, sem tocar na pasta "dados" (banco de dados).
rem Uso: de dois cliques (procura o ZIP mais recente em Downloads) ou arraste o ZIP sobre este arquivo.

rem roda a partir de uma copia temporaria, porque este proprio arquivo sera substituido pela versao nova
if not "%~2"=="--pasta" (
  copy /y "%~f0" "%TEMP%\core-rh-atualizar.bat" >nul
  "%TEMP%\core-rh-atualizar.bat" "%~1" --pasta "%~dp0."
  exit /b
)
cd /d "%~3"

netstat -ano | findstr /r /c:":3000 .*LISTENING" >nul
if not errorlevel 1 (
  echo.
  echo O sistema esta aberto ^(porta 3000 em uso^). Feche a janela preta do servidor e rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)

set "ZIP=%~1"
if not defined ZIP (
  for /f "delims=" %%f in ('dir /b /o-d "%USERPROFILE%\Downloads\teste-claude-work-schedule-generator-br-qozpwr*.zip" 2^>nul') do (
    if not defined ZIP set "ZIP=%USERPROFILE%\Downloads\%%f"
  )
)
if not defined ZIP (
  echo Nao encontrei o ZIP da atualizacao na pasta Downloads.
  echo Baixe o ZIP do GitHub e arraste o arquivo sobre este atualizar.bat.
  pause
  exit /b 1
)
echo Atualizacao: %ZIP%
echo Pasta do sistema: %CD%
echo.

rem 1. copia de seguranca da pasta dados (banco de dados)
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH\hmm"') do set "CARIMBO=%%t"
if not exist "dados" goto extrair
robocopy "dados" "backups-atualizacao\dados_%CARIMBO%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Falha ao copiar a pasta dados. Nada foi alterado.
  pause
  exit /b 1
)
echo Copia de seguranca dos dados: backups-atualizacao\dados_%CARIMBO%

:extrair
rem 2. extrai o ZIP numa pasta temporaria
set "TMPDIR=%TEMP%\core-rh-atualizacao"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TMPDIR%' -Force"
if errorlevel 1 (
  echo Nao foi possivel abrir o ZIP. Nada foi alterado.
  pause
  exit /b 1
)

rem 3. copia os arquivos novos por cima, sem a pasta dados nem as copias de seguranca
set "ORIGEM=%TMPDIR%"
for /d %%d in ("%TMPDIR%\*") do set "ORIGEM=%%d"
robocopy "%ORIGEM%" "%CD%" /E /XD dados backups-atualizacao /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Falha ao copiar os arquivos novos. Os dados nao foram alterados; tente de novo.
  pause
  exit /b 1
)
rmdir /s /q "%TMPDIR%"

echo.
echo Sistema atualizado. Os dados foram mantidos.
echo Abra o iniciar.bat e confira a versao no menu.
pause
