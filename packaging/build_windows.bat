@echo off
rem Builds DocumentsManager.exe (dist\DocumentsManager.exe). Needs Python 3.12+, Node.js 20+ and git on the PATH.
rem Nothing is left behind in the calling console: variables (setlocal), code page (restored at both exits), directory (pushd/popd).
setlocal
for /f "tokens=2 delims=:" %%a in ('chcp') do set "OLDCP=%%a"
set "OLDCP=%OLDCP: =%"
chcp 65001 >nul
pushd "%~dp0\.."
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv-build\Scripts\python.exe" %PY% -m venv .venv-build || goto :fail
".venv-build\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :fail
".venv-build\Scripts\python.exe" -m pip install --quiet . pyinstaller pywebview || goto :fail
pushd frontend
call npm ci || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\fetch_tesseract.ps1 || goto :fail
".venv-build\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist --workpath build packaging\documents-manager.spec || goto :fail
echo.
echo Built: %CD%\dist\DocumentsManager.exe
popd
chcp %OLDCP% >nul
exit /b 0
:fail
echo.
echo The build failed (see above).
popd
chcp %OLDCP% >nul
exit /b 1
