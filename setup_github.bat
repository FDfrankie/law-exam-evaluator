@echo off
echo ========================================================
echo        Law Exam AI Grader - Setup GitHub Repository
echo ========================================================
echo.
echo 1. Open https://github.com/new in your browser.
echo 2. Enter a repository name (e.g. law-exam-evaluator).
echo    (DO NOT check "Add a README file" or ".gitignore")
echo 3. Click "Create repository" and copy the URL.
echo.
set /p REPO_URL="Enter your GitHub Repository URL: "

cd /d "%~dp0"
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git branch -M main

echo.
echo Pushing codebase to GitHub main branch...
git push -u origin main

echo.
echo ========================================================
echo GitHub repository linked and pushed successfully!
echo You can now go to https://share.streamlit.io to deploy.
echo For future updates, simply double-click git_push.bat.
echo ========================================================
pause
