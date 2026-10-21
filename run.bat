@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PYTHON=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYTHON=py -3"

if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo.
    echo ERREUR : Python 3 n'est pas installe ou introuvable.
    echo Installe Python depuis https://www.python.org/downloads/
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo ERREUR pendant l'installation des dependances.
    pause
    exit /b 1
  )
)

echo.
echo Concert Agent : http://127.0.0.1:5000
echo.
".venv\Scripts\python.exe" app.py
pause
