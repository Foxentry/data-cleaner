@echo off
chcp 65001 >nul
title Foxentry Data Cleaner
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo.
        echo Python not found / Nenasel jsem Python. https://www.python.org/downloads/
        echo Tick "Add Python to PATH" during install.
        echo.
        pause
        exit /b 1
    )
)

rem The wizard opens in your browser. Set the API key there (gear icon) and Save.
%PY% run.py
echo.
pause
