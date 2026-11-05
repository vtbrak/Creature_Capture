@echo off
rem Creature Capture - install (or update) the conda environment on Windows.
rem Double-click to run.
setlocal
cd /d "%~dp0"
set "ENV_NAME=creature_capture"

call scripts\find_conda.bat
if errorlevel 1 goto :fail

call "%CONDA_BAT%" env list | findstr /b /c:"%ENV_NAME% " >nul
if errorlevel 1 (
    echo Creating environment %ENV_NAME% - this can take several minutes...
    call "%CONDA_BAT%" env create -n %ENV_NAME% -f environment.yml
) else (
    echo Updating existing environment %ENV_NAME%...
    call "%CONDA_BAT%" env update -n %ENV_NAME% -f environment.yml --prune
)
if errorlevel 1 goto :fail

call "%CONDA_BAT%" activate %ENV_NAME%
if errorlevel 1 goto :fail
echo.
echo Running self-test...
python run_creature_capture.py --self-test
echo.
echo Done. Start the program with run_windows.bat
pause
exit /b 0

:fail
echo.
echo INSTALL FAILED - see the messages above.
pause
exit /b 1
