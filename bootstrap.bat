@echo off
setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"
echo [admet-screening] portable bootstrap (Windows)
echo [admet-screening] logs are written to: logsif not defined PYTHON (
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYTHON set "PYTHON=%%i"
)
if not defined PYTHON set PYTHON=python
echo [admet-screening] interpreter: %PYTHON%
"%PYTHON%" bootstrap.py %*
set RC=%ERRORLEVEL%
echo [admet-screening] bootstrap exit=%RC%
if not "%RC%"=="0" (
  echo [admet-screening] FAILED. Open the newest log file:
  for /f "delims=" %%f in ('dir /b /o-d logsootstrap_*.log 2^>nul') do (
    if not defined ADT_LATEST set "ADT_LATEST=%%f"
  )
  if defined ADT_LATEST echo [admet-screening]   logs\%ADT_LATEST%
  echo [admet-screening] The log contains the full pip output and the return code.
)
exit /b %RC%
