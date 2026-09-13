@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"

%PYTHON% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo PyInstaller is required to build the Windows executable.
  echo Install it with: %PYTHON% -m pip install -r requirements-build.txt
  exit /b 1
)

%PYTHON% -m PyInstaller --clean --noconfirm --distpath "release" "course-gpa-ranker.spec"
if errorlevel 1 (
  echo.
  echo Build failed.
  exit /b 1
)

if not exist "dist" mkdir "dist"
copy /Y "release\course-gpa-ranker-v2.exe" "dist\course-gpa-ranker.exe" >nul

echo.
echo Single-file executable:
echo %~dp0release\course-gpa-ranker-v2.exe
endlocal
