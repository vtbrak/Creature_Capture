@echo off
rem Creature Capture - start the program on Windows (run install_windows.bat first).
setlocal
cd /d "%~dp0"
set "ENV_NAME=creature_capture"

call scripts\find_conda.bat
if errorlevel 1 goto :fail

call "%CONDA_BAT%" activate %ENV_NAME%
if errorlevel 1 (
    echo The %ENV_NAME% environment is not installed. Run install_windows.bat first.
    goto :fail
)
python run_creature_capture.py %*
if errorlevel 1 (
    echo.
    echo Creature Capture exited with an error.
    goto :fail
)
exit /b 0

:fail
pause
exit /b 1
