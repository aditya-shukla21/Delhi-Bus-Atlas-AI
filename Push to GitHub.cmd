@echo off
setlocal
cd /d "%~dp0"
where git.exe >nul 2>nul
if errorlevel 1 (
  echo Git is not installed. Install Git for Windows from https://git-scm.com/download/win
  pause
  exit /b 1
)
if not exist .git git init
for /f "delims=" %%N in ('git config user.name') do set "GIT_NAME=%%N"
if not defined GIT_NAME (
  set /p GIT_NAME=Enter your Git commit name: 
  git config user.name "%GIT_NAME%"
)
for /f "delims=" %%E in ('git config user.email') do set "GIT_EMAIL=%%E"
if not defined GIT_EMAIL (
  set /p GIT_EMAIL=Enter your Git commit email: 
  git config user.email "%GIT_EMAIL%"
)
git branch -M main
git add .
git commit -m "Initial commit - Delhi Bus Atlas AI"
git remote remove origin 2>nul
git remote add origin https://github.com/aditya-shukla21/Delhi-Bus-Atlas-AI.git
git push -u origin main
if errorlevel 1 (
  echo Push did not complete. Sign in to GitHub if prompted, then run this file again.
  pause
  exit /b 1
)
echo Project pushed successfully.
pause
