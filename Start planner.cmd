@echo off
setlocal
cd /d "%~dp0"
set "PYRUN="
if exist "%USERPROFILE%\AppData\Local\Python\bin\python.exe" set "PYRUN=%USERPROFILE%\AppData\Local\Python\bin\python.exe"
if defined PYRUN goto launch
where py.exe >nul 2>nul && set "PYRUN=py.exe"
if defined PYRUN goto launch
where python.exe >nul 2>nul && set "PYRUN=python.exe"
if defined PYRUN goto launch
echo This planner requires Python 3.11 or later.
pause
exit /b 1
:launch
"%PYRUN%" -B server.py --open --port 0
if errorlevel 1 pause
